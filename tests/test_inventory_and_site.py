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

import arxiv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daily_arxiv"))
spec = importlib.util.spec_from_file_location(
    "crawl_runner", ROOT / "daily_arxiv/crawl.py"
)
crawl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawl)
from ai.config import settings
from scripts.build_site import build
from scripts.daily_update import raw_update


class PageReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        self.references.extend(
            value for key, value in attrs if key in ("src", "href") and value
        )


class InventoryTests(unittest.TestCase):
    def test_daily_fetches_contiguous_batches_after_verified_listing_in_listing_order(
        self,
    ):
        ids = ["physics/0601001", *[f"2610.{n:05d}" for n in range(50, 0, -1)]]
        listings = [
            {"id": identifier, "announcement_date": f"2026-10-{19 + n % 2}"}
            for n, identifier in enumerate(ids)
        ]
        audit = {"complete": True, "errors": [], "expected_ids": sorted(ids)}

        def reverse_results(search):
            return [
                arxiv.Result(
                    entry_id=f"https://arxiv.org/abs/{identifier}v3",
                    title=identifier,
                    summary="Summary",
                    authors=[arxiv.Result.Author("A")],
                    categories=["physics.optics"],
                )
                for identifier in reversed(search.id_list)
            ]

        client = Mock()
        client.results.side_effect = reverse_results
        with (
            patch.object(crawl, "recent_listings", return_value=(listings, audit)),
            patch.object(crawl, "MetadataClient", return_value=client),
        ):
            rows, audit = crawl.recent(None, None)
        batches = [request.args[0].id_list for request in client.results.call_args_list]
        self.assertEqual(batches, [ids[:50], ids[50:]])
        self.assertEqual(
            [batch[0]["requested_ids"] for batch in audit["metadata_batches"]], batches
        )
        self.assertEqual(audit["metadata_ids"], audit["expected_ids"])
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["missing_metadata_ids"], [])
        self.assertEqual([r["id"] for r in rows], ids)
        self.assertEqual([r["title"] for r in rows], ids)
        self.assertEqual(
            [r["announcement_date"] for r in rows],
            [r["announcement_date"] for r in listings],
        )

    def test_incomplete_listing_or_missing_listing_item_never_requests_metadata(self):
        for complete in (False, True):
            audit = {"complete": complete, "errors": [], "expected_ids": ["2610.26164"]}
            with (
                self.subTest(complete=complete),
                patch.object(crawl, "recent_listings", return_value=([], audit)),
                patch.object(crawl, "MetadataClient") as factory,
            ):
                rows, audit = crawl.recent(None, None)
            self.assertFalse(audit["complete"])
            self.assertEqual(rows, [])
            self.assertEqual(audit["missing_metadata_ids"], ["2610.26164"])
            factory.assert_not_called()

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
                for i in sorted(selected, reverse=True)
            ]
            client = Mock(results=Mock(return_value=iter(papers)))
            with patch("arxiv.Client", return_value=client):
                rows, audit = crawl.archived_inventory(inventory, Path(temp))
            self.assertEqual([r["id"] for r in rows], sorted(selected, reverse=True))
            self.assertEqual(
                list(rows[0]),
                [
                    "id",
                    "title",
                    "summary",
                    "authors",
                    "categories",
                    "abs",
                    "pdf",
                    "comment",
                    "announcement_date",
                ],
            )
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
                "errors": [],
                "expected_ids": ["2610.26164"],
                "excluded_published_ids": [],
            }
            with (
                patch.object(sys, "argv", args),
                patch.object(crawl, "recent", return_value=([], audit)),
            ):
                self.assertEqual(crawl.main(), 1)
            self.assertEqual(output.read_bytes(), b"previous output")

    def test_unresolved_daily_metadata_preserves_previous_raw_and_blocks_publication(
        self,
    ):
        ids = ["2610.24394", "2610.26164"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output, coverage = root / "raw.jsonl", root / "coverage.json"
            output.write_bytes(b"previous raw bytes")
            client = Mock()
            client.results.side_effect = [
                [arxiv.Result(entry_id=ids[1], title="A", summary="Abstract")],
                [],
                [],
                arxiv.HTTPError("", 0, 503),
            ]
            listings = [{"id": i, "announcement_date": "2026-10-20"} for i in ids]
            audit = {
                "complete": True,
                "errors": [],
                "expected_ids": ids,
                "excluded_published_ids": [],
            }
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "crawl",
                        "--output",
                        str(output),
                        "--audit",
                        str(coverage),
                        "--history-dir",
                        temp,
                    ],
                ),
                patch.object(crawl, "recent_listings", return_value=(listings, audit)),
                patch.object(crawl, "MetadataClient", return_value=client),
                patch("daily_arxiv.pipelines.time.sleep"),
            ):
                self.assertEqual(crawl.main(), 1)
            self.assertEqual(output.read_bytes(), b"previous raw bytes")
            saved = json.loads(coverage.read_text())
            self.assertFalse(saved["complete"])
            self.assertEqual(saved["errors"], ["metadata_retries_exhausted:http_503"])
            self.assertEqual(saved["metadata_ids"], [ids[1]])
            self.assertEqual(saved["missing_metadata_ids"], [ids[0]])
            attempts = saved["metadata_batches"][0]
            self.assertEqual(
                [attempt["requested_ids"] for attempt in attempts],
                [ids, [ids[0]], [ids[0]], [ids[0]]],
            )
            publish = Mock()
            (root / "data").mkdir()
            with self.assertRaisesRegex(ValueError, "metadata_retries_exhausted"):
                raw_update(
                    root, output, coverage, "2026-10-20", root / "staging", {}, publish
                )
            publish.assert_not_called()
            self.assertFalse((root / "staging").exists())


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
