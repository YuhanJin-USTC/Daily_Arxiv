import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daily_arxiv"))
from ai.config import settings, subscribed_categories
from daily_arxiv.spiders.arxiv import ArxivSpider
from scripts.build_site import build


class CategoryConfigTests(unittest.TestCase):
    def test_blank_override_keeps_configured_order(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(subscribed_categories(), settings()["categories"])
        with patch.dict(os.environ, {"CATEGORIES": "  "}):
            self.assertEqual(subscribed_categories(), settings()["categories"])

    def test_site_and_crawler_share_custom_subscription(self):
        expected = ["physics.optics", "physics.plasm-ph"]
        with (
            patch.dict(
                os.environ,
                {"CATEGORIES": " physics.optics, physics.plasm-ph,physics.optics "},
            ),
            tempfile.TemporaryDirectory() as directory,
        ):
            self.assertEqual(subscribed_categories(), expected)
            self.assertEqual(ArxivSpider().target_categories, set(expected))
            output = Path(directory) / "site"
            with patch.dict(os.environ, {"ACCESS_PASSWORD": "fictional password"}):
                build(output, "Owner/chinese")
            script = (output / "js/data-config.js").read_text()
            categories = json.loads(re.search(r"categories: (\[[^\n]+\]),", script)[1])
            self.assertEqual(categories, expected)
            defaults = re.search(
                r"const DEFAULT_SUBSCRIBED_CATEGORIES = (\[[^\n]+\]);",
                (output / "js/papers.js").read_text(),
            )[1]
            self.assertEqual(json.loads(defaults), expected)

    def test_invalid_override_fails_instead_of_expanding_subscription(self):
        for supplied in (", ,", "physics.optics,invalid/category"):
            with patch.dict(os.environ, {"CATEGORIES": supplied}):
                with self.assertRaises(ValueError):
                    subscribed_categories()


if __name__ == "__main__":
    unittest.main()
