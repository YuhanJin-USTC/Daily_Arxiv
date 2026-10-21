import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daily_arxiv"))
from daily_arxiv.merge_published import merge_published


class PublishedMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.published = Path(self.temp.name) / "published.jsonl"
        self.generated = Path(self.temp.name) / "generated.jsonl"
        self.original = b'{"id": "2610.26164", "AI": {"tldr": "retain"}}\r\n'
        self.added = b'{"id":"2610.24394","AI":{"tldr":"new"}}\n'
        self.published.write_bytes(self.original)
        self.generated.write_bytes(self.added)

    def test_same_day_append_preserves_published_bytes_and_source(self):
        merge_published(self.published, self.generated)
        self.assertEqual(self.published.read_bytes(), self.original)
        self.assertEqual(self.generated.read_bytes(), self.original + self.added)

    def test_overlap_duplicate_invalid_or_unterminated_data_aborts(self):
        for old, new in [
            (self.original, self.original),
            (self.original, self.added * 2),
            (b"not JSON\n", self.added),
            (self.original.rstrip(), self.added),
        ]:
            with self.subTest(old=old, new=new):
                self.published.write_bytes(old)
                self.generated.write_bytes(new)
                with self.assertRaises(ValueError):
                    merge_published(self.published, self.generated)
                self.assertEqual(self.generated.read_bytes(), new)
                self.assertEqual(self.published.read_bytes(), old)

    def test_first_publication_needs_no_rewrite(self):
        self.published.unlink()
        merge_published(self.published, self.generated)
        self.assertEqual(self.generated.read_bytes(), self.added)
