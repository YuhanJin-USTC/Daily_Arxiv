from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ai.config import settings
from ai.enhance import process_all_items, resume_rows
from ai.errors import EnhancementError
from ai.quality import FIELDS, read_records
from ai.recover import plan_recovery, stage_recovery
from ai.storage import digest, write_bytes, write_json, write_jsonl
from scripts.resume_artifact import INVENTORY, checked_file, prepare, selector
from scripts.stage_daily import stage

GOOD = {field: "Valid " + field for field in FIELDS}
DAY = date(2026, 10, 20)


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "published"
        (self.source / "data").mkdir(parents=True)
        self.artifact = self.root / "previous"
        self.output = self.root / "current"
        self.language = settings()["language"]
        self.identifier = json.loads(INVENTORY.read_text())["papers"][0]["id"]
        self.row = {
            "id": self.identifier,
            "summary": "Abstract",
            "title": "Paper",
            "authors": ["Author"],
            "categories": ["physics.plasm-ph"],
            "abs": "https://arxiv.org/abs/" + self.identifier,
            "pdf": "https://arxiv.org/pdf/" + self.identifier,
        }

    def backfill(self):
        raw = self.artifact / f"{DAY}.jsonl"
        write_jsonl(raw, [self.row])
        write_json(
            self.artifact / "coverage.json",
            {
                "complete": True,
                "expected_ids": [self.identifier],
                "excluded_published_ids": [],
                "inventory_count": 91,
                "remaining_ids": [],
            },
        )
        prepare("append", self.source, self.artifact, ids=(self.identifier,))
        write_json(
            self.artifact / "ready/manifest.json",
            {
                "kind": "append",
                "date": str(DAY),
                "language": self.language,
                "complete": False,
                "files": [],
            },
        )
        write_json(
            self.artifact / "ready/checkpoint.json",
            {
                "source_sha256": digest(raw),
                "language": self.language,
                "completed": [{**self.row, "AI": GOOD}],
                "partial": None,
            },
        )
        return raw

    def metadata(self):
        inventory = json.loads(INVENTORY.read_text())
        identifiers = [paper["id"] for paper in inventory["papers"]]
        rows = [
            {
                **self.row,
                "id": identifier,
                "abs": "https://arxiv.org/abs/" + identifier,
                "pdf": "https://arxiv.org/pdf/" + identifier,
                "announcement_date": str(DAY),
            }
            for identifier in identifiers[:2]
        ]
        raw = self.artifact / f"{DAY}.jsonl"
        write_bytes(
            raw, b"".join(b"  " + json.dumps(row).encode() + b"\r\n" for row in rows)
        )
        write_json(
            self.artifact / "coverage.json",
            {
                "complete": True,
                "errors": [],
                "expected_ids": identifiers[:2],
                "excluded_published_ids": [],
                "inventory_count": len(identifiers),
                "inventory_date": str(DAY),
                "requested_ids": identifiers[:2],
                "remaining_ids": identifiers[2:],
            },
        )
        prepare("append", self.source, self.artifact, ids=tuple(identifiers[:2]))
        return raw, rows

    def snapshot(self, ids):
        prepare(
            "append",
            self.source,
            self.output,
            ids=tuple(ids),
            snapshot=self.artifact,
            metadata_run_id="123",
            metadata_name="arxiv-backfill-123-1",
        )

    def test_selector_requires_matching_pair_type_and_exact_numeric_run(self):
        selector("repair", "", "")
        selector("repair", "123", "arxiv-recovery-123-1")
        selector("append", "123", "arxiv-backfill-123-2")
        for run, name in [
            ("123", ""),
            ("", "arxiv-recovery-123-1"),
            ("1;echo", "arxiv-recovery-1-1"),
            ("123", "arxiv-backfill-123-1"),
            ("123", "../arxiv-recovery-123-1"),
            ("123", "arxiv-recovery-124-1"),
        ]:
            with self.subTest(run=run, name=name), self.assertRaises(ValueError):
                selector("repair", run, name)

    def test_metadata_selector_rejects_resume_and_incomplete_pairs(self):
        selector("append", "", "", "123", "arxiv-backfill-123-1")
        for kind, run, name, metadata_run, metadata_name in [
            ("append", "123", "arxiv-backfill-123-1", "456", "arxiv-backfill-456-1"),
            ("repair", "", "", "123", "arxiv-backfill-123-1"),
            ("append", "", "", "123", ""),
            ("append", "", "", "", "arxiv-backfill-123-1"),
        ]:
            with self.assertRaises(ValueError):
                selector(kind, run, name, metadata_run, metadata_name)

    def test_metadata_rebinds_current_source_without_rewriting_original_rows(self):
        raw, rows = self.metadata()
        before = {path.name: path.read_bytes() for path in self.artifact.iterdir()}
        published = self.source / "data" / f"{DAY}_AI_enhanced_{self.language}.jsonl"
        write_jsonl(published, [{**rows[0], "AI": GOOD}])
        write_jsonl(self.source / "data" / raw.name, rows[:1])
        published_bytes = published.read_bytes()
        self.snapshot(row["id"] for row in rows)
        selected = self.output / raw.name
        self.assertEqual(
            selected.read_bytes(), raw.read_bytes().splitlines(keepends=True)[1]
        )
        evidence = json.loads((self.output / "request.json").read_text())
        self.assertEqual(evidence["request"]["selected_ids"], [rows[1]["id"]])
        self.assertEqual(
            evidence["request"]["sources"]["data/" + published.name], digest(published)
        )
        self.assertEqual(evidence["metadata_source"]["raw_sha256"], digest(raw))
        self.assertEqual(
            evidence["metadata_source"]["request_sha256"],
            digest(self.artifact / "request.json"),
        )
        self.assertEqual(evidence["metadata_source"]["run_id"], "123")
        self.assertEqual(
            before, {path.name: path.read_bytes() for path in self.artifact.iterdir()}
        )
        self.assertFalse((self.output / "ready").exists())
        calls = []

        def generate(items, language, progress):
            calls.extend(item["id"] for item in items)
            result = [{**item, "AI": GOOD} for item in items]
            progress(result, None)
            return result

        stage(self.source, selected, self.output / "ready", str(DAY), generate)
        self.assertEqual(calls, [rows[1]["id"]])
        self.assertTrue(
            (self.output / "ready/data" / published.name)
            .read_bytes()
            .startswith(published_bytes)
        )
        self.assertEqual(published.read_bytes(), published_bytes)
        resumed = self.root / "resumed"
        prepare(
            "append",
            self.source,
            resumed,
            resume=self.output,
            ids=tuple(row["id"] for row in rows),
        )
        self.assertEqual(
            json.loads((resumed / "request.json").read_text())["metadata_source"],
            evidence["metadata_source"],
        )

    def test_metadata_rejects_changed_identity_hashes_and_missing_ids(self):
        raw, rows = self.metadata()
        ids = [row["id"] for row in rows]
        request_path = self.artifact / "request.json"
        original = json.loads(request_path.read_text())
        for key, value in (
            ("repository", "other/repository"),
            ("language", "Other"),
            ("date", "2026-10-19"),
            ("inventory_sha256", "changed"),
            ("profile", {}),
            ("prompt_sha256", {}),
        ):
            changed = json.loads(json.dumps(original))
            changed["request"][key] = value
            write_json(request_path, changed)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.snapshot(ids)
        write_json(request_path, original)
        original_raw = raw.read_bytes()
        raw.write_bytes(original_raw + b"\n")
        with self.assertRaisesRegex(ValueError, "hashes"):
            self.snapshot(ids)
        raw.write_bytes(original_raw)
        missing = json.loads(INVENTORY.read_text())["papers"][2]["id"]
        with self.assertRaisesRegex(ValueError, "every selected"):
            self.snapshot([*ids, missing])
        audit_path = self.artifact / "coverage.json"
        audit = json.loads(audit_path.read_text())
        audit["remaining_ids"] = []
        write_json(audit_path, audit)
        original["coverage_sha256"] = digest(audit_path)
        write_json(request_path, original)
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.snapshot(ids)
        self.assertFalse(self.output.exists())

    def test_metadata_partial_checkpoint_resumes_without_metadata_inputs(self):
        raw, rows = self.metadata()
        ids = tuple(row["id"] for row in rows)
        self.snapshot(ids)

        def interrupted(items, language, progress):
            completed = [{**items[0], "AI": GOOD}]
            partial = {**items[1], "AI": {"tldr": "Keep accepted TLDR"}}
            progress(completed, partial)
            error = EnhancementError("Synthetic interruption", partial)
            error.completed = completed
            raise error

        with self.assertRaises(EnhancementError):
            stage(
                self.source,
                self.output / raw.name,
                self.output / "ready",
                str(DAY),
                interrupted,
            )
        self.assertFalse(
            json.loads((self.output / "ready/manifest.json").read_text())["complete"]
        )
        resumed = self.root / "resumed"
        prepare("append", self.source, resumed, resume=self.output, ids=ids)
        previous = json.loads((self.output / "request.json").read_text())
        current = json.loads((resumed / "request.json").read_text())
        self.assertEqual(current, previous)
        restored = resume_rows(
            read_records(resumed / raw.name),
            self.output / "ready/checkpoint.json",
            digest(resumed / raw.name),
            self.language,
        )
        chain = Mock()
        chain.invoke.return_value = GOOD
        with (
            patch("ai.enhance.is_sensitive", return_value=False),
            patch("ai.enhance.check_github_code", return_value={}),
        ):
            completed = process_all_items(restored, self.language, chain)
        chain.invoke.assert_called_once()
        self.assertEqual(completed[0]["AI"], GOOD)
        self.assertEqual(completed[1]["AI"]["tldr"], "Keep accepted TLDR")

    def test_metadata_rejects_generated_artifacts_and_ai_in_raw(self):
        self.backfill()
        with self.assertRaisesRegex(ValueError, "audit-only"):
            self.snapshot([self.identifier])
        raw, rows = self.metadata()
        alternate = self.root / "audit-only"
        alternate.mkdir()
        for name in (raw.name, "coverage.json", "request.json"):
            write_bytes(alternate / name, (self.artifact / name).read_bytes())
        self.artifact = alternate
        raw = alternate / raw.name
        write_jsonl(raw, [{**rows[0], "AI": GOOD}, rows[1]])
        evidence = json.loads((alternate / "request.json").read_text())
        evidence["raw_sha256"] = digest(raw)
        write_json(alternate / "request.json", evidence)
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.snapshot(row["id"] for row in rows)

    def test_backfill_resume_copies_exact_raw_without_refetch(self):
        raw = self.backfill()
        original = raw.read_bytes()
        prepare(
            "append", self.source, self.output, self.artifact, ids=(self.identifier,)
        )
        self.assertEqual((self.output / raw.name).read_bytes(), original)
        self.assertEqual(raw.read_bytes(), original)
        self.assertEqual(
            json.loads((self.output / "request.json").read_text()),
            json.loads((self.artifact / "request.json").read_text()),
        )

    def test_resume_rejects_wrong_repository_language_profile_scope_and_source(self):
        self.backfill()
        request_path = self.artifact / "request.json"
        original = json.loads(request_path.read_text())
        for key, value in [
            ("repository", "other/repo"),
            ("language", "Other"),
            ("ids", []),
            ("profile", {}),
        ]:
            altered = json.loads(json.dumps(original))
            altered["request"][key] = value
            write_json(request_path, altered)
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepare(
                    "append",
                    self.source,
                    self.output,
                    self.artifact,
                    ids=(self.identifier,),
                )
        write_json(request_path, original)
        write_jsonl(
            self.source / "data" / f"{DAY}_AI_enhanced_{self.language}.jsonl",
            [{**self.row, "AI": GOOD}],
        )
        with self.assertRaises(ValueError):
            prepare(
                "append",
                self.source,
                self.output,
                self.artifact,
                ids=(self.identifier,),
            )
        self.assertFalse(self.output.exists())

    def test_resume_rejects_changed_raw_or_checkpoint_abstract(self):
        raw = self.backfill()
        original = raw.read_bytes()
        raw.write_bytes(original + b"\n")
        with self.assertRaises(ValueError):
            prepare(
                "append",
                self.source,
                self.output,
                self.artifact,
                ids=(self.identifier,),
            )
        raw.write_bytes(original)
        checkpoint = self.artifact / "ready/checkpoint.json"
        saved = json.loads(checkpoint.read_text())
        saved["completed"][0]["summary"] = "Different abstract"
        write_json(checkpoint, saved)
        with self.assertRaises(ValueError):
            prepare(
                "append",
                self.source,
                self.output,
                self.artifact,
                ids=(self.identifier,),
            )
        self.assertFalse(self.output.exists())

    def test_artifact_paths_cannot_follow_symlinks_or_escape(self):
        outside = self.root / "outside.json"
        outside.write_text("{}")
        self.artifact.mkdir()
        (self.artifact / "request.json").symlink_to(outside)
        for name in ("request.json", "../outside.json"):
            with self.assertRaises(ValueError):
                checked_file(self.artifact, name)

    def test_repair_resume_validates_each_checkpoint_and_preserves_old_artifact(self):
        raw = self.source / "data" / f"{DAY}.jsonl"
        enhanced = self.source / "data" / f"{DAY}_AI_enhanced_{self.language}.jsonl"
        write_jsonl(raw, [self.row])
        write_jsonl(enhanced, [{**self.row, "AI": {}}])
        entries = plan_recovery(self.source / "data", DAY, DAY, self.language)
        prepare("repair", self.source, self.artifact, start=DAY, end=DAY)
        stage_recovery(
            self.source / "data",
            self.artifact / "ready",
            entries,
            lambda row, lang: {**row, "AI": GOOD},
        )
        prepare("repair", self.source, self.output, self.artifact, start=DAY, end=DAY)
        checkpoint = (
            self.artifact / "ready/checkpoints" / f"{DAY}-{self.identifier}.json"
        )
        saved = json.loads(checkpoint.read_text())
        saved["source_sha256"] = "wrong"
        write_json(checkpoint, saved)
        with self.assertRaises(ValueError):
            prepare(
                "repair",
                self.source,
                self.root / "bad",
                self.artifact,
                start=DAY,
                end=DAY,
            )

    def test_other_model_profile_cannot_resume(self):
        self.backfill()
        config = settings()
        config["deepseek"] = {**config["deepseek"], "model": "different"}
        with (
            patch("scripts.resume_artifact.settings", return_value=config),
            self.assertRaises(ValueError),
        ):
            prepare(
                "append",
                self.source,
                self.output,
                self.artifact,
                ids=(self.identifier,),
            )
