"""Conservative name matching shared by site indexes and notifications."""

import hashlib
import json
from pathlib import Path
import re
import unicodedata

from .history import paper_id

RAW_NAME = re.compile(r"\d{4}-\d{2}-\d{2}\.jsonl")


def normalize_name(value):
    if not isinstance(value, str):
        raise ValueError("Author name must be a string")
    value = unicodedata.normalize("NFKC", value).casefold()
    # Split dotted initials, without changing punctuation inside full names.
    value = re.sub(r"(?<!\w)([^\W\d_])\.(?=[^\W\d_]\.)", r"\1 ", value)
    value = re.sub(r"(?<!\w)([^\W\d_])\.(?=\s|$)", r"\1", value)
    return " ".join(value.split())


def config_digest(researchers, categories=()):
    content = json.dumps(
        {"researchers": researchers, "categories": sorted(set(categories))},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(content.encode()).hexdigest()


def match_paper(row, researchers, categories):
    if not set(row.get("categories", [])).intersection(categories):
        return []
    matches = []
    for author in row.get("authors", []):
        normalized = normalize_name(author)
        for researcher in researchers:
            if not researcher.get("enabled", True):
                continue
            reliable = [researcher["display_name"], *researcher.get("aliases", [])]
            suspected = researcher.get("suspected_aliases", [])
            kind, basis = None, None
            for candidate in reliable:
                if normalized == normalize_name(candidate):
                    kind = "reliable"
                    basis = (
                        "full_name"
                        if candidate == researcher["display_name"]
                        else "confirmed_alias"
                    )
                    break
            if kind is None:
                for candidate in suspected:
                    if normalized == normalize_name(candidate):
                        kind, basis = "suspected", "unconfirmed_alias"
                        break
            if kind is not None:
                match = {
                    "researcher_id": researcher["id"],
                    "display_name": researcher["display_name"],
                    "author": author,
                    "kind": kind,
                    "basis": basis,
                }
                if match not in matches:
                    matches.append(match)
    return matches


def build_index(directory, researchers, categories):
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError("Published raw data directory does not exist")
    papers = {}
    for path in sorted(directory.glob("*.jsonl")):
        if not RAW_NAME.fullmatch(path.name):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            identifier = paper_id(row["id"])
            matches = match_paper(row, researchers, categories)
            if matches:
                prior = papers.setdefault(identifier, [])
                prior.extend(match for match in matches if match not in prior)
    return {
        "schema_version": 1,
        "config_digest": config_digest(researchers, categories),
        "papers": papers,
    }
