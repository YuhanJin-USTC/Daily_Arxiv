import importlib.util
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daily_arxiv"))
spec = importlib.util.spec_from_file_location(
    "crawl_runner", ROOT / "daily_arxiv/crawl.py"
)
crawl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawl)
from ai.config import settings
from scripts.build_site import build


class PageReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        self.references.extend(
            value for key, value in attrs if key in ("src", "href") and value
        )


class InventoryTests(unittest.TestCase):
    def test_subset_uses_inventory_members_and_skips_already_published(self):
        inventory = ROOT / "docs/audits/arxiv-2026-10-20.json"
        items = json.loads(inventory.read_text())["papers"]
        with tempfile.TemporaryDirectory() as temp:
            history = Path(temp) / "2026-10-20_AI_enhanced_English.jsonl"
            history.write_text(json.dumps({"id": items[0]["id"]}) + "\n")
            selected = items[1]["id"]
            paper = SimpleNamespace(
                entry_id="https://arxiv.org/abs/" + selected,
                title="Paper",
                summary="Abstract",
                authors=[],
                categories=["physics.plasm-ph"],
                comment=None,
            )
            client = Mock(results=Mock(return_value=iter([paper])))
            with patch("arxiv.Client", return_value=client):
                rows, audit = crawl.archived_inventory(
                    inventory, Path(temp), (items[0]["id"], selected)
                )
            self.assertEqual([r["id"] for r in rows], [selected])
            self.assertEqual(client.results.call_args.args[0].id_list, [selected])
            self.assertEqual(len(audit["remaining_ids"]), 89)
            for ids in [("9999.99999",), (selected, selected)]:
                with patch("arxiv.Client") as factory, self.assertRaises(ValueError):
                    crawl.archived_inventory(inventory, Path(temp), ids)
                factory.assert_not_called()

    def test_archived_inventory_fetches_only_unpublished_ids(self):
        inventory = ROOT / "docs/audits/arxiv-2026-10-20.json"
        items = json.loads(inventory.read_text())["papers"]
        self.assertEqual(len(items), 91)
        with tempfile.TemporaryDirectory() as temp:
            history = Path(temp) / "2026-10-20_AI_enhanced_English.jsonl"
            history.write_text(
                "".join(json.dumps({"id": r["id"]}) + "\n" for r in items[:59])
            )
            selected = {r["id"] for r in items[59:]}
            papers = [
                SimpleNamespace(
                    entry_id="http://arxiv.org/abs/" + i + "v2",
                    title="Paper",
                    summary="Abstract",
                    authors=[SimpleNamespace(name="A")],
                    categories=["physics.plasm-ph"],
                    comment=None,
                )
                for i in sorted(selected)
            ]
            client = Mock(results=Mock(return_value=iter(papers)))
            with patch("arxiv.Client", return_value=client):
                rows, audit = crawl.archived_inventory(inventory, Path(temp))
            self.assertEqual({r["id"] for r in rows}, selected)
            self.assertEqual(set(client.results.call_args.args[0].id_list), selected)
            self.assertEqual(len(audit["excluded_published_ids"]), 59)
            history.write_text(
                "".join(json.dumps({"id": r["id"]}) + "\n" for r in items)
            )
            with patch("arxiv.Client") as factory:
                self.assertEqual(crawl.archived_inventory(inventory, Path(temp))[0], [])
            factory.assert_not_called()

    def test_incomplete_crawl_never_replaces_old_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "raw.jsonl"
            output.write_bytes(b"previous output")
            args = [
                "crawl",
                "--output",
                str(output),
                "--audit",
                str(root / "audit.json"),
                "--history-dir",
                temp,
            ]
            audit = {
                "complete": True,
                "expected_ids": ["2610.26164"],
                "excluded_published_ids": [],
            }
            with (
                patch.object(sys, "argv", args),
                patch.object(crawl, "recent", return_value=([], audit)),
            ):
                self.assertEqual(crawl.main(), 1)
            self.assertEqual(output.read_bytes(), b"previous output")


class SiteTests(unittest.TestCase):
    def test_each_language_builds_correct_public_config_without_source_mutation(self):
        source = (ROOT / "js/data-config.js").read_bytes()
        for language in ("English", "Chinese"):
            config = {**settings(), "language": language}
            with (
                tempfile.TemporaryDirectory() as temp,
                patch("scripts.build_site.settings", return_value=config),
            ):
                dest = Path(temp) / "site"
                with patch.dict(
                    "os.environ", {"ACCESS_PASSWORD": "synthetic-private-password"}
                ):
                    build(dest, "Owner/example-repository")
                text = (dest / "js/data-config.js").read_text()
                self.assertIn('"' + language + '"', text)
                self.assertIn('"example-repository"', text)
                self.assertNotIn("__OWNER__", text)
                self.assertFalse((dest / "ai").exists())
                self.assertFalse((dest / "tests").exists())
                self.assertNotIn(
                    "synthetic-private-password",
                    (dest / "js/auth-config.js").read_text(),
                )
                mail = config["notifications"]
                private_values = [item["email"] for item in mail["recipients"]]
                private_values.extend(
                    mail["smtp"][key]
                    for key in ("host", "sender", "username_env", "password_env")
                )
                for file in dest.rglob("*"):
                    if file.suffix in (".html", ".css", ".js"):
                        content = file.read_text()
                        for value in private_values:
                            self.assertNotIn(value, content, file.name)
                self.assertEqual((ROOT / "js/data-config.js").read_bytes(), source)

    def test_all_local_page_and_stylesheet_references_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            build(output, "Owner/example-repository")
            for file in output.rglob("*"):
                if file.suffix == ".html":
                    parser = PageReferences()
                    parser.feed(file.read_text())
                    references = parser.references
                elif file.suffix == ".css":
                    references = re.findall(
                        r"url\(\s*['\"]?([^)'\"\s]+)", file.read_text()
                    )
                else:
                    continue
                for reference in references:
                    parsed = urlsplit(reference)
                    if parsed.scheme or parsed.netloc or not parsed.path:
                        continue
                    target = (file.parent / unquote(parsed.path)).resolve()
                    with self.subTest(file=file.name, reference=reference):
                        self.assertTrue(target.is_relative_to(output.resolve()))
                        self.assertTrue(target.is_file())

    def test_unlisted_assets_and_pages_are_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            for name in ("assets", "css", "js"):
                shutil.copytree(ROOT / name, source / name)
            for file in ROOT.glob("*.html"):
                shutil.copyfile(file, source / file.name)
            extras = (
                "assets/review-video.mp4",
                "assets/notification-state.json",
                "images/old-preview.png",
                "js/private-config.json",
                "css/preview.css",
                "preview.html",
            )
            for name in extras:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Synthetic private preview")
            output = Path(directory) / "site"
            with patch("scripts.build_site.ROOT", source):
                build(output, "Owner/example-repository")
            for name in extras:
                self.assertFalse((output / name).exists(), name)
            self.assertTrue((output / "assets/logo2-removebg-preview.png").is_file())
            self.assertTrue((output / ".nojekyll").is_file())
