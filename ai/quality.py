"""Shared, offline publication checks (also recognize legacy error placeholders)."""

import argparse
import json
import sys
from pathlib import Path

from .structured_output import DEFAULT_AI_FIELDS, PLACEHOLDERS

FIELDS = tuple(DEFAULT_AI_FIELDS)


def valid_value(value):
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.strip().casefold() not in PLACEHOLDERS
    )


def valid_ai(ai):
    return isinstance(ai, dict) and all(valid_value(ai.get(field)) for field in FIELDS)


def index_records(records, *, allow_identical_duplicates=False):
    result = {}
    for row in records:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not row["id"]
        ):
            raise ValueError("Missing paper identity")
        if row["id"] in result:
            if allow_identical_duplicates and row == result[row["id"]]:
                continue
            raise ValueError("Conflicting or duplicate paper identity")
        result[row["id"]] = row
    return result


def read_records(path):
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def validate_records(records):
    if not records:
        raise ValueError("No valid records to publish")
    seen = set()
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid record at index {index}")
        paper_id = item.get("id")
        if not isinstance(paper_id, str) or not paper_id.strip() or paper_id in seen:
            raise ValueError(f"Missing or duplicate ID at index {index}")
        seen.add(paper_id)
        if not valid_ai(item.get("AI")):
            raise ValueError(f"Invalid AI fields at index {index}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument(
        "--audit-history",
        action="store_true",
        help="Audit all archived dates without model calls",
    )
    args = parser.parse_args()
    try:
        if args.audit_history:
            from .config import settings

            report = []
            for path in sorted(
                Path(args.path).glob(f"*_AI_enhanced_{settings()['language']}.jsonl")
            ):
                rows = read_records(path)
                index_records(rows)
                failed = [row["id"] for row in rows if not valid_ai(row.get("AI"))]
                report.append(
                    {
                        "file": path.name,
                        "records": len(rows),
                        "failed": len(failed),
                        "failed_ids": failed,
                        "empty": not rows,
                    }
                )
            print(json.dumps(report, indent=2))
            return 0
        records = read_records(args.path)
        validate_records(records)
    except (OSError, ValueError):
        print("AI output validation failed; publication blocked", file=sys.stderr)
        return 1
    print(f"AI output validated: {len(records)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
