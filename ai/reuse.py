"""Reuse complete archived summaries for identical abstracts and language."""

import hashlib
import json
import re

from .quality import FIELDS, read_records, valid_ai
from .storage import digest
from .structured_output import valid_fields


def summary_key(row, language):
    identifier = re.sub(
        r"v\d+$", "", re.sub(r"^https?://arxiv.org/abs/", "", row["id"])
    )
    summary = row.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("A reusable summary needs its original abstract")
    return identifier, hashlib.sha256(summary.encode("utf-8")).hexdigest(), language


class SuccessfulSummaries:
    def __init__(self, source, targets, language):
        self.language = language
        self.keys = {summary_key(row, language) for row in targets}
        self.records = {}
        self.source_hashes = {}
        if source is not None:
            if not source.is_dir():
                raise ValueError("Successful-summary source is not a directory")
            for path in sorted(source.glob(f"*_AI_enhanced_{language}.jsonl")):
                self.source_hashes[path.name] = digest(path)
                for row in read_records(path):
                    if valid_ai(row.get("AI")):
                        self.add(row, path.name)

    def add(self, row, source):
        if not isinstance(row.get("summary"), str) or not row["summary"].strip():
            return
        key = summary_key(row, self.language)
        if key in self.keys and valid_ai(row.get("AI")):
            self.records.setdefault(key, []).append((dict(row["AI"]), source))

    def fields(self, row):
        retained = valid_fields(row.get("AI"))
        candidates = self.records.get(summary_key(row, self.language), [])
        reused = {}
        for field in FIELDS:
            if field in retained:
                continue
            values = {fields[field] for fields, _ in candidates}
            if len(values) > 1:
                raise ValueError(
                    "Conflicting successful summaries for a requested field"
                )
            if values:
                reused[field] = values.pop()
        return reused, [
            {"file": source, "sha256": self.source_hashes.get(source)}
            for source in sorted({source for _, source in candidates})
        ] if reused else []


def generation_provenance(config=None, *, topics_enabled=False):
    from pathlib import Path

    from .config import settings

    if config is None:
        config = settings()
    root = Path(__file__).resolve().parent
    provenance = {
        "profile": config["deepseek"],
        "prompt_sha256": {
            name: digest(root / name)
            for name in ("system.txt", "template.txt", "structure.py")
        },
    }
    if topics_enabled:
        from .deepseek import summary_messages
        from .structured_output import repair_content

        system = (root / "system.txt").read_text(encoding="utf-8")
        template = (root / "template.txt").read_text(encoding="utf-8")
        abstract = "{abstract}"
        contents = (abstract, repair_content(abstract, "English", {"tldr": "{tldr}"}))
        messages = [
            summary_messages(
                system,
                template,
                {
                    "language": "English",
                    "content": content,
                    "topic_title": "{title}",
                },
            )
            for content in contents
        ]
        provenance["prompt_sha256"]["english_topics"] = hashlib.sha256(
            json.dumps(messages, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
    return provenance
