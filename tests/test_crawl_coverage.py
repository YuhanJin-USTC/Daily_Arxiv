import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch
from urllib.parse import parse_qs, urlsplit

import arxiv
from requests import exceptions
import scrapy
from scrapy.http import HtmlResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daily_arxiv"))
from daily_arxiv.spiders.arxiv import ArxivSpider
from daily_arxiv.validate_crawl import validate
from daily_arxiv.check_stats import deduplicate
from daily_arxiv.pipelines import (
    DailyArxivPipeline,
    MetadataClient,
    MetadataError,
    fetch_batch,
)
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


def api_paper(identifier, title="Paper"):
    return arxiv.Result(
        entry_id=f"http://arxiv.org/abs/{identifier}v2",
        title=title,
        summary="Abstract",
        authors=[arxiv.Result.Author("A")],
        categories=["physics.plasm-ph"],
    )


class MetadataTests(unittest.TestCase):
    def test_partial_and_interrupted_responses_retry_only_missing_ids(self):
        ids = ["2610.24394", "physics/0601001", "2610.24296"]

        def interrupted():
            yield api_paper(ids[1])
            raise exceptions.ChunkedEncodingError()

        client = Mock()
        client.results.side_effect = [
            interrupted(),
            [api_paper(ids[2])],
            arxiv.HTTPError("", 0, 429),
            [api_paper(ids[0])],
        ]
        accepted, attempts = {}, []
        with patch("daily_arxiv.pipelines.time.sleep") as sleep:
            fetch_batch(client, ids, accepted, attempts)
        self.assertEqual(sleep.call_args_list, [call(30), call(120), call(300)])
        self.assertEqual(
            [args.args[0].id_list for args in client.results.call_args_list],
            [ids, [ids[0], ids[2]], [ids[0]], [ids[0]]],
        )
        self.assertEqual(
            [attempt.get("error") for attempt in attempts],
            ["ChunkedEncodingError", "partial_response", "http_429", None],
        )
        self.assertEqual(set(accepted), set(ids))
        self.assertEqual(accepted[ids[1]]["pdf"], f"https://arxiv.org/pdf/{ids[1]}")

    def test_transient_errors_retry_permanent_http_and_bad_identities_stop(self):
        identifier = "2610.24394"
        paper = api_paper(identifier)
        for failure in (
            arxiv.HTTPError("", 0, 503),
            exceptions.Timeout(),
            exceptions.ConnectionError(),
        ):
            client = Mock()
            client.results.side_effect = [failure, [paper]]
            with (
                self.subTest(error=failure),
                patch("daily_arxiv.pipelines.time.sleep") as sleep,
            ):
                fetch_batch(client, [identifier], {}, [])
                sleep.assert_called_once_with(30)
        for first, reason in [
            (arxiv.HTTPError("", 0, 404), "http_404"),
            ([api_paper("2610.24296")], "unexpected_metadata_id:2610.24296"),
            (
                [paper, api_paper(identifier, title="Other")],
                "conflicting_metadata:2610.24394",
            ),
        ]:
            client = Mock()
            client.results.side_effect = [first]
            with (
                self.subTest(reason=reason),
                patch("daily_arxiv.pipelines.time.sleep") as sleep,
                self.assertRaisesRegex(MetadataError, reason),
            ):
                fetch_batch(client, [identifier], {}, [])
            sleep.assert_not_called()
            client.results.assert_called_once()

    def test_short_atom_page_requeries_only_missing_ids_using_locked_client(self):
        ids = ["2610.24394", "2610.24296"]

        def feed(identifier, total):
            return Mock(
                status_code=200,
                content=f"""
                <feed xmlns="http://www.w3.org/2005/Atom"
                      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
                      xmlns:arxiv="http://arxiv.org/schemas/atom">
                  <opensearch:totalResults>{total}</opensearch:totalResults>
                  <entry>
                    <id>http://arxiv.org/abs/{identifier}v2</id>
                    <updated>2026-10-19T00:00:00Z</updated>
                    <published>2026-10-19T00:00:00Z</published>
                    <title>Paper</title><summary>Abstract</summary>
                    <author><name>A</name></author><category term="physics.optics"/>
                    <arxiv:primary_category term="physics.optics"/><link href="https://arxiv.org"/>
                  </entry>
                </feed>
            """.encode(),
            )

        with (
            patch(
                "requests.Session.get", side_effect=[feed(ids[1], 2), feed(ids[0], 1)]
            ) as get,
            patch("daily_arxiv.pipelines.time.sleep") as sleep,
        ):
            client = MetadataClient()
            self.assertEqual(
                (client.page_size, client.delay_seconds, client.num_retries), (50, 3, 0)
            )
            received = {}
            fetch_batch(client, ids, received, [])
        calls = [parse_qs(urlsplit(args.args[0]).query) for args in get.call_args_list]
        self.assertEqual(
            [query["id_list"] for query in calls], [[",".join(ids)], [ids[0]]]
        )
        self.assertTrue(all(query["start"] == ["0"] for query in calls))
        self.assertTrue(
            all(args.kwargs["timeout"] == 60 for args in get.call_args_list)
        )
        sleep.assert_any_call(30)
        self.assertEqual(set(received), set(ids))

    def test_native_scrapy_pipeline_preserves_discovery_and_metadata_fields(self):
        identifier = "physics/0601001"
        listing = {
            "id": identifier,
            "categories": ["physics.optics"],
            "announcement_date": "2026-10-19",
        }
        with patch.object(
            MetadataClient, "results", return_value=[api_paper(identifier)]
        ):
            row = DailyArxivPipeline().process_item(listing, None)
        self.assertEqual(row["announcement_date"], listing["announcement_date"])
        self.assertEqual(row["id"], identifier)
        self.assertEqual(row["categories"], ["physics.plasm-ph"])
        self.assertEqual(row["abs"], f"https://arxiv.org/abs/{identifier}")
        self.assertEqual(row["authors"], ["A"])


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
