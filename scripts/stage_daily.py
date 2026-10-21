"""Stage new papers; never mutate the published checkout or healthy rows."""

import argparse
import copy
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "daily_arxiv"))
from ai.config import settings, validate_credentials
from ai.enhance import process_all_items, resume_rows
from ai.errors import EnhancementError, safe_failure
from ai.quality import read_records, valid_ai, validate_records
from ai.storage import digest, write_bytes, write_json, write_jsonl
from ai.structured_output import valid_fields
from daily_arxiv.merge_published import merge_published
from to_md.convert import convert


def stage(
    source, raw, output, day, generate=process_all_items, resume=None, coverage=None
):
    if output.exists():
        raise ValueError("Staging directory must be new")
    rows = read_records(raw)
    if not rows:
        return None
    language = settings()["language"]
    source_hash = digest(raw)
    names = [f"{day}.jsonl", f"{day}_AI_enhanced_{language}.jsonl", f"{day}.md"]
    paths = ["data/" + name for name in names] + ["assets/file-list.txt"]
    before = {
        name: digest(source / name) if (source / name).exists() else None
        for name in paths
    }
    existing = source / "data" / names[1]
    if existing.exists():
        validate_records(
            read_records(existing)
        )  # Repair old failures before paying for a backfill.
    if resume is not None:
        rows = resume_rows(rows, resume, source_hash, language)
    output.mkdir(parents=True)
    manifest = {
        "complete": False,
        "kind": "append",
        "date": day,
        "language": language,
        "files": [],
    }
    write_json(output / "manifest.json", manifest)
    write_bytes(output / "data" / names[0], raw.read_bytes())

    retained = {row["id"]: copy.deepcopy(row) for row in rows}

    def checkpoint(completed, partial):
        for row in [*completed, *([partial] if partial else [])]:
            prior = retained[row["id"]]
            retained[row["id"]] = {
                **row,
                "AI": {**valid_fields(prior.get("AI")), **valid_fields(row.get("AI"))},
            }
        partial_id = partial.get("id") if partial else None
        saved = list(retained.values())
        write_json(
            output / "checkpoint.json",
            {
                "source_sha256": source_hash,
                "language": language,
                "completed": [row for row in saved if valid_ai(row.get("AI"))],
                "pending": [
                    row
                    for row in saved
                    if valid_fields(row.get("AI"))
                    and not valid_ai(row.get("AI"))
                    and row["id"] != partial_id
                ],
                "partial": retained[partial_id]
                if partial_id is not None
                and not valid_ai(retained[partial_id].get("AI"))
                else None,
            },
        )

    checkpoint([], None)
    try:
        generated = generate(rows, language, progress=checkpoint)
    except EnhancementError as error:
        checkpoint(getattr(error, "completed", []), error.record)
        raise
    validate_records(generated)
    if digest(raw) != source_hash:
        raise ValueError("Raw snapshot changed during generation")
    if [r["id"] for r in generated] != [r["id"] for r in rows]:
        raise ValueError("AI processing changed IDs or order")
    write_jsonl(output / "data" / names[1], generated)
    for name in names[:2]:
        merge_published(source / "data" / name, output / "data" / name)
    convert(output / "data" / names[1], language=language)
    filenames = sorted(
        {
            p.name
            for root in (source / "data", output / "data")
            for p in root.glob("*.jsonl")
        }
    )
    write_bytes(output / "assets/file-list.txt", ("\n".join(filenames) + "\n").encode())
    for path in paths:
        current = digest(source / path) if (source / path).exists() else None
        if current != before[path]:
            raise ValueError("Published source changed during staging")
        manifest["files"].append(
            {"path": path, "before": before[path], "after": digest(output / path)}
        )
    manifest["complete"] = True
    manifest["added_count"] = len(generated)
    manifest["added_ids"] = [row["id"] for row in generated]
    if coverage is not None:
        if set(coverage["expected_ids"]) != set(manifest["added_ids"]):
            raise ValueError("Staged papers differ from the selected inventory")
        manifest["inventory_count"] = coverage["inventory_count"]
        manifest["remaining_inventory_count"] = len(coverage["remaining_ids"])
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help="Published repository root"
    )
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--resume", type=Path, help="Checkpoint from the same raw snapshot"
    )
    parser.add_argument(
        "--coverage", type=Path, help="Verified archived inventory audit"
    )
    args = parser.parse_args()
    try:
        validate_credentials()
        stage(
            args.source,
            args.raw,
            args.output,
            args.date.isoformat(),
            resume=args.resume,
            coverage=json.loads(args.coverage.read_text()) if args.coverage else None,
        )
        return 0
    except Exception as error:
        print(str(safe_failure(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
