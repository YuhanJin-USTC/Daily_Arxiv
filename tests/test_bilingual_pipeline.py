import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from ai.enhance import resume_rows
from ai.errors import EnhancementError
from ai.quality import FIELDS, read_records
from ai.reuse import generation_provenance
from ai.storage import digest, write_json, write_jsonl
from scripts.apply_staged import apply
from scripts.bilingual_daily import load_state, stage_language, stage_raw
from scripts.migrate_history import migrate
from scripts.stage_daily import stage as stage_legacy
from to_md.convert import convert

DAY = "2026-10-21"
GOOD = {field: "Valid " + field for field in FIELDS}


def paper(identifier="2610.00001"):
    return {
        "id": identifier,
        "title": "Title",
        "summary": "Exact abstract",
        "authors": ["Author"],
        "categories": ["physics.plasm-ph"],
        "abs": "https://arxiv.org/abs/" + identifier,
        "pdf": "https://arxiv.org/pdf/" + identifier,
    }


def generate(rows, language, progress):
    results = [{**row, "AI": {**GOOD, **row.get("AI", {})}} for row in rows]
    progress(results, None)
    return results


class BilingualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "published"
        (self.source / "data").mkdir(parents=True)
        self.number = 0

    def output(self):
        self.number += 1
        return self.root / f"stage-{self.number}"

    def raw(self, rows):
        raw, audit = self.root / "incoming.jsonl", self.root / "audit.json"
        write_jsonl(raw, rows)
        write_json(
            audit,
            {
                "complete": True,
                "expected_ids": [row["id"] for row in rows],
                "excluded_published_ids": [],
            },
        )
        output = self.output()
        report = stage_raw(self.source, raw, output, DAY, audit)
        apply(self.source, output)
        return report

    def language(self, language, generator=generate, ids=None):
        output = self.output()
        report = stage_language(self.source, output, language, generator, ids=ids)
        apply(self.source, output)
        return report

    def test_raw_first_historical_baseline_and_independent_languages(self):
        historical = paper("2610.00009")
        write_jsonl(self.source / "data/2026-10-20.jsonl", [historical])
        report = self.raw([paper()])
        self.assertEqual(report["added_ids"], [paper()["id"]])
        state = load_state(self.source)
        self.assertEqual(state["historical_ids"], [historical["id"]])
        self.assertFalse(list((self.source / "data").glob("*AI*")))
        self.language("English")
        state = load_state(self.source)
        self.assertEqual(
            state["discoveries"][paper()["id"]]["languages"],
            {"English": "complete", "Chinese": "pending"},
        )
        self.raw([])
        self.language("Chinese")
        generator = Mock(side_effect=AssertionError("Already complete"))
        self.language("English", generator)
        self.language("Chinese", generator)
        generator.assert_not_called()
        self.assertFalse(
            (self.source / "data/2026-10-20_AI_enhanced_Chinese.jsonl").exists()
        )
        self.assertTrue((self.source / f"data/{DAY}_English.md").exists())
        self.assertTrue((self.source / f"data/{DAY}_Chinese.md").exists())

    def test_limited_ids_keep_unselected_pending_and_checkpoints_in_both_languages(
        self,
    ):
        rows = [paper(), paper("2610.00002"), paper("2610.00003")]
        self.raw(rows)

        def interrupt(items, language, progress):
            self.assertEqual(len(items), 1)
            raise EnhancementError(
                "Synthetic failure", {**items[0], "AI": {"tldr": "Keep partial"}}
            )

        self.language("English", interrupt, ids=(rows[0]["id"],))
        checkpoint = self.source / "data/ai-checkpoints/English.json"
        retained = json.loads(checkpoint.read_text())["records"][rows[0]["id"]]
        calls = []

        def limited(items, language, progress):
            calls.append((language, [row["id"] for row in items]))
            self.assertEqual([row["id"] for row in items], [rows[1]["id"]])
            return generate(items, language, progress)

        report = self.language("English", limited, ids=(rows[1]["id"] + "v2",))
        self.assertEqual(report["selected_ids"], [rows[1]["id"]])
        self.assertEqual(
            json.loads(checkpoint.read_text())["records"][rows[0]["id"]], retained
        )
        self.language("Chinese", interrupt, ids=(rows[1]["id"],))
        self.raw([])
        self.language("Chinese", limited, ids=(rows[1]["id"],))
        self.assertEqual(
            calls, [("English", [rows[1]["id"]]), ("Chinese", [rows[1]["id"]])]
        )
        state = load_state(self.source)
        for row in (rows[0], rows[2]):
            self.assertEqual(
                state["discoveries"][row["id"]]["languages"],
                {"English": "pending", "Chinese": "pending"},
            )
        generator = Mock(side_effect=AssertionError("Selected paper is complete"))
        for language in ("English", "Chinese"):
            self.language(language, generator, ids=(rows[1]["id"],))
        generator.assert_not_called()

    def test_limited_ids_reject_history_unknown_empty_duplicates_and_changed_raw(self):
        historical = paper("2610.00009")
        write_jsonl(self.source / "data/2026-10-20.jsonl", [historical])
        self.raw([paper()])
        generator = Mock()
        for ids in (
            (historical["id"],),
            ("2610.00008",),
            (),
            (paper()["id"], paper()["id"] + "v2"),
        ):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                stage_language(
                    self.source, self.output(), "English", generator, ids=ids
                )
        raw = self.source / f"data/{DAY}.jsonl"
        write_jsonl(raw, [{**paper(), "summary": "Changed abstract"}])
        with self.assertRaisesRegex(ValueError, "source or abstract"):
            stage_language(
                self.source, self.output(), "English", generator, ids=(paper()["id"],)
            )
        write_jsonl(raw, [{**paper(), "title": "Changed title"}])
        with self.assertRaisesRegex(ValueError, "source or abstract"):
            stage_language(
                self.source, self.output(), "English", generator, ids=(paper()["id"],)
            )
        write_jsonl(raw, [])
        with self.assertRaisesRegex(ValueError, "source or abstract"):
            stage_language(
                self.source, self.output(), "English", generator, ids=(paper()["id"],)
            )
        generator.assert_not_called()

    def test_partial_failure_persists_success_and_retries_without_new_papers(self):
        rows = [paper(), paper("2610.00002")]
        self.raw(rows)
        self.language("English")

        def interrupt(items, language, progress):
            complete = {**items[0], "AI": GOOD}
            partial = {**items[1], "AI": {"tldr": "Retained TLDR"}}
            progress([complete], partial)
            error = EnhancementError("Synthetic failure", partial)
            error.completed = [complete]
            raise error

        failed = self.language("Chinese", interrupt)
        self.assertTrue(failed["failures"])
        target = self.source / f"data/{DAY}_AI_enhanced_Chinese.jsonl"
        original = target.read_bytes()
        self.assertEqual(len(read_records(target)), 1)
        self.raw([])
        called = []

        def recovered(items, language, progress):
            called.extend(item["id"] for item in items)
            self.assertEqual(items[0]["AI"]["tldr"], "Retained TLDR")
            return generate(items, language, progress)

        self.language("Chinese", recovered)
        self.assertEqual(called, [rows[1]["id"]])
        self.assertTrue(target.read_bytes().startswith(original))
        self.assertEqual(len(read_records(target)), 2)

    def test_new_same_day_discovery_preserves_bound_partial_reuse(self):
        self.raw([paper()])

        def failed(items, language, progress):
            raise EnhancementError(
                "Synthetic", {**items[0], "AI": {"tldr": "retained"}}
            )

        self.language("Chinese", failed)
        self.raw([paper("2610.00002")])
        called = []

        def recovered(items, language, progress):
            called.extend(item["id"] for item in items)
            self.assertEqual(items[0]["AI"]["tldr"], "retained")
            return generate(items, language, progress)

        self.language("Chinese", recovered)
        self.assertEqual(called, ["2610.00001", "2610.00002"])

    def test_moderation_failure_does_not_publish_complete_but_unaccepted_fields(self):
        self.raw([paper()])

        def rejected(items, language, progress):
            row = {**items[0], "AI": GOOD}
            error = EnhancementError("Manual content review required", row)
            error.completed = []
            raise error

        self.language("Chinese", rejected)
        self.assertFalse(
            (self.source / f"data/{DAY}_AI_enhanced_Chinese.jsonl").exists()
        )
        self.assertEqual(
            load_state(self.source)["discoveries"][paper()["id"]]["languages"][
                "Chinese"
            ],
            "pending",
        )

    def test_raw_requires_complete_coverage_and_stage_rejects_changed_state(self):
        raw, audit = self.root / "incoming.jsonl", self.root / "audit.json"
        write_jsonl(raw, [paper()])
        write_json(audit, {"complete": False})
        with self.assertRaises(ValueError):
            stage_raw(self.source, raw, self.output(), DAY, audit)
        self.raw([paper()])
        output = self.output()
        stage_language(self.source, output, "English", generate)
        state = self.source / "data/pipeline-state.json"
        state.write_bytes(state.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            apply(self.source, output)
        self.assertFalse(
            (self.source / f"data/{DAY}_AI_enhanced_English.jsonl").exists()
        )

    def test_checkpoint_rejects_wrong_prompt_model_source_language_abstract(self):
        self.raw([paper()])

        def failed(items, language, progress):
            raise EnhancementError(
                "Synthetic", {**items[0], "AI": {"tldr": "retained"}}
            )

        self.language("Chinese", failed)
        path = self.source / "data/ai-checkpoints/Chinese.json"
        original = json.loads(path.read_text())
        for key, value in [
            ("language", "English"),
            ("provenance", {}),
            (
                "records",
                {
                    paper()["id"]: {
                        "summary_sha256": "wrong",
                        "source_sha256": "wrong",
                        "AI": GOOD,
                    }
                },
            ),
        ]:
            write_json(path, {**original, key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                stage_language(self.source, self.output(), "Chinese", generate)
        write_json(path, original)
        cp = self.root / "checkpoint.json"
        raw = self.source / f"data/{DAY}.jsonl"
        saved = {
            "source_sha256": digest(raw),
            "language": "English",
            "provenance": generation_provenance(),
            "completed": [{**paper(), "AI": GOOD}],
        }
        for updates in (
            {"provenance": {}},
            {"source_sha256": "wrong"},
            {"language": "Chinese"},
            {"completed": [{**paper(), "summary": "changed", "AI": GOOD}]},
        ):
            write_json(cp, {**saved, **updates})
            with self.assertRaises(ValueError):
                resume_rows([paper()], cp, digest(raw), "English")

    def test_legacy_raw_staging_rejects_unbound_ai_before_generation(self):
        raw = self.root / "raw.jsonl"
        write_jsonl(raw, [{**paper(), "AI": GOOD}])
        generator = Mock()
        with self.assertRaisesRegex(ValueError, "unbound AI"):
            stage_legacy(
                self.source, raw, self.output(), DAY, generator, language="Chinese"
            )
        generator.assert_not_called()

    def test_markdown_filename_refuses_wrong_language(self):
        raw = self.root / f"{DAY}_AI_enhanced_Chinese.jsonl"
        write_jsonl(raw, [{**paper(), "AI": GOOD}])
        with self.assertRaises(ValueError):
            convert(raw, "English")
        self.assertEqual(convert(raw, "Chinese").name, f"{DAY}_Chinese.md")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cn, self.en = self.root / "cn", self.root / "en"
        for source, language in ((self.cn, "Chinese"), (self.en, "English")):
            write_jsonl(source / f"data/{DAY}.jsonl", [paper()])
            write_jsonl(
                source / f"data/{DAY}_AI_enhanced_{language}.jsonl",
                [{**paper(), "AI": GOOD}],
            )
            (source / f"data/{DAY}.md").write_bytes(
                (language + " original\r\n").encode()
            )

    def test_union_exact_ai_markdown_and_repeatable_complete_index(self):
        write_jsonl(self.en / f"data/{DAY}.jsonl", [paper(), paper("2610.00002")])
        write_jsonl(self.en / "data/2026-09-14.jsonl", [paper("2609.00001")])
        first, second = self.root / "first", self.root / "second"
        a = migrate(self.cn, self.en, first)
        b = migrate(self.cn, self.en, second)
        self.assertEqual(a, b)
        self.assertEqual(
            [row["id"] for row in read_records(first / f"data/{DAY}.jsonl")],
            ["2610.00001", "2610.00002"],
        )
        for source, language in ((self.cn, "Chinese"), (self.en, "English")):
            name = f"data/{DAY}_AI_enhanced_{language}.jsonl"
            self.assertEqual((source / name).read_bytes(), (first / name).read_bytes())
            self.assertEqual(
                (source / f"data/{DAY}.md").read_bytes(),
                (first / f"data/{DAY}_{language}.md").read_bytes(),
            )
        self.assertIn("2026-09-14.jsonl", (first / "assets/file-list.txt").read_text())
        self.assertEqual(
            len(
                json.loads((first / "data/pipeline-state.json").read_text())[
                    "historical_ids"
                ]
            ),
            3,
        )
        with self.assertRaises(ValueError):
            migrate(self.cn, self.en, first)

    def test_metadata_conflict_stops_without_publishable_candidate(self):
        write_jsonl(
            self.en / f"data/{DAY}.jsonl",
            [{**paper(), "summary": "Conflicting abstract"}],
        )
        output = self.root / "conflict"
        with self.assertRaisesRegex(ValueError, "migration conflicts"):
            migrate(self.cn, self.en, output)
        report = json.loads((output / "migration-manifest.json").read_text())
        self.assertFalse(report["complete"])
        self.assertEqual(report["conflicts"][0]["kind"], "raw_metadata")
        self.assertFalse((output / "data").exists())

    def test_same_language_conflict_and_missing_raw_stop(self):
        name = f"data/{DAY}_AI_enhanced_Chinese.jsonl"
        write_jsonl(
            self.en / name,
            [{**paper(), "AI": {**GOOD, "tldr": "Different valid answer"}}],
        )
        with self.assertRaises(ValueError):
            migrate(self.cn, self.en, self.root / "conflict")

    def test_orphan_ai_date_without_any_raw_file_stops(self):
        write_jsonl(
            self.en / "data/2026-09-14_AI_enhanced_English.jsonl",
            [{**paper("2609.00001"), "AI": GOOD}],
        )
        output = self.root / "orphan"
        with self.assertRaisesRegex(ValueError, "migration conflicts"):
            migrate(self.cn, self.en, output)
        conflicts = json.loads((output / "migration-manifest.json").read_text())[
            "conflicts"
        ]
        self.assertEqual(
            conflicts,
            [
                {
                    "kind": "ai_without_raw",
                    "date": "2026-09-14",
                    "language": "English",
                    "ids": ["2609.00001"],
                }
            ],
        )
        self.assertFalse((output / "data").exists())

    def test_healthy_ai_exact_abstract_mismatch_stops(self):
        write_jsonl(
            self.en / f"data/{DAY}_AI_enhanced_English.jsonl",
            [{**paper(), "summary": "Exact abstract ", "AI": GOOD}],
        )
        output = self.root / "abstract"
        with self.assertRaisesRegex(ValueError, "migration conflicts"):
            migrate(self.cn, self.en, output)
        conflicts = json.loads((output / "migration-manifest.json").read_text())[
            "conflicts"
        ]
        self.assertEqual(conflicts[0]["kind"], "ai_abstract")
        self.assertEqual(conflicts[0]["raw_summary"], "Exact abstract")
        self.assertEqual(conflicts[0]["ai_summary"], "Exact abstract ")
        self.assertFalse((output / "data").exists())

    def test_unknown_jsonl_conflict_stops_instead_of_discarding_content(self):
        write_jsonl(self.cn / "data/legacy.jsonl", [paper()])
        write_jsonl(self.en / "data/legacy.jsonl", [paper("2610.00002")])
        output = self.root / "unknown"
        with self.assertRaisesRegex(ValueError, "migration conflicts"):
            migrate(self.cn, self.en, output)
        conflicts = json.loads((output / "migration-manifest.json").read_text())[
            "conflicts"
        ]
        self.assertEqual(conflicts[0]["kind"], "unknown_jsonl")
        self.assertNotEqual(
            conflicts[0]["before_sha256"], conflicts[0]["incoming_sha256"]
        )
        self.assertFalse((output / "data").exists())
