"""Stage validated raw discoveries and independent, resumable language results."""

import argparse
import copy
from datetime import date
import hashlib
from inspect import signature
from itertools import groupby
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "daily_arxiv"))
from ai.config import validate_credentials, validate_language
from ai.enhance import process_all_items
from ai.errors import EnhancementError, safe_failure
from ai.quality import read_records, valid_ai, validate_records
from ai.reuse import generation_provenance
from ai.storage import digest, write_bytes, write_json, write_jsonl
from ai.structured_output import DERIVED_PAPER_FIELDS, valid_fields, validated_topics
from daily_arxiv.history import load_history_ids, paper_id
from daily_arxiv.merge_published import merge_published
from daily_arxiv.validate_crawl import validate
from to_md.convert import convert

LANGUAGES = ("English", "Chinese")
STATE = "data/pipeline-state.json"


def abstract_hash(row):
    return hashlib.sha256(row["summary"].encode()).hexdigest()


def source_hash(row):
    return hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def load_state(source):
    path = source / STATE
    state = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "version": 1,
            "historical_ids": sorted(load_history_ids(source / "data")),
            "discoveries": {},
        }
    )
    if state.get("version") != 1 or not isinstance(state.get("discoveries"), dict):
        raise ValueError("Unsupported pipeline state")
    historical = set(state["historical_ids"])
    if historical.intersection(state["discoveries"]):
        raise ValueError("Historical and new discovery identities overlap")
    for identifier, entry in state["discoveries"].items():
        if paper_id(identifier) != identifier:
            raise ValueError("Discovery ID must be normalized")
        if type(entry.get("topics_enabled", False)) is not bool:
            raise ValueError("Invalid discovery topic eligibility")
        date.fromisoformat(entry["date"])
        if set(entry["languages"]) != set(LANGUAGES) or any(
            status not in ("pending", "complete")
            for status in entry["languages"].values()
        ):
            raise ValueError("Invalid discovery language state")
    return state


class Stage:
    def __init__(self, source, output, kind, language=None):
        self.source, self.output = Path(source), Path(output)
        if output.exists() or output.resolve().is_relative_to(source.resolve()):
            raise ValueError("Use a new, separate staging directory")
        self.before = {}
        self.manifest = {
            "complete": False,
            "kind": kind,
            "language": language,
            "files": [],
        }
        output.mkdir(parents=True)
        write_json(output / "manifest.json", self.manifest)

    def track(self, name):
        path = self.source / name
        self.before.setdefault(name, digest(path) if path.exists() else None)

    def finish(self):
        for path in sorted(self.output.rglob("*")):
            if not path.is_file() or path.name == "manifest.json":
                continue
            name = path.relative_to(self.output).as_posix()
            if name not in self.before:
                raise ValueError("Unbound staged file")
            original = self.source / name
            if (digest(original) if original.exists() else None) != self.before[name]:
                raise ValueError("Published source changed during staging")
            self.manifest["files"].append(
                {"path": name, "before": self.before[name], "after": digest(path)}
            )
        self.manifest["complete"] = True
        write_json(self.output / "manifest.json", self.manifest)
        return self.manifest

    def index(self):
        self.track("assets/file-list.txt")
        names = sorted(
            {
                path.name
                for directory in (self.source / "data", self.output / "data")
                for path in directory.glob("*.jsonl")
            }
        )
        write_bytes(
            self.output / "assets/file-list.txt", ("\n".join(names) + "\n").encode()
        )


def stage_raw(source, raw, output, day, coverage):
    day = date.fromisoformat(day).isoformat()
    raw_hash, coverage_hash = digest(raw), digest(coverage)
    validate(raw, coverage)
    stage = Stage(source, output, "raw")
    stage.track(STATE)
    state = load_state(source)
    known = set(state["historical_ids"]) | state["discoveries"].keys()
    rows = read_records(raw)
    added = []
    for row in rows:
        identifier = paper_id(row["id"])
        if DERIVED_PAPER_FIELDS.intersection(row):
            raise ValueError("Raw discovery contains AI fields")
        if identifier in known:
            continue
        row = {**row, "id": identifier}
        state["discoveries"][identifier] = {
            "date": day,
            "summary_sha256": abstract_hash(row),
            "source_sha256": source_hash(row),
            "topics_enabled": True,
            "languages": {language: "pending" for language in LANGUAGES},
        }
        known.add(identifier)
        added.append(row)
    if digest(raw) != raw_hash or digest(coverage) != coverage_hash:
        raise ValueError("Raw snapshot or coverage changed during validation")
    if added:
        name = f"data/{day}.jsonl"
        stage.track(name)
        write_jsonl(output / name, added)
        merge_published(source / name, output / name)
    write_json(output / STATE, state)
    stage.index()
    stage.manifest.update(
        date=day,
        added_ids=[row["id"] for row in added],
        raw_sha256=raw_hash,
        coverage_sha256=coverage_hash,
    )
    return stage.finish()


