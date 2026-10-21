"""Fetch only unpublished IDs and atomically save a complete verified crawl."""

import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(1, str(Path(__file__).resolve().parents[1]))
from ai.storage import write_json, write_jsonl
from daily_arxiv.history import load_history_ids, paper_id
from daily_arxiv.validate_crawl import validate


def archived_inventory(path, history_dir, ids=()):
    """Use a reviewed dated inventory even after arXiv's recent window expires."""
    import arxiv

    inventory = json.loads(path.read_text())
    from ai.config import settings
    from datetime import date

    date.fromisoformat(inventory["announcement_date"])
    if set(inventory["categories"]) != set(settings()["categories"]):
        raise ValueError("Inventory categories differ from project configuration")
    all_ids = [paper_id(row["id"]) for row in inventory["papers"]]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Duplicate inventory IDs")
    history = load_history_ids(history_dir)
    selected = set(all_ids) - history
    requested = [paper_id(identifier) for identifier in ids]
    if len(requested) != len(set(requested)) or not set(requested) <= set(all_ids):
        raise ValueError("Requested IDs must be unique members of the inventory")
    missing = set(selected)
    if requested:
        selected &= set(requested)
    rows = []
    if selected:
        client = arxiv.Client(page_size=100, delay_seconds=3, num_retries=3)
        for paper in client.results(arxiv.Search(id_list=sorted(selected))):
            identifier = paper_id(paper.entry_id.replace("http://", "https://"))
            rows.append(
                {
                    "id": identifier,
                    "title": paper.title,
                    "summary": paper.summary,
                    "authors": [author.name for author in paper.authors],
                    "categories": paper.categories,
                    "abs": f"https://arxiv.org/abs/{identifier}",
                    "pdf": f"https://arxiv.org/pdf/{identifier}",
                    "comment": paper.comment,
                    "announcement_date": inventory["announcement_date"],
                }
            )
    audit = {
        "complete": True,
        "errors": [],
        "expected_ids": sorted(selected),
        "excluded_published_ids": sorted(set(all_ids) & history),
        "inventory_date": inventory["announcement_date"],
        "scope": "reviewed archived inventory",
        "inventory_count": len(all_ids),
        "requested_ids": sorted(requested),
        "remaining_ids": sorted(missing - selected),
    }
    return rows, audit


def recent(history_dir, target_date):
    from scrapy import signals
    from scrapy.crawler import CrawlerProcess
    from scrapy.settings import Settings
    from daily_arxiv.spiders.arxiv import ArxivSpider

    rows, errors = [], []
    config = Settings()
    config.setmodule("daily_arxiv.settings")
    config.set("FEEDS", {})
    process = CrawlerProcess(config)
    crawler = process.create_crawler(ArxivSpider)

    def scraped(item, **kwargs):
        rows.append(dict(item))

    def failed(**kwargs):
        errors.append("item_or_spider_error")

    crawler.signals.connect(scraped, signal=signals.item_scraped, weak=False)
    for signal in (signals.item_error, signals.item_dropped, signals.spider_error):
        crawler.signals.connect(failed, signal=signal, weak=False)
    deferred = process.crawl(crawler, history_dir=history_dir, target_date=target_date)
    deferred.addErrback(lambda failure: errors.append("crawl_failed"))
    process.start()
    audit = crawler.spider.audit(crawler.stats.get_value("finish_reason"))
    audit["errors"].extend(errors)
    audit["complete"] = audit["complete"] and not errors
    return rows, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--history-dir", type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--date", help="Announcement date within the recent window")
    group.add_argument(
        "--inventory", type=Path, help="Reviewed archived inventory JSON"
    )
    parser.add_argument("--ids", default="", help="Comma-separated inventory subset")
    args = parser.parse_args()
    try:
        if args.ids and not args.inventory:
            raise ValueError("--ids requires a reviewed inventory")
        rows, audit = (
            archived_inventory(
                args.inventory,
                args.history_dir,
                tuple(filter(None, (value.strip() for value in args.ids.split(",")))),
            )
            if args.inventory
            else recent(str(args.history_dir), args.date)
        )
        write_json(args.audit, audit)
        with tempfile.TemporaryDirectory(prefix="arxiv-crawl-") as directory:
            staging = Path(directory) / "records.jsonl"
            write_jsonl(staging, rows)
            validate(staging, args.audit)
        write_jsonl(args.output, rows)
        print(f"Verified unpublished papers: {len(rows)}")
        return 0
    except Exception as error:
        print(
            f"Crawl failed ({type(error).__name__}); previous output preserved.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
