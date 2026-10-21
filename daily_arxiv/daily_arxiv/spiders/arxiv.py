"""Collect new submissions AND cross-lists from all recent announcement pages."""

from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import urlencode

import scrapy

from ai.config import subscribed_categories
from daily_arxiv.history import load_history_ids, paper_id


class ArxivSpider(scrapy.Spider):
    name = "arxiv"
    allowed_domains = ["arxiv.org"]
    custom_settings = {"DOWNLOAD_DELAY": 3, "CONCURRENT_REQUESTS_PER_DOMAIN": 1}

    def __init__(
        self, target_date=None, history_dir=None, audit_path=None, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.target_categories = set(subscribed_categories())
        self.target_date = (
            datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else None
        )
        self.history_ids = load_history_ids(history_dir)
        self.audit_path = Path(audit_path) if audit_path else None
        self.expected_ids = set()
        self.listed_ids = set()
        self.excluded_history_ids = set()
        self.listings = {}
        self.errors = []
        self.announcement_dates = set()

    def start_requests(self):
        for category in sorted(self.target_categories):
            yield self.list_request(category, 0)

    async def start(self):
        for request in self.start_requests():
            yield request

    def list_request(self, category, skip):
        query = urlencode({"skip": skip, "show": 2000})
        return scrapy.Request(
            f"https://arxiv.org/list/{category}/recent?{query}",
            callback=self.parse,
            errback=self.failed,
            cb_kwargs={"category": category, "skip": skip},
        )

    def failed(self, failure):
        self.errors.append("listing_request_failed")
        self.logger.error(
            "An arXiv listing request failed; completeness check will fail"
        )

    def parse(self, response, category, skip=0):
        text = " ".join(response.css("div.paging ::text").getall())
        total_match = re.search(r"Total of ([\d,]+) entries", text)
        if total_match is None:
            raise ValueError(
                "Listing total is missing; refusing silent partial results"
            )
        total = int(total_match.group(1).replace(",", ""))
        state = self.listings.setdefault(
            category, {"total": total, "rows": set(), "pages": set()}
        )
        if state["total"] != total or skip in state["pages"]:
            raise ValueError("Listing changed or a pagination loop was detected")
        state["pages"].add(skip)
        papers = response.css("dl dt")
        if not papers and skip < total:
            raise ValueError("Empty page before the advertised end of listing")
        for paper in papers:
            heading = " ".join(paper.xpath("preceding::h3[1]//text()").getall()).strip()
            match = re.match(r"([A-Za-z]{3}, \d{1,2} [A-Za-z]{3} \d{4})", heading)
            if not match:
                raise ValueError("Could not determine the announcement date")
            announced = datetime.strptime(match.group(1), "%a, %d %b %Y").date()
            self.announcement_dates.add(announced.isoformat())
            link = paper.css("a[title='Abstract']::attr(href)").get()
            if not link or not link.startswith("/abs/"):
                raise ValueError("A listing entry has no abstract id")
            identifier = paper_id(link.removeprefix("/abs/"))
            dd = paper.xpath("following-sibling::dd[1]")
            # Read secondary categories too; a selected category is not always primary.
            subjects = " ".join(dd.css(".list-subjects ::text").getall())
            categories = re.findall(r"\(([A-Za-z][A-Za-z.-]+)\)", subjects)
            if category not in categories:
                raise ValueError("Listing subject metadata does not match its category")
            state["rows"].add((announced.isoformat(), identifier))
            if self.target_date and announced != self.target_date:
                continue
            self.listed_ids.add(identifier)
            if identifier in self.history_ids:
                self.excluded_history_ids.add(identifier)
                continue
            if identifier not in self.expected_ids:
                self.expected_ids.add(identifier)
                yield {
                    "id": identifier,
                    "categories": categories,
                    "announcement_date": announced.isoformat(),
                }
        next_skip = skip + len(papers)
        if next_skip < total:
            yield self.list_request(category, next_skip)
        elif next_skip != total:
            raise ValueError("Page length exceeds advertised listing total")

    def audit(self, reason):
        errors = list(self.errors)
        stats = self.crawler.stats.get_stats() if getattr(self, "crawler", None) else {}
        if reason != "finished":
            errors.append("crawl_did_not_finish_cleanly")
        if any(
            value
            for key, value in stats.items()
            if key.startswith("spider_exceptions/")
        ):
            errors.append("spider_exception")
        for category in self.target_categories:
            state = self.listings.get(category)
            if state is None or len(state["rows"]) != state["total"]:
                errors.append("incomplete_listing:" + category)
        if (
            self.target_date
            and self.target_date.isoformat() not in self.announcement_dates
        ):
            errors.append("requested_date_not_in_recent_window")
        return {
            "complete": not errors,
            "errors": sorted(set(errors)),
            "scope": "recent announcement dates, new submissions and cross-lists",
            "announcement_dates": sorted(self.announcement_dates),
            "categories": sorted(self.target_categories),
            "listed_ids": sorted(self.listed_ids),
            "excluded_published_ids": sorted(self.excluded_history_ids),
            "expected_ids": sorted(self.expected_ids),
            "listing_counts": {
                category: {
                    "advertised": state["total"],
                    "parsed": len(state["rows"]),
                    "pages": len(state["pages"]),
                }
                for category, state in self.listings.items()
            },
        }

    def closed(self, reason):
        if self.audit_path:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            self.audit_path.write_text(
                json.dumps(self.audit(reason), indent=2), encoding="utf-8"
            )
