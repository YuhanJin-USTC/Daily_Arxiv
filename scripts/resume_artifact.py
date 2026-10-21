"""Bind resumed Actions artifacts to the current request and archived sources."""

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "daily_arxiv"))
from ai.config import settings
from ai.enhance import resume_rows
from ai.quality import read_records
from ai.recover import load_checkpoints, plan_recovery
from ai.storage import digest, write_bytes, write_json
from daily_arxiv.history import load_history_ids, paper_id
from daily_arxiv.validate_crawl import validate

INVENTORY = ROOT / "docs/audits/arxiv-2026-10-20.json"


def selector(kind, run_id, name):
    if not run_id and not name:
        return
    prefix = "recovery" if kind == "repair" else "backfill"
    if not re.fullmatch(r"[1-9]\d*", run_id) or not re.fullmatch(
        rf"arxiv-{prefix}-{re.escape(run_id)}-[1-9]\d*", name
    ):
        raise ValueError("Provide a matching run ID and artifact name of this workflow")


def checked_file(root, name):
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("Artifact path escapes its directory")
    if not path.is_file():
        raise ValueError("Required recovery evidence is absent")
    return path


def request(kind, source, start, end, ids, expected_count):
    config = settings()
    base = {
        "version": 1,
        "kind": kind,
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "language": config["language"],
        "ids": sorted(ids),
        "profile": config["deepseek"],
        "prompt_sha256": {
            name: digest(ROOT / "ai" / name)
            for name in ("system.txt", "template.txt", "structure.py")
        },
    }
    if kind == "repair":
        base.update(
            start=start.isoformat(),
            end=end.isoformat(),
            expected_count=expected_count,
            entries=plan_recovery(
                source / "data", start, end, config["language"], ids, expected_count
            ),
        )
    else:
        inventory = json.loads(INVENTORY.read_text())
        day = inventory["announcement_date"]
        all_ids = {paper_id(row["id"]) for row in inventory["papers"]}
        if set(inventory["categories"]) != set(config["categories"]):
            raise ValueError("Inventory categories differ from the project")
        if not set(ids) <= all_ids:
            raise ValueError("Requested IDs are outside the inventory")
        missing = all_ids - load_history_ids(source / "data")
        selected = missing & set(ids) if ids else missing
        names = [
            f"data/{day}.jsonl",
            f"data/{day}_AI_enhanced_{config['language']}.jsonl",
            f"data/{day}.md",
            "assets/file-list.txt",
        ]
        base.update(
            date=day,
            inventory_sha256=digest(INVENTORY),
            selected_ids=sorted(selected),
            sources={
                name: digest(source / name) if (source / name).exists() else None
                for name in names
            },
        )
    return base


def prepare(
    kind, source, output, resume=None, start=None, end=None, ids=(), expected_count=None
):
    if len(ids) != len(set(ids)):
        raise ValueError("Requested IDs must be unique")
    binding = request(kind, source, start, end, ids, expected_count)
    if resume is not None:
        if (
            output.resolve() == resume.resolve()
            or output.resolve().is_relative_to(resume.resolve())
            or resume.resolve().is_relative_to(output.resolve())
        ):
            raise ValueError("Use separate old and new artifact directories")
        previous = json.loads(checked_file(resume, "request.json").read_text())
        if previous.get("request") != binding:
            raise ValueError(
                "Artifact request, sources, language or model profile changed"
            )
        manifest = json.loads(checked_file(resume, "ready/manifest.json").read_text())
        if manifest.get("kind") != kind:
            raise ValueError("Artifact has the wrong operation kind")
        if kind == "repair":
            saved_entries = manifest.get("entries", [])
            if len(saved_entries) != len(binding["entries"]):
                raise ValueError("Repair manifest scope changed")
            for saved, current in zip(saved_entries, binding["entries"]):
                if any(saved.get(key) != value for key, value in current.items()):
                    raise ValueError("Repair manifest sources changed")
            checkpoint_dir = resume / "ready/checkpoints"
            if (
                not checkpoint_dir.resolve().is_relative_to(resume.resolve())
                or not checkpoint_dir.is_dir()
            ):
                raise ValueError("Recovery checkpoints are absent or unsafe")
            load_checkpoints(checkpoint_dir, binding["entries"])
        else:
            if (
                manifest.get("date") != binding["date"]
                or manifest.get("language") != binding["language"]
            ):
                raise ValueError("Backfill manifest date or language changed")
            raw = checked_file(resume, binding["date"] + ".jsonl")
            audit = checked_file(resume, "coverage.json")
            if digest(raw) != previous.get("raw_sha256") or digest(
                audit
            ) != previous.get("coverage_sha256"):
                raise ValueError("Backfill snapshot changed")
            validate(raw, audit)
            if (
                sorted(row["id"] for row in read_records(raw))
                != binding["selected_ids"]
            ):
                raise ValueError("Backfill snapshot does not match the selected IDs")
            resume_rows(
                read_records(raw),
                checked_file(resume, "ready/checkpoint.json"),
                digest(raw),
                binding["language"],
            )
            for old, name in ((raw, raw.name), (audit, "coverage.json")):
                target = output / name
                if target.exists():
                    raise ValueError("New artifact snapshot already exists")
                write_bytes(target, old.read_bytes())
    evidence = {"request": binding}
    if kind == "append":
        raw = checked_file(output, binding["date"] + ".jsonl")
        audit = checked_file(output, "coverage.json")
        validate(raw, audit)
        if sorted(row["id"] for row in read_records(raw)) != binding["selected_ids"]:
            raise ValueError("Backfill selection differs from the request")
        evidence.update(raw_sha256=digest(raw), coverage_sha256=digest(audit))
    write_json(output / "request.json", evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("repair", "append"), required=True)
    parser.add_argument("--check-selector", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--ids", default="")
    parser.add_argument("--expected-count", type=int)
    args = parser.parse_args()
    selector(args.kind, args.run_id, args.name)
    if args.check_selector:
        return
    if (
        args.source is None
        or args.output is None
        or (args.kind == "repair" and (args.start is None or args.end is None))
    ):
        parser.error("Source, output and repair dates are required")
    ids = tuple(
        paper_id(value.strip()) for value in args.ids.split(",") if value.strip()
    )
    prepare(
        args.kind,
        args.source,
        args.output,
        args.resume,
        args.start,
        args.end,
        ids,
        args.expected_count,
    )


if __name__ == "__main__":
    main()
