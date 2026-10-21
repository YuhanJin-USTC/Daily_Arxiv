"""Build a deterministic bilingual candidate from immutable source snapshots."""

import argparse
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "daily_arxiv"))
from ai.quality import valid_ai
from ai.storage import digest, write_bytes, write_json
from daily_arxiv.history import paper_id

LANGUAGES = ("Chinese", "English")
RAW = re.compile(r"\d{4}-\d{2}-\d{2}\.jsonl")


def sha(content):
    return hashlib.sha256(content).hexdigest()


def snapshot(repository, commit, output):
    """Read git objects without changing source refs or worktrees."""
    if output.exists():
        raise ValueError("Snapshot directory must be new")
    resolved = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", commit + "^{commit}"], text=True
    ).strip()
    archive = subprocess.check_output(
        [
            "git",
            "-C",
            str(repository),
            "archive",
            resolved,
            "data",
            "assets/file-list.txt",
        ]
    )
    output.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            target = output / member.name
            if not target.resolve().is_relative_to(output.resolve()) or not (
                member.isfile() or member.isdir()
            ):
                raise ValueError("Unsafe snapshot member")
            if member.isfile():
                write_bytes(target, tar.extractfile(member).read())
    write_json(
        output / "SOURCE.json", {"repository": str(repository), "commit": resolved}
    )
    return output


def records(content):
    return [json.loads(line) for line in content.splitlines() if line.strip()]


def metadata(row):
    return {**row, "id": paper_id(row["id"])}


