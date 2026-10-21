"""Plan or stage archived repairs in either language, preserving healthy bytes."""

import argparse
import copy
from datetime import date, timedelta
import json
from pathlib import Path
import sys

from .config import settings, validate_credentials
from .errors import EnhancementError, safe_failure
from .quality import index_records, read_records, valid_ai, validate_records
from .storage import digest, write_bytes, write_json
from .structured_output import valid_fields


def plan_recovery(source, start, end, language, ids=(), expected_count=None):
    if start > end:
        raise ValueError("Invalid date range")
    if ids and start != end:
        raise ValueError("An exact-ID repair requires a single date")
    entries = []
    current = start
    while current <= end:
        raw = source / f"{current}.jsonl"
        enhanced = source / f"{current}_AI_enhanced_{language}.jsonl"
        originals = index_records(read_records(raw), allow_identical_duplicates=True)
        rows = read_records(enhanced)
        by_id = index_records(rows)
        if not rows or (expected_count is not None and len(rows) != expected_count):
            raise ValueError("Unexpected source record count")
        if ids and not set(ids) <= by_id.keys():
            raise ValueError("Exact repair ID is absent")
        failed = []
        for row in rows:
            if not valid_ai(row.get("AI")):
                if ids and row["id"] not in ids:
                    raise ValueError(
                        "Another failed record exists outside the exact repair scope"
                    )
                archived = originals[row["id"]]
                if not archived.get("summary") or archived["summary"] != row.get(
                    "summary"
                ):
                    raise ValueError("Archived abstract mismatch")
                failed.append(row["id"])
        entries.append(
            {
                "date": str(current),
                "language": language,
                "file": enhanced.name,
                "raw_file": raw.name,
                "total": len(rows),
                "failed": len(failed),
                "preserved": len(rows) - len(failed),
                "failed_ids": failed,
                "source_sha256": digest(enhanced),
                "raw_sha256": digest(raw),
            }
        )
        current += timedelta(days=1)
    return entries


def check_sources(source, entries):
    for entry in entries:
        if (
            digest(source / entry["file"]) != entry["source_sha256"]
            or digest(source / entry["raw_file"]) != entry["raw_sha256"]
        ):
            raise ValueError("Source changed; create a fresh repair plan")


def verify_repair(original, candidate, entry):
    before = original.splitlines(keepends=True)
    after = candidate.splitlines(keepends=True)
    if len(before) != len(after):
        raise ValueError("Record count or layout changed")
    targets = set(entry["failed_ids"])
    for old_line, new_line in zip(before, after):
        if not old_line.strip():
            if old_line != new_line:
                raise ValueError("Blank-line bytes changed")
            continue
        old, new = json.loads(old_line), json.loads(new_line)
        if old["id"] not in targets:
            if old_line != new_line:
                raise ValueError("Healthy record bytes changed")
            continue
        if {k: v for k, v in old.items() if k not in ("AI", "AI_status")} != {
            k: v for k, v in new.items() if k not in ("AI", "AI_status")
        }:
            raise ValueError("Target metadata changed")
        if not valid_ai(new.get("AI")) or any(
            new["AI"].get(k) != v for k, v in valid_fields(old.get("AI")).items()
        ):
            raise ValueError(
                "Target fields are incomplete or existing valid values changed"
            )
    validate_records([json.loads(line) for line in after if line.strip()])


def stage_recovery(source, output, entries, generate, resume=None):
    """Only complete files get staged; checkpoint fields survive any later failure."""
    if output.exists():
        raise ValueError("Output must be a new directory")
    check_sources(source, entries)
    output.mkdir(parents=True)
    manifest = {"complete": False, "kind": "repair", "entries": copy.deepcopy(entries)}
    write_json(output / "manifest.json", manifest)
    for entry in manifest["entries"]:
        if not entry["failed"]:
            continue
        source_path = source / entry["file"]
        before = source_path.read_bytes()
        lines = before.splitlines(keepends=True)
        updated = []
        for line in lines:
            if not line.strip():
                updated.append(line)
                continue
            row = json.loads(line)
            if row["id"] not in entry["failed_ids"]:
                updated.append(line)
                continue
            work = copy.deepcopy(row)
            name = f"{entry['date']}-{row['id'].replace('/', '_')}.json"
            binding = {
                "id": row["id"],
                "language": entry["language"],
                "source_sha256": entry["source_sha256"],
            }
            if resume is not None and (resume / name).exists():
                checkpoint = json.loads((resume / name).read_text())
                if any(checkpoint.get(k) != v for k, v in binding.items()):
                    raise ValueError("Checkpoint belongs to another source or language")
                work["AI"] = {
                    **valid_fields(checkpoint.get("AI")),
                    **valid_fields(row.get("AI")),
                }
            try:
                generated = generate(work, entry["language"])
            except EnhancementError as error:
                partial = error.record or work
                write_json(
                    output / "checkpoints" / name,
                    {**binding, "AI": valid_fields(partial.get("AI"))},
                )
                raise
            fields = {
                **valid_fields(generated.get("AI")),
                **valid_fields(row.get("AI")),
            }
            write_json(output / "checkpoints" / name, {**binding, "AI": fields})
            if not valid_ai(fields):
                raise EnhancementError("Recovery still incomplete; checkpoint saved")
            row["AI"] = fields
            row.pop("AI_status", None)
            ending = (
                b"\r\n"
                if line.endswith(b"\r\n")
                else b"\n"
                if line.endswith(b"\n")
                else b""
            )
            updated.append(json.dumps(row, ensure_ascii=False).encode() + ending)
        candidate = b"".join(updated)
        verify_repair(before, candidate, entry)
        check_sources(source, entries)
        destination = output / "data" / entry["file"]
        write_bytes(destination, candidate)
        entry["output_sha256"] = digest(destination)
        from to_md.convert import convert

        markdown = convert(destination, language=entry["language"])
        entry["markdown_file"] = markdown.name
        old_markdown = source / markdown.name
        entry["markdown_source_sha256"] = (
            digest(old_markdown) if old_markdown.exists() else None
        )
        entry["markdown_output_sha256"] = digest(markdown)
    check_sources(source, entries)
    manifest["complete"] = True
    write_json(output / "manifest.json", manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--ids", default="", help="Comma-separated exact IDs; requires one date"
    )
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--resume", type=Path, help="Checkpoint directory from the same source"
    )
    args = parser.parse_args(argv)
    try:
        entries = plan_recovery(
            args.source,
            args.start,
            args.end,
            settings()["language"],
            tuple(filter(None, args.ids.split(","))),
            args.expected_count,
        )
        print(json.dumps(entries, indent=2))
        if args.generate:
            if args.output is None:
                raise ValueError("--output is required")
            validate_credentials()
            from .deepseek import DeepSeekSummaryChain
            from .enhance import process_single_item

            chain = DeepSeekSummaryChain()
            try:
                stage_recovery(
                    args.source,
                    args.output,
                    entries,
                    lambda row, language: process_single_item(chain, row, language),
                    args.resume,
                )
            finally:
                chain.close()
        return 0
    except Exception as error:
        print(str(safe_failure(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