def accepts_topic_option(generate):
    try:
        signature(generate).bind_partial(topics_enabled=True)
    except (TypeError, ValueError):
        return False
    return True


def prepare_language_days(
    stage, language, discoveries, selected, records, topic_profile, supports_topics
):
    if not records.keys() <= discoveries.keys():
        raise ValueError("Checkpoint contains an unknown discovery")
    groups = {}
    for identifier, entry in discoveries.items():
        requested = (
            identifier in selected
            if selected is not None
            else entry["languages"][language] == "pending"
        )
        if requested or identifier in records:
            groups.setdefault(entry["date"], []).append(identifier)

    # Verify all sources and partials before any model request, including later days.
    days = []
    for day, identifiers in sorted(groups.items()):
        raw = stage.source / "data" / f"{day}.jsonl"
        if not raw.is_file():
            raise ValueError("Discovery has no raw source")
        raw_hash = digest(raw)
        originals = {paper_id(row["id"]): row for row in read_records(raw)}
        name = f"data/{day}_AI_enhanced_{language}.jsonl"
        stage.track(name)
        path = stage.source / name
        existing = read_records(path) if path.exists() else []
        if existing:
            validate_records(existing)
        published = {paper_id(row["id"]): row for row in existing}
        work = []
        for identifier in identifiers:
            row = originals.get(identifier)
            entry = discoveries[identifier]
            eligible = language == "English" and entry.get("topics_enabled", False)
            if row is None or abstract_hash(row) != entry["summary_sha256"]:
                raise ValueError("Discovery source or abstract changed")
            binding = source_hash(row)
            if entry.get("source_sha256") != binding and (
                entry.get("source_sha256") is not None
                or (selected is not None and identifier in selected)
                or entry.get("topics_enabled", False)
            ):
                raise ValueError("Discovery source or abstract changed")
            saved = records.get(identifier)
            if saved is not None:
                if (
                    saved.get("summary_sha256") != entry["summary_sha256"]
                    or saved.get("source_sha256") != binding
                ):
                    raise ValueError("Checkpoint source or abstract changed")
                used_topics = "topic_provenance" in saved
                if (
                    used_topics
                    and (not eligible or saved["topic_provenance"] != topic_profile)
                ) or ("topics" in saved and not used_topics):
                    raise ValueError(
                        "Checkpoint topic prompt changed; explicit recovery required"
                    )
            if selected is not None and identifier not in selected:
                continue
            if identifier in published or entry["languages"][language] == "complete":
                result = published.get(identifier, {})
                if (
                    not valid_ai(result.get("AI"))
                    or result.get("summary") != row["summary"]
                    or (eligible and result.get("title") != row["title"])
                ):
                    raise ValueError("Published language row needs explicit recovery")
                entry["languages"][language] = "complete"
                records.pop(identifier, None)
                continue
            item = copy.deepcopy(row)
            if saved is not None:
                if used_topics != (eligible and supports_topics):
                    raise ValueError(
                        "Checkpoint topic prompt changed; explicit recovery required"
                    )
                item["AI"] = valid_fields(saved.get("AI"))
                topics = validated_topics(saved.get("topics"))
                if topics:
                    item["topics"] = topics
            work.append(item)
        if work:
            days.append((day, name, raw, raw_hash, originals, work))
    return days


