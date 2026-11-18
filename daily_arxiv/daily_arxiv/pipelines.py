"""Fetch arXiv metadata by normalized identity, preserving listing order."""

from io import BytesIO
import logging
import time
from xml.etree import ElementTree

import arxiv
from requests import exceptions

from daily_arxiv.history import paper_id

BATCH_SIZE = 50
logger = logging.getLogger(__name__)


class MetadataClient(arxiv.Client):
    def __init__(self):
        super().__init__(page_size=BATCH_SIZE, delay_seconds=3, num_retries=0)
        get = self._session.get

        def get_page(url, **kwargs):
            response = get(url, timeout=60, **kwargs)
            self._page_body = response.content
            return response

        self._session.get = get_page

    def results(self, search, offset=0):
        # Use one SDK request. A short page is retried with the missing IDs.
        feed = self._parse_feed(self._format_url(search, offset, self.page_size))
        entries = feed.entries
        if feed.bozo:
            # feedparser can return an unfinished entry with plausible-looking fields.
            closed = 0
            try:
                for _, element in ElementTree.iterparse(BytesIO(self._page_body)):
                    if element.tag == "{http://www.w3.org/2005/Atom}entry":
                        closed += 1
            except ElementTree.ParseError:
                pass
            entries = entries[:closed]
        for entry in entries:
            if not entry.get("id"):
                continue
            # Preserve the ID for verification even when the body is incomplete.
            if entry.get("title"):
                try:
                    paper = arxiv.Result._from_feed_entry(entry)
                except (AttributeError, KeyError, TypeError, ValueError):
                    pass
                else:
                    yield paper
                    continue
            yield arxiv.Result(entry_id=entry.id)


class MetadataError(ValueError):
    """A diagnostic suitable for the coverage audit."""


def fetch_batch(client, pending, received, attempts):
    for delay in (0, 30, 120, 300):
        if delay:
            time.sleep(delay)
        attempt = {"requested_ids": pending}
        attempts.append(attempt)
        try:
            for paper in client.results(arxiv.Search(id_list=pending)):
                identifier = paper_id(paper.entry_id)
                if identifier not in pending:
                    raise MetadataError(f"unexpected_metadata_id:{identifier}")
                # The abstract/PDF links are derived from the validated ID.
                if not all(
                    (paper.title, paper.summary, paper.authors, paper.categories)
                ):
                    continue
                row = {
                    "id": identifier,
                    "pdf": f"https://arxiv.org/pdf/{identifier}",
                    "abs": f"https://arxiv.org/abs/{identifier}",
                    "authors": [author.name for author in paper.authors],
                    "title": paper.title,
                    "categories": paper.categories,
                    "comment": paper.comment,
                    "summary": paper.summary,
                }
                if identifier in received and received[identifier] != row:
                    raise MetadataError(f"conflicting_metadata:{identifier}")
                received[identifier] = row
            reason = "partial_response"
        except arxiv.HTTPError as error:
            reason = f"http_{error.status}"
            if error.status != 429 and not 500 <= error.status < 600:
                raise MetadataError(reason) from error
        except (
            arxiv.UnexpectedEmptyPageError,
            exceptions.ConnectionError,
            exceptions.Timeout,
            exceptions.ChunkedEncodingError,
        ) as error:
            reason = type(error).__name__
        pending = [identifier for identifier in pending if identifier not in received]
        if not pending:
            return
        attempt["error"] = reason
        logger.warning("arXiv metadata %s, %d IDs outstanding", reason, len(pending))
    raise MetadataError(f"metadata_retries_exhausted:{reason}")


class DailyArxivPipeline:
    """Keep the standalone Scrapy item pipeline usable by feed exporters."""

    def __init__(self):
        self.client = MetadataClient()

    def process_item(self, item: dict, spider):
        identifier = paper_id(item["id"])
        received = {}
        fetch_batch(self.client, [identifier], received, [])
        return {**item, **received[identifier]}
