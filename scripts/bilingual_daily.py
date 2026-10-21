"""Stage validated raw discoveries and independent, resumable language results."""

import argparse
import copy
from datetime import date
import hashlib
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
from ai.structured_output import valid_fields
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
        if "AI" in row or "AI_status" in row:
            raise ValueError("Raw discovery contains AI fields")
        if identifier in known:
            continue
        row = {**row, "id": identifier}
        state["discoveries"][identifier] = {
            "date": day,
            "summary_sha256": abstract_hash(row),
            "source_sha256": source_hash(row),
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
    if selected is not None:
        verified_days = {}
        for identifier in sorted(selected):
            entry = state["discoveries"][identifier]
            day = entry["date"]
            if day not in verified_days:
                raw = source / "data" / f"{day}.jsonl"
                if not raw.is_file():
                    raise ValueError("Selected discovery has no raw source")
                originals = {paper_id(row["id"]): row for row in read_records(raw)}
                enhanced = source / "data" / f"{day}_AI_enhanced_{language}.jsonl"
                published = (
                    {paper_id(row["id"]): row for row in read_records(enhanced)}
                    if enhanced.exists()
                    else {}
                )
                verified_days[day] = originals, published
            originals, published = verified_days[day]
            row = originals.get(identifier)
            if (
                row is None
                or abstract_hash(row) != entry["summary_sha256"]
                or source_hash(row) != entry.get("source_sha256")
            ):
                raise ValueError("Selected discovery raw source or abstract changed")
            saved = checkpoints["records"].get(identifier)
            if saved and (
                saved.get("summary_sha256") != abstract_hash(row)
                or saved.get("source_sha256") != source_hash(row)
            ):
                raise ValueError("Selected checkpoint source or abstract changed")
            if entry["languages"][language] == "complete":
                existing = published.get(identifier, {})
                if (
                    not valid_ai(existing.get("AI"))
                    or existing.get("summary") != row["summary"]
                ):
                    raise ValueError("Selected completed language is absent or invalid")
    groups = {}
    for identifier, entry in state["discoveries"].items():
        if entry["languages"][language] == "pending" and (
            selected is None or identifier in selected
        ):
            groups.setdefault(entry["date"], []).append(identifier)
    stage.manifest.update(completed_ids=[], failures=[])
    for day, ids in sorted(groups.items()):
        raw = source / "data" / f"{day}.jsonl"
        raw_hash = digest(raw)
        originals = {paper_id(row["id"]): row for row in read_records(raw)}
        name = f"data/{day}_AI_enhanced_{language}.jsonl"
        stage.track(name)
        existing = read_records(source / name) if (source / name).exists() else []
        if existing:
            validate_records(existing)
        published = {paper_id(row["id"]): row for row in existing}
        work = []
        for identifier in ids:
            row = copy.deepcopy(originals[identifier])
            discovery = state["discoveries"][identifier]
            if abstract_hash(row) != discovery["summary_sha256"] or (
                discovery.get("source_sha256") is not None
                and source_hash(row) != discovery["source_sha256"]
            ):
                raise ValueError("Discovery source or abstract changed")
            if identifier in published:
                if (
                    not valid_ai(published[identifier].get("AI"))
                    or published[identifier].get("summary") != row["summary"]
                ):
                    raise ValueError("Published language row needs explicit recovery")
                state["discoveries"][identifier]["languages"][language] = "complete"
                checkpoints["records"].pop(identifier, None)
                continue
            binding = {
                "summary_sha256": abstract_hash(row),
                "source_sha256": source_hash(originals[identifier]),
            }
            saved = checkpoints["records"].get(identifier)
            if saved:
                if any(saved.get(key) != value for key, value in binding.items()):
                    raise ValueError(
                        "Checkpoint abstract or source changed; explicit recovery required"
                    )
                row["AI"] = valid_fields(saved.get("AI"))
            work.append(row)
        retained = {paper_id(row["id"]): row for row in work}
        accepted = set()

        def checkpoint(completed, partial):
            accepted.update(paper_id(row["id"]) for row in completed)
            for row in [*completed, *([partial] if partial else [])]:
                identifier = paper_id(row["id"])
                if identifier not in retained or row.get("summary") != originals[
                    identifier
                ].get("summary"):
                    raise ValueError("Generated identity or abstract changed")
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
            write_json(output / checkpoint_name, checkpoints)

        if work:
            checkpoint([], None)
            try:
                generated = generate(work, language, progress=checkpoint)
                if [paper_id(row["id"]) for row in generated] != [
                    paper_id(row["id"]) for row in work
                ]:
                    raise ValueError("AI generation changed paper IDs or order")
                validate_records(generated)
                checkpoint(generated, None)
            except EnhancementError as error:
                checkpoint(getattr(error, "completed", []), error.record)
                stage.manifest["failures"].append(
                    {"date": day, "error": str(safe_failure(error))}
                )
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
