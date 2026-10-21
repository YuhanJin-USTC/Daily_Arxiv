"""Generate complete summaries, keeping failures separate from publishable output."""

import argparse
import copy
import os
from pathlib import Path
import re
import sys

import requests

from .config import settings, validate_credentials
from .deepseek import DeepSeekSummaryChain
from .errors import AuthenticationFailure, EnhancementError, safe_failure
from .quality import index_records, read_records, validate_records
from .storage import digest, write_json, write_jsonl
from .structured_output import enhance_fields
from .structured_output import valid_fields


def is_sensitive(content):
    try:
        response = requests.post(
            "https://spam.dw-dengwei.workers.dev", json={"text": content}, timeout=5
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or type(result.get("sensitive")) is not bool:
            raise ValueError("Invalid moderation response")
        return result["sensitive"]
    except Exception:
        # Unavailability is not a positive moderation decision and must not erase rows.
        raise EnhancementError(
            "Content-check service failed; publication blocked."
        ) from None


def check_github_code(content):
    match = re.search(
        r"https?://github\.com/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_.-]+)", content
    )
    if match:
        owner, repo = match.groups()
        repo = repo.rstrip(".,)").removesuffix(".git")
        result = {"code_url": f"https://github.com/{owner}/{repo}"}
        headers = {"Accept": "application/vnd.github.v3+json"}
        token = os.environ.get("TOKEN_GITHUB")
        if token:
            headers["Authorization"] = f"token {token}"
        try:
            response = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers,
                timeout=5,
            )
            if response.status_code == 200:
                data = response.json()
                result.update(
                    code_stars=data.get("stargazers_count", 0),
                    code_last_update=data.get("pushed_at", "")[:10],
                )
        except Exception:
            pass  # Optional repository metadata does not affect summary quality.
        return result
    match = re.search(
        r"https?://[a-zA-Z0-9_-]+\.github\.io(?:/[a-zA-Z0-9_.-]+)*", content
    )
    return {"code_url": match.group(0).rstrip(".,)")} if match else {}


def process_single_item(chain, item, language):
    item = copy.deepcopy(item)
    if is_sensitive(item.get("summary", "")):
        raise EnhancementError(
            "Content check rejected a paper; manual review required.", item
        )
    item.update(check_github_code(item.get("summary", "")))
    outcome = enhance_fields(chain, item["summary"], language, existing=item.get("AI"))
    item["AI"] = outcome.fields
    if not outcome.complete:
        item["AI_status"] = {
            "status": "incomplete",
            "missing_fields": list(outcome.missing),
            "attempts": outcome.attempts,
            "error_type": outcome.error_type,
        }
        error = (
            AuthenticationFailure
            if outcome.error_type == "AuthenticationFailure"
            else EnhancementError
        )
        raise error(
            "AI incomplete: "
            + ", ".join(outcome.missing)
            + "; "
            + str(outcome.error_type),
            item,
        )
    item.pop("AI_status", None)
    try:
        if any(is_sensitive(value) for value in item["AI"].values()):
            raise EnhancementError("Generated content needs manual review.", item)
    except EnhancementError as error:
        error.record = item
        raise
    return item


def process_all_items(data, language, chain=None, progress=None):
    """Sequential requests stop on the first error; no queued batch after 401."""
    if not data:
        raise EnhancementError("Empty input; publication blocked.")
    owned = chain is None
    chain = chain or DeepSeekSummaryChain()
    completed = []
    try:
        for item in data:
            try:
                completed.append(process_single_item(chain, item, language))
            except Exception as error:
                safe = safe_failure(error)
                safe.completed = completed
                if safe.record is None:
                    safe.record = copy.deepcopy(item)
                if progress is not None:
                    progress(completed, safe.record)
                raise safe from None
            if progress is not None:
                progress(completed, None)
        validate_records(completed)
        return completed
    finally:
        if owned:
            chain.close()


def resume_rows(rows, checkpoint_path, source_hash, language):
    import json

    checkpoint = json.loads(checkpoint_path.read_text())
    if (
        checkpoint.get("source_sha256") != source_hash
        or checkpoint.get("language") != language
    ):
        raise ValueError("Checkpoint belongs to another input or language")
    saved = list(checkpoint.get("completed", []))
    saved.extend(checkpoint.get("pending", []))
    if checkpoint.get("partial"):
        saved.append(checkpoint["partial"])
    by_id = index_records(saved)
    if not by_id.keys() <= {row["id"] for row in rows}:
        raise ValueError("Checkpoint contains unknown paper IDs")
    result = copy.deepcopy(rows)
    for row in result:
        if row["id"] in by_id:
            if by_id[row["id"]].get("summary") != row.get("summary"):
                raise ValueError("Checkpoint abstract differs from the raw snapshot")
            row["AI"] = {
                **valid_fields(by_id[row["id"]].get("AI")),
                **valid_fields(row.get("AI")),
            }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument(
        "--resume", type=Path, help="Reuse a partial checkpoint for this exact raw file"
    )
    args = parser.parse_args(argv)
    if not args.check_config and args.data is None:
        parser.error("--data is required")
    source = args.data
    try:
        if not os.environ.get("GITHUB_ACTIONS"):
            from dotenv import load_dotenv

            load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
        validate_credentials()
        language = settings()["language"]
        if args.check_config:
            print(
                "Configuration format checks passed; credentials were not tested or displayed."
            )
            return 0
        if source.suffix != ".jsonl" or "_AI_enhanced_" in source.stem:
            raise ValueError("Expected raw JSONL input")
        target = args.output or source.with_name(
            f"{source.stem}_AI_enhanced_{language}.jsonl"
        )
        if target.resolve() == source.resolve():
            raise ValueError("Input and output must differ")
        source_hash = digest(source)
        data = list(
            index_records(
                read_records(source), allow_identical_duplicates=True
            ).values()
        )
        if args.resume:
            data = resume_rows(data, args.resume, source_hash, language)
        try:
            result = process_all_items(data, language)
        except EnhancementError as error:
            # A checkpoint is not publishable output; the previous target survives.
            write_json(
                target.with_suffix(".partial.json"),
                {
                    "source_sha256": source_hash,
                    "language": language,
                    "completed": getattr(error, "completed", []),
                    "partial": error.record,
                },
            )
            raise
        if digest(source) != source_hash:
            raise ValueError("Source changed during generation")
        validate_records(result)
        write_jsonl(target, result)
        return 0
    except Exception as error:
        print(str(safe_failure(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
