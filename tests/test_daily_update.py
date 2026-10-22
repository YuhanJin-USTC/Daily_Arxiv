import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ai.config import settings
from ai.errors import EnhancementError
from ai.quality import FIELDS
from ai.storage import digest, write_json, write_jsonl
from scripts.daily_update import (
    INDEX,
    QUEUE,
    language_update,
    raw_update,
    refresh_index,
    send_notifications,
)
from scripts.publish_data import Publisher, allowed_path


class DailyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "published"
        (self.source / "data").mkdir(parents=True)
        self.raw = self.root / "raw.jsonl"
        self.audit = self.root / "audit.json"
        self.row = {
            "id": "2610.12345",
            "title": "Public fixture",
            "summary": "Exact abstract",
            "authors": ["Alexey Arefiev"],
            "categories": ["physics.plasm-ph"],
            "abs": "https://arxiv.org/abs/2610.12345",
            "pdf": "https://arxiv.org/pdf/2610.12345",
        }
        self.config = copy.deepcopy(settings())
        self.config["notifications"]["recipients"] = [
            {"id": "yuhanjin", "email": "recipient@example.org", "enabled": True}
        ]
        self.day = "2026-10-21"

    def discover(self, rows=None, suffix="1"):
        rows = [self.row] if rows is None else rows
        write_jsonl(self.raw, rows)
        write_json(
            self.audit,
            {
                "complete": True,
                "expected_ids": [r["id"] for r in rows],
                "excluded_published_ids": [],
            },
        )
        published = []

        def save(paths):
            published.append(paths)
            queue = json.loads((self.source / QUEUE).read_text())
            self.assertIn(self.row["id"], queue["discoveries"])
            self.assertTrue((self.source / f"data/{self.day}.jsonl").exists())

        raw_update(
            self.source,
            self.raw,
            self.audit,
            self.day,
            self.root / ("raw-" + suffix),
            self.config,
            save,
        )
        self.assertIn(QUEUE, published[0])
        self.assertIn(INDEX, published[0])
        staged = self.root / ("raw-" + suffix)
        manifest = json.loads((staged / "manifest.json").read_text())
        entries = {entry["path"]: entry for entry in manifest["files"]}
        for name in (QUEUE, INDEX):
            self.assertEqual(entries[name]["after"], digest(staged / name))
            self.assertEqual(
                (staged / name).read_bytes(), (self.source / name).read_bytes()
            )

    def test_mail_failure_does_not_block_ai_or_raw_and_empty_day_keeps_queue(self):
        self.discover()
        raw_bytes = (self.source / f"data/{self.day}.jsonl").read_bytes()
        sent = Mock(side_effect=RuntimeError("ambiguous transport"))
        report = send_notifications(
            self.source, self.config, Mock(), sent, {"ALLOW_SMTP_SEND": "1"}, self.day
        )
        self.assertEqual(report["uncertain"], 1)
        self.assertEqual(
            (self.source / f"data/{self.day}.jsonl").read_bytes(), raw_bytes
        )

        def complete(rows, language, progress):
            result = [
                {
                    **row,
                    "AI": {field: language + " fixture " + field for field in FIELDS},
                }
                for row in rows
            ]
            progress(result, None)
            return result

        report = language_update(
            self.source, self.root / "English", "English", generate=complete
        )
        self.assertEqual(report["completed"], 1)
        self.discover([], "2")
        before = json.loads((self.source / QUEUE).read_text())
        refresh_index(self.source, self.config)
        self.assertEqual(json.loads((self.source / QUEUE).read_text()), before)
        self.assertEqual(
            before["deliveries"]["yuhanjin"][self.row["id"]]["status"], "uncertain"
        )

    def test_one_language_failure_other_success_durable_on_no_new_run(self):
        self.discover()
        fail = Mock(side_effect=EnhancementError("synthetic failure", self.row))
        report = language_update(
            self.source, self.root / "failed", "English", generate=fail
        )
        self.assertEqual(len(report["failures"]), 1)
        self.assertTrue((self.source / "data/ai-checkpoints/English.json").exists())
        self.assertTrue((self.source / QUEUE).exists())

    def test_send_without_durable_publisher_refused(self):
        self.discover()
        with self.assertRaisesRegex(ValueError, "durable"):
            send_notifications(self.source, self.config, None)

    def test_publication_rejects_local_origin_before_any_git_mutation(self):
        path = self.source / "data/pipeline-state.json"
        write_json(path, {})
        publisher = Publisher(self.source, "yuhanjin-ustc/daily-arxiv")
        with patch.object(
            publisher, "git", return_value="/home/yuhanjin/daily-arxiv-chinese"
        ) as git:
            with self.assertRaisesRegex(ValueError, "local origin"):
                publisher(["data/pipeline-state.json"])
        self.assertEqual(git.call_count, 1)

    def test_publication_path_allowlist(self):
        for path in (
            QUEUE,
            INDEX,
            "data/2026-10-21_English.md",
            "data/ai-checkpoints/Chinese.json",
        ):
            self.assertTrue(allowed_path(path))
        for path in (
            "pyproject.toml",
            ".env",
            "data/../../README.md",
            "data/2026-10-21.md",
            "assets/credentials.json",
        ):
            self.assertFalse(allowed_path(path))


if __name__ == "__main__":
    unittest.main()
