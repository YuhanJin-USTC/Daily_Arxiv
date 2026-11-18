"""Fetch arXiv metadata by normalized identity, preserving listing order."""

from functools import partial
import logging
import time

import arxiv
from requests import exceptions

from daily_arxiv.history import paper_id

BATCH_SIZE = 50
logger = logging.getLogger(__name__)


class MetadataClient(arxiv.Client):
    def __init__(self):
        super().__init__(page_size=BATCH_SIZE, delay_seconds=3, num_retries=0)
        # arxiv.py 2.1.3 supplies no timeout on its session's GET.
        self._session.get = partial(self._session.get, timeout=60)

    def _parse_feed(self, url, first_page=True, _try_index=0):
        # A batch fits in one page. Recover a short page using only missing IDs.
        if not first_page:
            raise arxiv.UnexpectedEmptyPageError(url, 0, {})
        return super()._parse_feed(url, first_page, _try_index)


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
