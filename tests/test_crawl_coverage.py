import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import scrapy
from scrapy.http import HtmlResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daily_arxiv"))
from daily_arxiv.spiders.arxiv import ArxivSpider
from daily_arxiv.validate_crawl import validate
from daily_arxiv.check_stats import deduplicate
from ai.config import settings


def response(rows, total=None):
    total = len(rows) if total is None else total
    body = f'<div class="paging">Total of {total} entries</div><h3>Tue, 20 Oct 2026 (showing entries)</h3><dl>'
    for identifier, categories in rows:
        subjects = "; ".join(f"Field ({category})" for category in categories)
        body += f'<dt><a title="Abstract" href="/abs/{identifier}">{identifier}</a></dt><dd><div class="list-subjects">{subjects}</div></dd>'
    body += "</dl>"
    return HtmlResponse(
        url="https://arxiv.org/list/physics.plasm-ph/recent",
        body=body.encode(),
        encoding="utf-8",
    )


class CrawlTests(unittest.TestCase):
    def spider(self, **kwargs):
        with patch.dict(os.environ, {"CATEGORIES": "physics.plasm-ph"}):
            return ArxivSpider(**kwargs)

    def test_sync_and_async_start_emit_the_configured_listing_requests(self):
        async def collect(spider):
            return [request async for request in spider.start()]

        for supplied, expected in (
            ("", settings()["categories"]),
            (
                " physics.optics, physics.plasm-ph, physics.optics ",
                ["physics.optics", "physics.plasm-ph"],
            ),
        ):
            with (
                self.subTest(categories=supplied),
                patch.dict(os.environ, {"CATEGORIES": supplied}),
            ):
                spider = ArxivSpider()
                starts = (list(spider.start_requests()), asyncio.run(collect(spider)))
                for requests in starts:
                    self.assertEqual(
                        [request.url for request in requests],
                        [
                            f"https://arxiv.org/list/{category}/recent?skip=0&show=2000"
                            for category in sorted(expected)
                        ],
                    )
                    self.assertEqual(
                        len({request.url for request in requests}), len(expected)
                    )
                    for request, category in zip(requests, sorted(expected)):
                        self.assertEqual(
                            request.cb_kwargs, {"category": category, "skip": 0}
                        )
                        self.assertEqual(request.callback, spider.parse)
                        self.assertEqual(request.errback, spider.failed)

    def test_cross_list_with_external_primary_category_is_kept(self):
        spider = self.spider()
        items = list(
            spider.parse(
                response([("2610.24394", ["astro-ph.CO", "physics.plasm-ph"])]),
                "physics.plasm-ph",
            )
        )
        self.assertEqual(items[0]["id"], "2610.24394")
        self.assertEqual(items[0]["announcement_date"], "2026-10-20")
        self.assertTrue(spider.audit("finished")["complete"])

    def test_pagination_uses_actual_returned_page_length(self):
        spider = self.spider()
        page1 = response([("2610.24394", ["physics.plasm-ph"])], total=2)
        output = list(spider.parse(page1, "physics.plasm-ph"))
        self.assertIsInstance(output[-1], scrapy.Request)
        self.assertIn("skip=1", output[-1].url)
        self.assertFalse(spider.audit("finished")["complete"])
        page2 = response([("2610.24296", ["physics.plasm-ph"])], total=2)
        list(spider.parse(page2, "physics.plasm-ph", skip=1))
        self.assertTrue(spider.audit("finished")["complete"])

    def test_overlapping_categories_yield_one_record(self):
        spider = self.spider()
        spider.target_categories.add("physics.atom-ph")
        page = response(
            [
                (
                    "2610.26280",
                    ["physics.atm-clus", "physics.atom-ph", "physics.plasm-ph"],
                )
            ]
        )
        first = list(spider.parse(page, "physics.atom-ph"))
        second = list(spider.parse(page, "physics.plasm-ph"))
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertTrue(spider.audit("finished")["complete"])

    def test_history_prevents_refetch_of_published_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-20_AI_enhanced_Chinese.jsonl"
            path.write_text(json.dumps({"id": "2610.24394"}) + "\n")
            before = path.read_bytes()
            spider = self.spider(history_dir=directory)
            page = response(
                [
                    ("2610.24394v2", ["physics.plasm-ph"]),
                    ("2610.24296", ["physics.plasm-ph"]),
                ]
            )
            items = list(spider.parse(page, "physics.plasm-ph"))
            self.assertEqual([row["id"] for row in items], ["2610.24296"])
            self.assertEqual(
                spider.audit("finished")["excluded_published_ids"], ["2610.24394"]
            )
            self.assertEqual(path.read_bytes(), before)

    def test_legacy_id_cross_list_is_not_discarded_as_old_submission(self):
        spider = self.spider()
        items = list(
            spider.parse(
                response([("physics/0601001v2", ["physics.plasm-ph"])]),
                "physics.plasm-ph",
            )
        )
        self.assertEqual(items[0]["id"], "physics/0601001")

    def test_absent_requested_date_and_failed_request_make_audit_fail(self):
        spider = self.spider(target_date="2026-10-19")
        list(
            spider.parse(
                response([("2610.24394", ["physics.plasm-ph"])]), "physics.plasm-ph"
            )
        )
        self.assertIn(
            "requested_date_not_in_recent_window", spider.audit("finished")["errors"]
        )
        spider.failed(None)
        self.assertFalse(spider.audit("finished")["complete"])

    def test_empty_page_or_missing_header_does_not_silently_pass(self):
        with self.assertRaises(ValueError):
            list(self.spider().parse(response([], total=1), "physics.plasm-ph"))
        broken = HtmlResponse(
            url="https://arxiv.org", body=b"<html>error</html>", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            list(self.spider().parse(broken, "physics.plasm-ph"))

    def test_missing_pipeline_record_is_detected(self):
        spider = self.spider()
        list(
            spider.parse(
                response([("2610.24394", ["physics.plasm-ph"])]), "physics.plasm-ph"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            audit, data = Path(directory) / "audit.json", Path(directory) / "data.jsonl"
            audit.write_text(json.dumps(spider.audit("finished")))
            data.write_text("")
            with self.assertRaisesRegex(ValueError, "missing="):
                validate(data, audit)

    def test_history_and_within_run_duplicates_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "history"
            history.mkdir()
            (history / "2026-10-19_AI_enhanced_Chinese.jsonl").write_text(
                '{"id":"2610.24394"}\n'
            )
            data = root / "today.jsonl"
            data.write_text(
                "".join(
                    json.dumps({"id": i}) + "\n"
                    for i in ["2610.24394v2", "2610.24296", "2610.24296v1"]
                )
            )
            self.assertEqual(deduplicate(data, history), 1)
            self.assertEqual(json.loads(data.read_text())["id"], "2610.24296")

    def test_conflicting_duplicates_fail_without_touching_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            original = b'{"id":"2610.26164","summary":"one"}\n{"id":"2610.26164","summary":"different"}\n'
            path.write_bytes(original)
            with self.assertRaises(ValueError):
                deduplicate(path)
            self.assertEqual(path.read_bytes(), original)

    def test_corrupt_history_fails_without_touching_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad_AI_enhanced_Chinese.jsonl").write_text("bad-json")
            data = root / "today.jsonl"
            data.write_text('{"id":"2610.24394"}\n')
            before = data.read_bytes()
            with self.assertRaises(ValueError):
                deduplicate(data, root)
            self.assertEqual(data.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
