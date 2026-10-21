"""Coordinate raw publication, notification cohorts and independent AI progress."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "daily_arxiv"))
from ai.config import settings, subscribed_categories, validate_credentials
from ai.quality import read_records
from ai.storage import digest, write_json
from daily_arxiv.history import paper_id
from daily_arxiv.notifications import (
    dispatch,
    enqueue_discoveries,
    new_state,
    validate_state,
)
from daily_arxiv.researchers import build_index
from scripts.apply_staged import apply
from scripts.bilingual_daily import load_state, stage_language, stage_raw
from scripts.publish_data import Publisher

QUEUE = "data/notification-state.json"
INDEX = "assets/researcher-index.json"


def configuration():
    return {**settings(), "categories": subscribed_categories()}


def load_queue(source):
    path = source / QUEUE
    if path.exists():
        return validate_state(json.loads(path.read_text()))
    state = load_state(source)
    if state["discoveries"]:
        raise ValueError(
            "Notification state is missing for existing discoveries; restore it before continuing"
        )
    return new_state(state["historical_ids"])


def refresh_index(source, config, publish=None):
    write_json(
        source / INDEX,
        build_index(source / "data", config["researchers"], config["categories"]),
    )
    if publish:
        publish([INDEX])


def raw_update(source, raw, coverage, day, output, config, publish=None):
    queue = load_queue(source)
    stage = stage_raw(source, raw, output, day, coverage)
    added = set(stage["added_ids"])
    rows = (
        [
            row
            for row in read_records(output / "data" / f"{day}.jsonl")
            if paper_id(row["id"]) in added
        ]
        if added
        else []
    )
    queue = enqueue_discoveries(
        queue, rows, day, config, load_state(source)["historical_ids"]
    )
    index = build_index(source / "data", config["researchers"], config["categories"])
    index["papers"].update(
        build_index(output / "data", config["researchers"], config["categories"])[
            "papers"
        ]
    )
    for name, value in ((QUEUE, queue), (INDEX, index)):
        before = digest(source / name) if (source / name).exists() else None
        write_json(output / name, value)
        stage["files"].append(
            {"path": name, "before": before, "after": digest(output / name)}
        )
    write_json(output / "manifest.json", stage)
    apply(source, output)
    if publish:
        publish([entry["path"] for entry in stage["files"]])
    return {"new_papers": len(added)}


def language_update(source, output, language, publish=None, generate=None):
    options = {"generate": generate} if generate is not None else {}
    stage = stage_language(source, output, language, **options)
    apply(source, output)
    if publish:
        publish([entry["path"] for entry in stage["files"]])
    return {
        "language": language,
        "completed": len(stage["completed_ids"]),
        "failures": stage["failures"],
    }


def send_notifications(
    source, config, publish, transport=None, environment=None, day=None
):
    if publish is None:
        raise ValueError("Sending requires a durable publication callback")
    state = load_queue(source)

    def persist(value):
        write_json(source / QUEUE, value)
        publish([QUEUE])

    return dispatch(
        state, config, persist, transport=transport, environment=environment, day=day
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("raw", "index", "ai", "notify"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--date")
    parser.add_argument("--language", choices=("English", "Chinese"))
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    publish = Publisher(args.source, args.repository) if args.publish else None
    config = configuration()
    if args.phase == "raw":
        if not all((args.raw, args.coverage, args.date, args.output)):
            parser.error("raw requires --raw --coverage --date --output")
        report = raw_update(
            args.source,
            args.raw,
            args.coverage,
            args.date,
            args.output,
            config,
            publish,
        )
    elif args.phase == "index":
        refresh_index(args.source, config, publish)
        report = {"index": "refreshed"}
    elif args.phase == "ai":
        if not args.output or not args.language:
            parser.error("ai requires --output --language")
        validate_credentials()
        report = language_update(args.source, args.output, args.language, publish)
    else:
        if not args.send or os.environ.get("ALLOW_SMTP_SEND") != "1":
            parser.error(
                "notify requires --send and ALLOW_SMTP_SEND=1; use notify.py for previews"
            )
        report = send_notifications(args.source, config, publish, day=args.date)
    print(json.dumps(report, indent=2))
    return int(
        bool(
            report.get("failures")
            or report.get("errors")
            or report.get("failed")
            or report.get("uncertain")
            or report.get("blocked")
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
