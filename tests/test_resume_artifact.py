from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai.config import settings
from ai.quality import FIELDS
from ai.recover import plan_recovery, stage_recovery
from ai.storage import digest, write_json, write_jsonl
from scripts.resume_artifact import INVENTORY, checked_file, prepare, selector

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
