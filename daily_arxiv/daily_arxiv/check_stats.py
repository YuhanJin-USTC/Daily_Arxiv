"""Deduplicate by normalized id against the actual published data snapshot."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

if __package__:
    from .history import load_history_ids, paper_id
else:
    from history import load_history_ids, paper_id


def deduplicate(path, history_dir=None):
    path = Path(path)
    seen = load_history_ids(history_dir)
    retained = []
    input_rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        identifier = paper_id(row["id"])
        row["id"] = identifier
        if identifier in input_rows and input_rows[identifier] != row:
            raise ValueError("Conflicting duplicate input records")
        input_rows[identifier] = row
        if identifier not in seen:
            seen.add(identifier)
            row["id"] = identifier
            retained.append(row)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, encoding="utf-8", delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            for row in retained:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return len(retained)


def main():
    parser = argparse.ArgumentParser()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parser.add_argument("--data", default=f"../data/{today}.jsonl")
    parser.add_argument("--history-dir")
    args = parser.parse_args()
    try:
        count = deduplicate(args.data, args.history_dir)
    except Exception as exc:
        print(f"Deduplication failed ({type(exc).__name__})")
        return 2
    print(f"New unique papers: {count}")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())
