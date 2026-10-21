"""Fail when a listed paper is lost in fetching or metadata enrichment."""

import argparse
import json
from pathlib import Path

from .history import paper_id


def validate(data_path, audit_path):
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    if audit.get("complete") is not True:
        raise ValueError(
            "Listing coverage failed: " + ", ".join(audit.get("errors", []))
        )
    ids = []
    required = ("title", "summary", "authors", "categories", "abs", "pdf")
    for line in Path(data_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        ids.append(paper_id(row["id"]))
        if any(not row.get(field) for field in required):
            raise ValueError("Metadata is incomplete for " + ids[-1])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate ids in crawl output")
    expected = set(audit["expected_ids"])
    if set(ids) != expected:
        raise ValueError(
            f"Crawl differs from listing: missing={sorted(expected - set(ids))}, "
            f"unexpected={sorted(set(ids) - expected)}"
        )
    return {
        "complete": True,
        "records": len(ids),
        "already_published": len(audit["excluded_published_ids"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--audit", required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.data, args.audit)))


if __name__ == "__main__":
    main()