def stage_language(source, output, language, generate=process_all_items, *, ids=None):
    language = validate_language(language)
    stage = Stage(source, output, "language", language)
    stage.track(STATE)
    state = load_state(source)
    selected = None
    if ids is not None:
        if isinstance(ids, str):
            raise ValueError("Selected IDs must be an explicit sequence")
        requested = [paper_id(identifier) for identifier in ids]
        if not requested or len(requested) != len(set(requested)):
            raise ValueError("Selected IDs must be nonempty and unique")
        selected = set(requested)
        if not selected <= state["discoveries"].keys():
            raise ValueError(
                "Selected IDs must be post-baseline discoveries; history is excluded"
            )
    stage.manifest["selected_ids"] = sorted(selected) if selected is not None else None
    provenance = generation_provenance()
    checkpoint_name = f"data/ai-checkpoints/{language}.json"
    stage.track(checkpoint_name)
    checkpoint_path = source / checkpoint_name
    checkpoints = (
        json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {}
    )
    if checkpoints.get("records") and (
        checkpoints.get("version") != 1
        or checkpoints.get("language") != language
        or checkpoints.get("provenance") != provenance
    ):
        raise ValueError(
            "Checkpoint language, model or prompt changed; explicit recovery required"
        )
    checkpoints = (
        checkpoints
        if checkpoints.get("records")
        else {
            "version": 1,
            "language": language,
            "provenance": provenance,
            "records": {},
        }
    )
    topic_provenance = (
        generation_provenance(topics_enabled=True) if language == "English" else None
    )
    discoveries = state["discoveries"]
    supports_topics = language == "English" and accepts_topic_option(generate)

    def topics_enabled(identifier):
        return supports_topics and discoveries[identifier].get("topics_enabled", False)

    days = prepare_language_days(
        stage,
        language,
        discoveries,
        selected,
        checkpoints["records"],
        topic_provenance,
        supports_topics,
    )
    stage.manifest.update(completed_ids=[], failures=[])
    for day, name, raw, raw_hash, originals, work in days:
        if digest(raw) != raw_hash:
            raise ValueError("Raw source changed before generation")
        retained = {paper_id(row["id"]): row for row in work}
        accepted = set()

        def checkpoint(completed, partial):
            accepted.update(paper_id(row["id"]) for row in completed)
            for row in [*completed, *([partial] if partial else [])]:
                identifier = paper_id(row["id"])
                if identifier not in batch_ids or any(
                    row.get(field) != originals[identifier].get(field)
                    for field in ("title", "summary")
                ):
                    raise ValueError("Generated identity, title or abstract changed")
                retained[identifier] = {
                    **row,
                    "AI": {
                        **valid_fields(retained[identifier].get("AI")),
                        **valid_fields(row.get("AI")),
                    },
                }
                checkpoints["records"][identifier] = {
                    "summary_sha256": abstract_hash(row),
                    "source_sha256": source_hash(originals[identifier]),
                    "raw_sha256": raw_hash,
                    "AI": retained[identifier]["AI"],
                }
                retained[identifier].pop("topics", None)
                if topics_enabled(identifier):
                    saved = checkpoints["records"][identifier]
                    saved["topic_provenance"] = topic_provenance
                    topics = validated_topics(row.get("topics"))
                    if topics:
                        retained[identifier]["topics"] = saved["topics"] = topics
            write_json(output / checkpoint_name, checkpoints)

        checkpoint([], None)
        for enabled, items in groupby(work, lambda row: topics_enabled(row["id"])):
            batch = list(items)
            batch_ids = {paper_id(row["id"]) for row in batch}
            options = {"topics_enabled": True} if enabled else {}
            try:
                generated = generate(batch, language, progress=checkpoint, **options)
                if [paper_id(row["id"]) for row in generated] != [
                    paper_id(row["id"]) for row in batch
                ]:
                    raise ValueError("AI generation changed paper IDs or order")
                validate_records(generated)
                checkpoint(generated, None)
            except EnhancementError as error:
                checkpoint(getattr(error, "completed", []), error.record)
                stage.manifest["failures"].append(
                    {"date": day, "error": str(safe_failure(error))}
                )
                break
        completed = [
            row
            for identifier, row in retained.items()
            if identifier in accepted and valid_ai(row.get("AI"))
        ]
        if completed:
            validate_records(completed)
            if digest(raw) != raw_hash:
                raise ValueError("Raw source changed during generation")
            write_jsonl(output / name, completed)
            merge_published(source / name, output / name)
            markdown_name = f"data/{day}_{language}.md"
            stage.track(markdown_name)
            convert(output / name, language=language)
            for row in completed:
                identifier = paper_id(row["id"])
                state["discoveries"][identifier]["languages"][language] = "complete"
                checkpoints["records"].pop(identifier, None)
                stage.manifest["completed_ids"].append(identifier)
        if stage.manifest["failures"]:
            break
    write_json(output / checkpoint_name, checkpoints)
    write_json(output / STATE, state)
    stage.index()
    return stage.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("raw", "ai"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--date")
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--language", choices=LANGUAGES)
    parser.add_argument(
        "--ids", help="Comma-separated post-baseline IDs for limited AI generation"
    )
    args = parser.parse_args()
    if args.kind == "raw":
        if args.ids is not None:
            parser.error("--ids is only valid for AI staging")
        if not args.raw or not args.date or not args.coverage:
            parser.error("Raw staging requires --raw, --date and --coverage")
        report = stage_raw(args.source, args.raw, args.output, args.date, args.coverage)
    else:
        if not args.language:
            parser.error("AI staging requires --language")
        validate_credentials()
        report = stage_language(
            args.source,
            args.output,
            args.language,
            ids=tuple(value.strip() for value in args.ids.split(",") if value.strip())
            if args.ids is not None
            else None,
        )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "files"}, indent=2
        )
    )
    return 1 if report.get("failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())
