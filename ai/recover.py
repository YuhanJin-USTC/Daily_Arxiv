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
from .reuse import SuccessfulSummaries
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


def load_checkpoints(directory, entries):
    if directory is None:
        return {}
    if not directory.is_dir():
        raise ValueError("Checkpoint directory is absent")
    bindings = {
        f"{entry['date']}-{identifier.replace('/', '_')}.json": {
            "id": identifier,
            "language": entry["language"],
            "source_sha256": entry["source_sha256"],
        }
        for entry in entries
        for identifier in entry["failed_ids"]
    }
    snapshot = directory / "snapshot.json"
    if snapshot.exists() and (
        snapshot.is_symlink()
        or not snapshot.resolve().is_relative_to(directory.resolve())
    ):
        raise ValueError("Unsafe checkpoint path")
    checkpoints = json.loads(snapshot.read_text()) if snapshot.exists() else {}
    if not isinstance(checkpoints, dict) or not checkpoints.keys() <= bindings.keys():
        raise ValueError("Checkpoint snapshot contains unknown paper IDs")
    for name in bindings:
        path = directory / name
        if path.exists():
            if path.is_symlink() or not path.resolve().is_relative_to(
                directory.resolve()
            ):
                raise ValueError("Unsafe checkpoint path")
            checkpoints[name] = json.loads(path.read_text())
    for name, saved in checkpoints.items():
        if not isinstance(saved, dict) or any(
            saved.get(key) != value for key, value in bindings[name].items()
        ):
            raise ValueError("Checkpoint belongs to another source or language")
    return checkpoints


def stage_recovery(source, output, entries, generate, resume=None, success_source=None):
    """Only complete files get staged; checkpoint fields survive any later failure."""
    if output.exists():
        raise ValueError("Output must be a new directory")
    check_sources(source, entries)
    targets = [
        (entry, row)
        for entry in entries
        for row in read_records(source / entry["file"])
        if row["id"] in entry["failed_ids"]
    ]
    language = entries[0]["language"] if entries else None
    if any(entry["language"] != language for entry in entries):
        raise ValueError("A recovery batch must have one language")
    reusable = SuccessfulSummaries(
        success_source, [row for _, row in targets], language
    )
    checkpoints = load_checkpoints(resume, entries)
    for entry, target in targets:
        name = f"{entry['date']}-{target['id'].replace('/', '_')}.json"
        retained = {
            **valid_fields(checkpoints.get(name, {}).get("AI")),
            **valid_fields(target.get("AI")),
        }
        reusable.fields({**target, "AI": retained})
    output.mkdir(parents=True)
    write_json(output / "checkpoints/snapshot.json", checkpoints)
    manifest = {"complete": False, "kind": "repair", "entries": copy.deepcopy(entries)}
    write_json(output / "manifest.json", manifest)

    def save_checkpoint(name, binding, fields):
        checkpoints[name] = {**binding, "AI": fields}
        write_json(output / "checkpoints" / name, checkpoints[name])
        write_json(output / "checkpoints/snapshot.json", checkpoints)

    for entry in manifest["entries"]:
        entry.update(
            model_paper_ids=[],
            reused_ids=[],
            checkpoint_reused_ids=[],
            reuse_sources={},
        )
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
            if name in checkpoints:
                checkpoint = checkpoints[name]
                work["AI"] = {
                    **valid_fields(checkpoint.get("AI")),
                    **valid_fields(row.get("AI")),
                }
                if valid_ai(work["AI"]):
                    entry["checkpoint_reused_ids"].append(row["id"])
            reused, origins = reusable.fields(work)
            if reused:
                work["AI"] = {**reused, **valid_fields(work.get("AI"))}
                entry["reused_ids"].append(row["id"])
                entry["reuse_sources"][row["id"]] = origins
            try:
                if valid_ai(work.get("AI")):
                    generated = work
                else:
                    entry["model_paper_ids"].append(row["id"])
                    write_json(output / "manifest.json", manifest)
                    generated = generate(work, entry["language"])
            except EnhancementError as error:
                partial = error.record or work
                save_checkpoint(
                    name,
                    binding,
                    {**valid_fields(work.get("AI")), **valid_fields(partial.get("AI"))},
                )
                raise
            fields = {
                **valid_fields(generated.get("AI")),
                **valid_fields(work.get("AI")),
                **valid_fields(row.get("AI")),
            }
            save_checkpoint(name, binding, fields)
            if not valid_ai(fields):
                raise EnhancementError("Recovery still incomplete; checkpoint saved")
            row["AI"] = fields
            row.pop("AI_status", None)
            reusable.add(row, "staged:" + entry["file"])
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
        reusable.source_hashes["staged:" + entry["file"]] = entry["output_sha256"]
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
    parser.add_argument(
        "--success-source",
        type=Path,
        help="Same-language archive for identical-abstract reuse",
    )
    args = parser.parse_args(argv)
    try:
        entries = plan_recovery(
            args.source,
            args.start,
            args.end,
            settings()["language"],
            tuple(value.strip() for value in args.ids.split(",") if value.strip()),
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
                    args.success_source or args.source,
                )
            finally:
                chain.close()
        return 0
    except Exception as error:
        print(str(safe_failure(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
