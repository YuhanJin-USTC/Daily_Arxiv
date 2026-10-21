"""Append newly generated rows while preserving a published day's exact bytes."""

import argparse
import json
import os
from pathlib import Path
import tempfile

from .history import paper_id


def identifiers(data):
    return [
        paper_id(json.loads(line)["id"]) for line in data.splitlines() if line.strip()
    ]


def merge_published(published, generated):
    published, generated = Path(published), Path(generated)
    if published.resolve() == generated.resolve():
        raise ValueError("Published and generated paths must be separate")
    added = generated.read_bytes()
    added_ids = identifiers(added)
    if len(added_ids) != len(set(added_ids)):
        raise ValueError("New data contains duplicate ids")
    if not published.exists():
        return
    original = published.read_bytes()
    old_ids = set(identifiers(original))
    if old_ids.intersection(added_ids):
        raise ValueError("Refusing to overwrite a published record")
    if original and not original.endswith(b"\n"):
        raise ValueError(
            "Published JSONL has no final newline; refusing to change its bytes"
        )
    with tempfile.NamedTemporaryFile(
        "wb", dir=generated.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(original + added)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, generated)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--published", required=True)
    parser.add_argument("--generated", required=True)
    args = parser.parse_args()
    merge_published(args.published, args.generated)


if __name__ == "__main__":
    main()
