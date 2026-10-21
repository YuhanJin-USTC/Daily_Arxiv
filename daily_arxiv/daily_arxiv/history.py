"""Read published identities without changing or regenerating records."""

import json
from pathlib import Path
import re


def paper_id(value):
    if not isinstance(value, str):
        raise ValueError("Paper id must be a string")
    value = re.sub(r"v\d+$", "", re.sub(r"^https?://arxiv.org/abs/", "", value))
    if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})", value):
        raise ValueError("Invalid arXiv id")
    return value


def load_history_ids(directory):
    if directory is None:
        return set()
    path = Path(directory)
    if not path.is_dir():
        raise ValueError("Published history directory does not exist")
    ids = set()
    for file in sorted(path.glob("*.jsonl")):
        if "_AI_enhanced_" not in file.name and not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}\.jsonl", file.name
        ):
            continue
        for line in file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(paper_id(json.loads(line)["id"]))
    return ids
