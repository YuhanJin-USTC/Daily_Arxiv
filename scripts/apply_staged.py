"""Verify every source/candidate hash before applying a staged data repair."""

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(1, str(Path(__file__).resolve().parents[1] / "daily_arxiv"))
from ai.config import validate_language
from ai.quality import validate_records
from ai.recover import check_sources, verify_repair
from ai.storage import digest, write_bytes
from daily_arxiv.history import paper_id


def staged_files(source, staged, manifest):
    if manifest.get("complete") is not True:
        raise ValueError("Incomplete stage cannot be applied")
    if manifest["kind"] == "repair":
        for entry in manifest["entries"]:
            day = date.fromisoformat(entry["date"]).isoformat()
            language = entry["language"]
            if language not in ("English", "Chinese") or (
                entry["file"] != f"{day}_AI_enhanced_{language}.jsonl"
                or entry["raw_file"] != f"{day}.jsonl"
                or (
                    entry["failed"] and entry["markdown_file"] != f"{day}_{language}.md"
                )
            ):
                raise ValueError("Invalid repair manifest path")
        check_sources(source / "data", manifest["entries"])
        files = []
        for entry in manifest["entries"]:
            if not entry["failed"]:
                continue
            verify_repair(
                (source / "data" / entry["file"]).read_bytes(),
                (staged / "data" / entry["file"]).read_bytes(),
                entry,
            )
            files += [
                {
                    "path": "data/" + entry["file"],
                    "before": entry["source_sha256"],
                    "after": entry["output_sha256"],
                },
                {
                    "path": "data/" + entry["markdown_file"],
                    "before": entry["markdown_source_sha256"],
                    "after": entry["markdown_output_sha256"],
                },
            ]
        return files
    if manifest["kind"] not in ("append", "raw", "language"):
        raise ValueError("Unknown stage type")
    if manifest["kind"] != "raw":
        validate_language(manifest["language"])
    return manifest["files"]


def apply(source, staged, verify_only=False):
    source, staged = source.resolve(), staged.resolve()
    if source == staged or source in staged.parents or staged in source.parents:
        raise ValueError("Use separate source and staging directories")
    manifest = json.loads((staged / "manifest.json").read_text())
    files = staged_files(source, staged, manifest)
    seen = set()
    for entry in files:
        name = entry["path"]
        if name in seen or not re.fullmatch(
            r"(?:data/\d{4}-\d{2}-\d{2}(?:(?:_AI_enhanced_(?:English|Chinese))?\.jsonl|_(?:English|Chinese)\.md)|data/(?:pipeline-state|notification-state)\.json|data/ai-checkpoints/(?:English|Chinese)\.json|assets/(?:file-list\.txt|researcher-index\.json))",
            name,
        ):
            raise ValueError("Invalid or repeated staged path")
        if manifest["kind"] == "raw" and (
            "_AI_enhanced_" in name
            or name.endswith(".md")
            or "/ai-checkpoints/" in name
        ):
            raise ValueError("Raw stage contains language output")
        if (
            manifest["kind"] == "language"
            and name.startswith("data/")
            and name != "data/pipeline-state.json"
        ):
            language = manifest["language"]
            if not (
                name.endswith(f"_AI_enhanced_{language}.jsonl")
                or name.endswith(f"_{language}.md")
                or name == f"data/ai-checkpoints/{language}.json"
            ):
                raise ValueError("Language stage contains another language or raw data")
        if (
            name in ("data/notification-state.json", "assets/researcher-index.json")
            and manifest["kind"] != "raw"
        ):
            raise ValueError(
                "Only raw staging may include notification cohorts or matching index"
            )
        seen.add(name)
        target, candidate = source / name, staged / name
        if not target.resolve().is_relative_to(
            source
        ) or not candidate.resolve().is_relative_to(staged):
            raise ValueError("Staged path escapes its directory")
        current = digest(target) if target.exists() else None
        if current != entry["before"] or digest(candidate) != entry["after"]:
            raise ValueError("Source or candidate hash changed; refusing overwrite")
        if name == "data/notification-state.json":
            from daily_arxiv.notifications import validate_state

            validate_state(json.loads(candidate.read_text()))
        if name == "assets/researcher-index.json":
            index = json.loads(candidate.read_text())
            if (
                index.get("schema_version") != 1
                or not re.fullmatch(r"[0-9a-f]{64}", index.get("config_digest", ""))
                or not isinstance(index.get("papers"), dict)
            ):
                raise ValueError("Invalid researcher index")
        if manifest["kind"] in ("append", "raw", "language") and name.endswith(
            ".jsonl"
        ):
            old = target.read_bytes() if target.exists() else b""
            new = candidate.read_bytes()
            if not new.startswith(old):
                raise ValueError("Published bytes were replaced")
            old_ids = {
                paper_id(json.loads(line)["id"])
                for line in old.splitlines()
                if line.strip()
            }
            added = [
                json.loads(line)
                for line in new[len(old) :].splitlines()
                if line.strip()
            ]
            added_ids = [paper_id(row["id"]) for row in added]
            if old_ids.intersection(added_ids) or len(added_ids) != len(set(added_ids)):
                raise ValueError("Append contains duplicate/published IDs")
            if "_AI_enhanced_" in name:
                validate_records(added)
    if not verify_only:
        for entry in files:
            write_bytes(source / entry["path"], (staged / entry["path"]).read_bytes())
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", required=True, type=Path, help="Data branch checkout root"
    )
    parser.add_argument("--staged", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    count = apply(args.source, args.staged, args.verify_only)
    print(f"Verified {count} staged files; applied={not args.verify_only}")


if __name__ == "__main__":
    main()