def migrate(chinese, english, output):
    if output.exists():
        raise ValueError("Candidate directory must be new")
    sources = dict(zip(LANGUAGES, (Path(chinese), Path(english))))
    if any(
        output.resolve().is_relative_to(path.resolve()) for path in sources.values()
    ):
        raise ValueError("Candidate must be outside source snapshots")
    manifest = {
        "version": 1,
        "complete": False,
        "sources": {},
        "days": {},
        "conflicts": [],
        "targets": {},
    }
    payloads, raw_days, baseline = {}, {}, set()
    enhanced, enhanced_rows = {}, {}
    for language, source in sources.items():
        origin = (
            json.loads((source / "SOURCE.json").read_text())
            if (source / "SOURCE.json").exists()
            else {"repository": str(source), "commit": None}
        )
        files = {}
        for path in sorted((source / "data").iterdir()):
            if path.is_file():
                files["data/" + path.name] = digest(path)
        index = source / "assets/file-list.txt"
        if index.exists():
            files["assets/file-list.txt"] = digest(index)
        manifest["sources"][language] = {**origin, "files": files, "preserved": {}}
        for path in sorted((source / "data").glob("*.jsonl")):
            content = path.read_bytes()
            if RAW.fullmatch(path.name):
                day = date.fromisoformat(path.stem).isoformat()
                by_id = raw_days.setdefault(day, {})
                for row in records(content):
                    identifier = paper_id(row["id"])
                    baseline.add(identifier)
                    normalized = metadata(row)
                    if identifier in by_id and by_id[identifier] != normalized:
                        manifest["conflicts"].append(
                            {
                                "kind": "raw_metadata",
                                "date": day,
                                "id": identifier,
                                "source": language,
                                "before": by_id[identifier],
                                "incoming": normalized,
                            }
                        )
                    else:
                        by_id.setdefault(identifier, normalized)
            elif match := re.fullmatch(
                r"(\d{4}-\d{2}-\d{2})_AI_enhanced_(English|Chinese)\.jsonl", path.name
            ):
                day, edition = match.groups()
                key = "data/" + path.name
                if key in payloads and payloads[key] != content:
                    manifest["conflicts"].append(
                        {"kind": "language_file", "file": path.name, "source": language}
                    )
                payloads.setdefault(key, content)
                manifest["sources"][language]["preserved"]["data/" + path.name] = key
                seen = {}
                for row in records(content):
                    identifier = paper_id(row["id"])
                    baseline.add(identifier)
                    prior = seen.get(identifier)
                    if prior is not None and metadata(prior) != metadata(row):
                        manifest["conflicts"].append(
                            {
                                "kind": "language_record",
                                "file": path.name,
                                "id": identifier,
                                "before": prior,
                                "incoming": row,
                            }
                        )
                    seen[identifier] = row
                    enhanced_rows.setdefault((day, edition), []).append(row)
                    if valid_ai(row.get("AI")):
                        enhanced.setdefault((day, edition), set()).add(identifier)
            else:
                key = "data/" + path.name
                if key in payloads and payloads[key] != content:
                    manifest["conflicts"].append(
                        {
                            "kind": "unknown_jsonl",
                            "file": path.name,
                            "source": language,
                            "before_sha256": sha(payloads[key]),
                            "incoming_sha256": sha(content),
                        }
                    )
                payloads.setdefault(key, content)
                manifest["sources"][language]["preserved"][key] = key
        for path in sorted((source / "data").glob("*.md")):
            name = path.name
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", name):
                name = f"{path.stem}_{language}.md"
            key, content = "data/" + name, path.read_bytes()
            if key in payloads and payloads[key] != content:
                manifest["conflicts"].append(
                    {"kind": "markdown", "file": name, "source": language}
                )
            payloads.setdefault(key, content)
            manifest["sources"][language]["preserved"]["data/" + path.name] = key
    for language, source in sources.items():
        for name, expected in manifest["sources"][language]["files"].items():
            if digest(source / name) != expected:
                raise ValueError("Source snapshot changed during migration")
    for (day, language), rows in enhanced_rows.items():
        originals = raw_days.get(day, {})
        missing = {paper_id(row["id"]) for row in rows} - originals.keys()
        if missing:
            manifest["conflicts"].append(
                {
                    "kind": "ai_without_raw",
                    "date": day,
                    "language": language,
                    "ids": sorted(missing),
                }
            )
        for row in rows:
            identifier = paper_id(row["id"])
            if (
                identifier in originals
                and valid_ai(row.get("AI"))
                and row.get("summary") != originals[identifier].get("summary")
            ):
                manifest["conflicts"].append(
                    {
                        "kind": "ai_abstract",
                        "date": day,
                        "language": language,
                        "id": identifier,
                        "raw_summary": originals[identifier].get("summary"),
                        "ai_summary": row.get("summary"),
                    }
                )
    for day, rows in raw_days.items():
        payloads[f"data/{day}.jsonl"] = b"".join(
            (json.dumps(row, ensure_ascii=False) + "\n").encode()
            for row in rows.values()
        )
        manifest["days"][day] = {
            "raw_count": len(rows),
            "languages": {
                language: {
                    "available": len(enhanced.get((day, language), set())),
                    "missing_ids": sorted(
                        rows.keys() - enhanced.get((day, language), set())
                    ),
                }
                for language in LANGUAGES
            },
        }
    output.mkdir(parents=True)
    if manifest["conflicts"]:
        write_json(output / "migration-manifest.json", manifest)
        raise ValueError(
            f"{len(manifest['conflicts'])} migration conflicts; inspect migration-manifest.json"
        )
    state = {"version": 1, "historical_ids": sorted(baseline), "discoveries": {}}
    payloads["data/pipeline-state.json"] = (
        json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    names = sorted(
        Path(name).name
        for name in payloads
        if name.startswith("data/") and name.endswith(".jsonl")
    )
    payloads["assets/file-list.txt"] = ("\n".join(names) + "\n").encode()
    for name, content in sorted(payloads.items()):
        write_bytes(output / name, content)
        manifest["targets"][name] = sha(content)
    manifest["complete"] = True
    manifest["summary"] = {
        "raw_days": len(raw_days),
        "unique_ids": len(baseline),
        "raw_rows": sum(len(rows) for rows in raw_days.values()),
        "healthy_by_language": {
            language: sum(
                len(ids)
                for (day, edition), ids in enhanced.items()
                if edition == language
            )
            for language in LANGUAGES
        },
        "markdown_files": sum(name.endswith(".md") for name in payloads),
    }
    write_json(output / "migration-manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chinese", type=Path, required=True)
    parser.add_argument("--english", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chinese-commit")
    parser.add_argument("--english-commit")
    parser.add_argument("--snapshots", type=Path)
    args = parser.parse_args()
    if args.chinese_commit or args.english_commit:
        if not args.snapshots or not args.chinese_commit or not args.english_commit:
            parser.error("Both commits and a new snapshots directory are required")
        args.chinese = snapshot(
            args.chinese, args.chinese_commit, args.snapshots / "Chinese"
        )
        args.english = snapshot(
            args.english, args.english_commit, args.snapshots / "English"
        )
    report = migrate(args.chinese, args.english, args.output)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
