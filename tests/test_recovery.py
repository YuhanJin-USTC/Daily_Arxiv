from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ai.config import settings
from ai.enhance import process_all_items, resume_rows
from ai.errors import EnhancementError
from ai.quality import FIELDS, read_records, valid_ai
from ai.recover import load_checkpoints, plan_recovery, stage_recovery
from ai.storage import digest, write_json
from scripts.apply_staged import apply
from scripts.stage_daily import stage
from to_md.convert import convert

GOOD = {key: "Good " + key for key in FIELDS}
DAY = date(2026, 10, 20)


def row(i, good=True):
    return {
        "id": f"2610.{i:05}",
        "title": "Paper",
        "authors": ["A"],
        "summary": "Abstract",
        "categories": ["physics.plasm-ph"],
        "abs": f"https://arxiv.org/abs/2610.{i:05}",
        "AI": dict(GOOD)
        if good
        else {**GOOD, "conclusion": "Conclusion extraction failed"},
    }


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "published"
        (self.source / "data").mkdir(parents=True)
        self.language = settings()["language"]
        self.output = self.root / "candidate"
        self.rows = [row(i, i != 41) for i in range(59)]
        self.rows[41]["id"] = "2610.26164"
        self.enhanced = (
            self.source / "data" / f"{DAY}_AI_enhanced_{self.language}.jsonl"
        )
        self.raw = self.source / "data" / f"{DAY}.jsonl"
        self.original = b"".join(
            json.dumps(
                r,
                ensure_ascii=i % 2 == 0,
                separators=(",", ":") if i % 3 == 0 else None,
            ).encode()
            + b"\r\n"
            for i, r in enumerate(self.rows)
        )
        self.enhanced.write_bytes(self.original)
        self.raw.write_text(
            "".join(
                json.dumps({k: v for k, v in r.items() if k != "AI"}) + "\n"
                for r in self.rows
            )
        )
        self.plan = plan_recovery(
            self.source / "data", DAY, DAY, self.language, ("2610.26164",), 59
        )
        self.generate = Mock(
            side_effect=lambda item, lang: {
                "id": "untrusted metadata",
                "AI": {**GOOD, "tldr": "Must not replace"},
            }
        )

    def run_stage(self, **kwargs):
        return stage_recovery(
            self.source / "data", self.output, self.plan, self.generate, **kwargs
        )

    def test_single_target_58_byte_identical_and_valid_fields_metadata_preserved(self):
        manifest = self.run_stage()
        data = (self.output / "data" / self.enhanced.name).read_bytes()
        self.assertTrue(manifest["complete"])
        self.generate.assert_called_once()
        self.assertEqual(self.generate.call_args.args[0]["id"], "2610.26164")
        self.assertEqual(
            [
                i
                for i, (a, b) in enumerate(
                    zip(self.original.splitlines(True), data.splitlines(True))
                )
                if a != b
            ],
            [41],
        )
        self.assertEqual(self.enhanced.read_bytes(), self.original)
        parsed = read_records(self.output / "data" / self.enhanced.name)
        self.assertEqual(parsed[41], {**self.rows[41], "AI": GOOD})
        self.assertEqual(apply(self.source, self.output, True), 2)
        self.assertEqual(self.enhanced.read_bytes(), self.original)
        apply(self.source, self.output)
        self.assertEqual(self.enhanced.read_bytes(), data)

    def test_multi_failure_repair_for_both_languages_preserves_healthy_rows(self):
        for language in ("English", "Chinese"):
            with self.subTest(language=language):
                source = self.root / language
                source.mkdir()
                raw = source / f"{DAY}.jsonl"
                enhanced = source / f"{DAY}_AI_enhanced_{language}.jsonl"
                rows = [row(1, False), row(2, True), row(3, False)]
                raw.write_text("".join(json.dumps(r) + "\n" for r in rows))
                enhanced.write_bytes(
                    b"".join(json.dumps(r).encode() + b"\r\n" for r in rows)
                )
                before = enhanced.read_bytes()
                plan = plan_recovery(source, DAY, DAY, language)
                out = self.root / (language + "-out")
                stage_recovery(source, out, plan, lambda r, language: {**r, "AI": GOOD})
                self.assertEqual(enhanced.read_bytes(), before)
                self.assertEqual(
                    (out / "data" / enhanced.name).read_bytes().splitlines(True)[1],
                    before.splitlines(True)[1],
                )

    def test_partial_checkpoint_resumes_without_overwriting_valid_fields(self):
        self.generate.side_effect = EnhancementError(
            "incomplete", {"AI": {"result": "A retained result"}}
        )
        with self.assertRaises(EnhancementError):
            self.run_stage()
        self.assertFalse(
            json.loads((self.output / "manifest.json").read_text())["complete"]
        )
        self.assertFalse((self.output / "data" / self.enhanced.name).exists())
        saved = self.output / "checkpoints"
        self.output = self.root / "resumed"
        self.generate.side_effect = lambda item, lang: {**item, "AI": GOOD}
        self.run_stage(resume=saved)
        self.assertEqual(self.enhanced.read_bytes(), self.original)
        self.assertEqual(self.generate.call_args.args[0]["AI"]["tldr"], GOOD["tldr"])

    def test_stale_checkpoint_or_source_and_existing_output_are_rejected(self):
        checkpoint = self.root / "checkpoints"
        checkpoint.mkdir()
        write_json(
            checkpoint / f"{DAY}-2610.26164.json",
            {
                "id": "2610.26164",
                "language": self.language,
                "source_sha256": "stale",
                "AI": GOOD,
            },
        )
        with self.assertRaises(ValueError):
            self.run_stage(resume=checkpoint)
        self.generate.assert_not_called()
        self.output = self.root / "stale-source"
        self.enhanced.write_bytes(self.original + b"\n")
        with self.assertRaises(ValueError):
            self.run_stage()
        self.generate.assert_not_called()
        self.enhanced.write_bytes(self.original)
        self.output.mkdir()
        with self.assertRaises(ValueError):
            self.run_stage()

    def test_missing_duplicate_extra_failed_and_wrong_count_fail_before_model(self):
        variants = [
            self.rows[:-1],
            [*self.rows, self.rows[0]],
            [
                {**r, "id": "2610.99999"} if r["id"] == "2610.26164" else r
                for r in self.rows
            ],
            [{**r, "AI": {}} if i == 0 else r for i, r in enumerate(self.rows)],
        ]
        for rows in variants:
            self.enhanced.write_text("".join(json.dumps(r) + "\n" for r in rows))
            with self.assertRaises(ValueError):
                plan_recovery(
                    self.source / "data", DAY, DAY, self.language, ("2610.26164",), 59
                )

    def test_apply_rejects_changed_source_or_non_target_bytes(self):
        self.run_stage()
        self.enhanced.write_bytes(self.original + b"\n")
        with self.assertRaises(ValueError):
            apply(self.source, self.output)
        self.enhanced.write_bytes(self.original)
        p = self.output / "data" / self.enhanced.name
        p.write_bytes(b" " + p.read_bytes())
        with self.assertRaises(ValueError):
            apply(self.source, self.output)
        self.assertEqual(self.enhanced.read_bytes(), self.original)

    def test_all_healthy_is_noop_and_markdown_rejects_bad_input(self):
        md = self.source / "data" / f"{DAY}.md"
        md.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            convert(self.enhanced)
        self.assertEqual(md.read_bytes(), b"keep")
        for r in self.rows:
            r["AI"] = GOOD
        self.enhanced.write_text("".join(json.dumps(r) + "\n" for r in self.rows))
        plan = plan_recovery(self.source / "data", DAY, DAY, self.language)
        self.assertEqual(plan[0]["failed"], 0)
        stage_recovery(self.source / "data", self.output, plan, self.generate)
        self.generate.assert_not_called()
        self.assertFalse((self.output / "data").exists())

    def test_same_day_backfill_only_appends_after_healthy_original_bytes(self):
        for r in self.rows:
            r["AI"] = GOOD
        original = b"".join(json.dumps(r).encode() + b"\r\n" for r in self.rows)
        self.enhanced.write_bytes(original)
        incoming = self.root / "new.jsonl"
        incoming.write_text(json.dumps(row(999)) + "\n")
        generated = Mock(side_effect=lambda rows, language, **kwargs: rows)
        stage(self.source, incoming, self.output, str(DAY), generated)
        self.assertTrue(
            (self.output / "data" / self.enhanced.name)
            .read_bytes()
            .startswith(original)
        )
        self.assertEqual(self.enhanced.read_bytes(), original)
        self.assertEqual(apply(self.source, self.output, True), 4)
        self.assertEqual(
            len(read_records(self.output / "data" / self.enhanced.name)), 60
        )

    def test_backfill_refuses_old_failed_data_before_any_generation(self):
        incoming = self.root / "new.jsonl"
        incoming.write_text(json.dumps(row(999)) + "\n")
        generated = Mock()
        with self.assertRaises(ValueError):
            stage(self.source, incoming, self.output, str(DAY), generated)
        generated.assert_not_called()

    def test_backfill_resume_reuses_checkpoint_fields_and_preserves_source(self):
        for item in self.rows:
            item["AI"] = GOOD
        self.enhanced.write_text("".join(json.dumps(r) + "\n" for r in self.rows))
        original = self.enhanced.read_bytes()
        incoming = self.root / "new.jsonl"
        pending = row(999, False)
        pending.pop("AI")
        incoming.write_text(json.dumps(pending) + "\n")
        checkpoint = self.root / "checkpoint.json"
        retained = {"tldr": "Already generated and retained"}
        write_json(
            checkpoint,
            {
                "source_sha256": digest(incoming),
                "language": self.language,
                "completed": [],
                "partial": {**pending, "AI": retained},
            },
        )
        generated = Mock(
            side_effect=lambda rows, language, **kwargs: [
                {**r, "AI": {**GOOD, **r.get("AI", {})}} for r in rows
            ]
        )
        stage(
            self.source, incoming, self.output, str(DAY), generated, resume=checkpoint
        )
        self.assertEqual(generated.call_args.args[0][0]["AI"], retained)
        candidate = self.output / "data" / self.enhanced.name
        self.assertTrue(candidate.read_bytes().startswith(original))
        self.assertEqual(read_records(candidate)[-1]["AI"]["tldr"], retained["tldr"])
        self.assertEqual(self.enhanced.read_bytes(), original)

    def test_daily_checkpoint_cannot_cross_source_or_language(self):
        checkpoint = self.root / "daily.json"
        write_json(
            checkpoint,
            {
                "source_sha256": digest(self.raw),
                "language": self.language,
                "completed": [{**self.rows[0], "AI": GOOD}],
                "partial": None,
            },
        )
        resumed = resume_rows(self.rows, checkpoint, digest(self.raw), self.language)
        self.assertEqual(resumed[0]["AI"], GOOD)
        for key, lang in [("stale", self.language), (digest(self.raw), "other")]:
            with self.assertRaises(ValueError):
                resume_rows(self.rows, checkpoint, key, lang)

    def test_backfill_checkpoints_each_success_before_the_next_request(self):
        checkpoint = self.root / "progress.json"
        items = [row(10), row(11)]

        def process(chain, item, language):
            if item["id"] == items[1]["id"]:
                saved = json.loads(checkpoint.read_text())
                self.assertEqual(saved["completed"], [items[0]])
                raise KeyboardInterrupt("simulated cancellation")
            return item

        with patch("ai.enhance.process_single_item", side_effect=process):
            with self.assertRaises(KeyboardInterrupt):
                process_all_items(
                    items,
                    self.language,
                    chain=Mock(),
                    progress=lambda completed, partial: write_json(
                        checkpoint, {"completed": completed, "partial": partial}
                    ),
                )
        self.assertEqual(json.loads(checkpoint.read_text())["completed"], [items[0]])

    def test_checkpoint_write_failure_stops_before_another_model_request(self):
        process = Mock(side_effect=lambda chain, item, language: item)
        with patch("ai.enhance.process_single_item", process):
            with self.assertRaises(OSError):
                process_all_items(
                    [row(10), row(11)],
                    self.language,
                    chain=Mock(),
                    progress=Mock(side_effect=OSError("disk full")),
                )
        self.assertEqual(process.call_count, 1)

    def test_success_source_reuses_only_matching_abstract_and_language(self):
        archive = self.root / "successes"
        archive.mkdir()
        matched = {**self.rows[41], "AI": GOOD}
        (archive / f"2026-10-19_AI_enhanced_{self.language}.jsonl").write_text(
            json.dumps(matched) + "\n"
        )
        manifest = self.run_stage(success_source=archive)
        self.generate.assert_not_called()
        self.assertEqual(manifest["entries"][0]["reused_ids"], ["2610.26164"])
        self.assertEqual(manifest["entries"][0]["model_paper_ids"], [])
        self.assertEqual(apply(self.source, self.output, True), 2)
        self.output = self.root / "different-abstract"
        matched["summary"] = "A changed abstract"
        (archive / f"2026-10-19_AI_enhanced_{self.language}.jsonl").write_text(
            json.dumps(matched) + "\n"
        )
        other = "English" if self.language == "Chinese" else "Chinese"
        (archive / f"2026-10-19_AI_enhanced_{other}.jsonl").write_text(
            json.dumps({**matched, "summary": "Abstract"}) + "\n"
        )
        self.run_stage(success_source=archive)
        self.generate.assert_called_once()

    def test_conflicts_only_block_requested_missing_fields(self):
        archive = self.root / "successes"
        archive.mkdir()
        for day, conclusion in [(18, "First"), (19, "Second")]:
            (archive / f"2026-10-{day}_AI_enhanced_{self.language}.jsonl").write_text(
                json.dumps({**self.rows[41], "AI": {**GOOD, "conclusion": conclusion}})
                + "\n"
            )
        with self.assertRaises(ValueError):
            self.run_stage(success_source=archive)
        self.generate.assert_not_called()
        for day in (18, 19):
            (archive / f"2026-10-{day}_AI_enhanced_{self.language}.jsonl").write_text(
                json.dumps({**self.rows[41], "AI": {**GOOD, "tldr": str(day)}}) + "\n"
            )
        self.run_stage(success_source=archive)
        self.generate.assert_not_called()
        self.assertEqual(
            read_records(self.output / "data" / self.enhanced.name)[41]["AI"], GOOD
        )

    def test_same_batch_reuses_completed_identical_paper_on_later_date(self):
        tomorrow = date(2026, 10, 21)
        (self.source / "data" / f"{tomorrow}.jsonl").write_bytes(self.raw.read_bytes())
        (
            self.source / "data" / f"{tomorrow}_AI_enhanced_{self.language}.jsonl"
        ).write_bytes(self.original)
        self.plan = plan_recovery(self.source / "data", DAY, tomorrow, self.language)
        manifest = self.run_stage()
        self.generate.assert_called_once()
        self.assertEqual(manifest["entries"][1]["reused_ids"], ["2610.26164"])

    def test_complete_repair_checkpoint_skips_model(self):
        checkpoint = self.root / "complete-checkpoint"
        write_json(
            checkpoint / f"{DAY}-2610.26164.json",
            {
                "id": "2610.26164",
                "language": self.language,
                "source_sha256": digest(self.enhanced),
                "AI": GOOD,
            },
        )
        manifest = self.run_stage(resume=checkpoint)
        self.generate.assert_not_called()
        self.assertEqual(
            manifest["entries"][0]["checkpoint_reused_ids"], ["2610.26164"]
        )

    def test_second_backfill_interruption_keeps_all_inherited_fields(self):
        self.enhanced.write_text(
            "".join(json.dumps({**r, "AI": GOOD}) + "\n" for r in self.rows)
        )
        incoming = self.root / "three.jsonl"
        rows = [{k: v for k, v in row(i).items() if k != "AI"} for i in (999, 998, 997)]
        incoming.write_text("".join(json.dumps(r) + "\n" for r in rows))
        previous = self.root / "old-checkpoint.json"
        write_json(
            previous,
            {
                "source_sha256": digest(incoming),
                "language": self.language,
                "completed": [{**r, "AI": GOOD} for r in rows[:2]],
                "partial": {**rows[2], "AI": {"tldr": "Keep partial"}},
            },
        )

        def interrupted(items, language, progress):
            self.assertTrue(valid_ai(items[0]["AI"]))
            progress([items[0]], None)
            raise KeyboardInterrupt("second cancellation")

        with self.assertRaises(KeyboardInterrupt):
            stage(
                self.source,
                incoming,
                self.output,
                str(DAY),
                interrupted,
                resume=previous,
            )
        restored = resume_rows(
            rows, self.output / "checkpoint.json", digest(incoming), self.language
        )
        self.assertTrue(all(valid_ai(r["AI"]) for r in restored[:2]))
        self.assertEqual(restored[2]["AI"], {"tldr": "Keep partial"})

    def test_second_repair_interruption_keeps_unvisited_checkpoints(self):
        rows = [{**row(i), "AI": {}} for i in (10, 11, 12)]
        self.enhanced.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.raw.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.plan = plan_recovery(self.source / "data", DAY, DAY, self.language)
        previous = self.root / "old-checkpoints"
        for index, item in enumerate(rows):
            write_json(
                previous / f"{DAY}-{item['id']}.json",
                {
                    "id": item["id"],
                    "language": self.language,
                    "source_sha256": digest(self.enhanced),
                    "AI": GOOD if index < 2 else {"tldr": "Keep partial"},
                },
            )

        def interrupted_write(path, value):
            write_json(path, value)
            if path.name == f"{DAY}-{rows[0]['id']}.json":
                raise KeyboardInterrupt("second cancellation")

        with (
            patch("ai.recover.write_json", side_effect=interrupted_write),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.run_stage(resume=previous)
        self.generate.assert_not_called()
        saved = load_checkpoints(self.output / "checkpoints", self.plan)
        self.assertEqual(len(saved), 3)
        self.assertTrue(valid_ai(saved[f"{DAY}-{rows[1]['id']}.json"]["AI"]))
        resumed = self.output / "checkpoints"
        self.output = self.root / "third-attempt"
        self.run_stage(resume=resumed)
        self.generate.assert_called_once()
        self.assertEqual(self.generate.call_args.args[0]["id"], rows[2]["id"])
