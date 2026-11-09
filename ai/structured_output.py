"""Bounded, field-preserving recovery of structured model responses.

No network/client setup lives here, so recovery can be tested offline.
"""

import json
import unicodedata
from dataclasses import dataclass

from pydantic import ValidationError
from .errors import safe_failure


DERIVED_PAPER_FIELDS = frozenset({"AI", "AI_status", "topics", "topics_enabled"})

DEFAULT_AI_FIELDS = {
    "tldr": "Summary generation failed",
    "motivation": "Motivation analysis unavailable",
    "method": "Method extraction failed",
    "result": "Result analysis unavailable",
    "conclusion": "Conclusion extraction failed",
}
PLACEHOLDERS = {s.casefold() for s in DEFAULT_AI_FIELDS.values()} | {
    "processing failed",
    "this content has not passed the compliance test and has been hidden.",
}


def valid_fields(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key in DEFAULT_AI_FIELDS
        if isinstance(value.get(key), str)
        and value[key].strip()
        and value[key].strip().casefold() not in PLACEHOLDERS
    }


def missing_fields(value):
    fields = valid_fields(value)
    return tuple(key for key in DEFAULT_AI_FIELDS if key not in fields)


def _topic_terms(value):
    if not isinstance(value, list):
        return None
    terms = {}
    for label in value:
        if (
            not isinstance(label, str)
            or not label.isprintable()
            or any(mark in label for mark in "<>")
        ):
            return None
        label = " ".join(label.split())
        letters = [unicodedata.name(char, "") for char in label if char.isalpha()]
        if (
            not any("LATIN" in name for name in letters)
            or any("LATIN" not in name and "GREEK" not in name for name in letters)
            or label.casefold() in terms
            or label.casefold() in PLACEHOLDERS
        ):
            return None
        terms[label.casefold()] = label
    return terms


def validated_topics(value):
    if not isinstance(value, dict):
        return None
    keywords = _topic_terms(value.get("keywords"))
    subset = _topic_terms(value.get("laser_plasma_keywords"))
    if (
        keywords is None
        or not 3 <= len(keywords) <= 5
        or subset is None
        or not subset.keys() <= keywords.keys()
    ):
        return None
    return {
        "keywords": list(keywords.values()),
        "laser_plasma_keywords": [keywords[key] for key in subset],
    }


def _json_object(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _response_values(value, topics_enabled):
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    fields = valid_fields(value)
    if topics_enabled and isinstance(value, dict):
        topics = validated_topics(value.get("topics"))
        if topics is not None:
            fields["topics"] = topics
    return fields


def _raw_fields(raw, topics_enabled):
    # Accept only the requested tool; never blindly merge arbitrary tool data.
    calls = getattr(raw, "tool_calls", None) or []
    matching = [call for call in calls if call.get("name") == "Structure"]
    if len(matching) == 1:
        return _response_values(_json_object(matching[0].get("args")), topics_enabled)
    if matching:
        return {}
    kwargs = getattr(raw, "additional_kwargs", {}) or {}
    if kwargs.get("refusal"):
        return {}
    functions = [call.get("function", {}) for call in kwargs.get("tool_calls", [])]
    matching = [
        function for function in functions if function.get("name") == "Structure"
    ]
    if len(matching) == 1:
        return _response_values(
            _json_object(matching[0].get("arguments")), topics_enabled
        )
    if not calls and not functions:
        # JSON mode retains the original content when its schema is incomplete.
        return _response_values(
            _json_object(getattr(raw, "content", None)), topics_enabled
        )
    return {}


def response_fields(response, *, topics_enabled=False):
    if isinstance(response, dict) and "raw" in response:
        raw = response["raw"]
        if isinstance(getattr(raw, "content", None), str) and raw.content:
            # A parser may auto-close truncated JSON. Do not accept such invented
            # closure as a complete structured response; validate the raw JSON.
            if not getattr(raw, "tool_calls", None):
                return _raw_fields(raw, topics_enabled)
        # Parsed data is preferred, raw arguments rescue validation failures.
        return {
            **_raw_fields(raw, topics_enabled),
            **_response_values(response.get("parsed"), topics_enabled),
        }
    return _response_values(response, topics_enabled)


@dataclass(frozen=True)
class EnhancementResult:
    fields: dict
    attempts: int
    error_type: str | None = None
    topics: dict | None = None

    @property
    def missing(self):
        return missing_fields(self.fields)

    @property
    def complete(self):
        return not self.missing


def repair_content(summary, language, fields):
    return summary + (
        "\n\nRepair the structured analysis above. Return a JSON object "
        "with all five required fields as non-empty strings in " + language + ". "
        "Copy the retained fields exactly; generate only these missing/invalid "
        "fields: " + ", ".join(missing_fields(fields)) + ". "
        "Use only information supported by the abstract; state limitations "
        "explicitly rather than inventing results. Retained fields (JSON):\n"
        + json.dumps(fields, ensure_ascii=False)
    )


def enhance_fields(
    chain,
    summary,
    language,
    existing=None,
    max_attempts=3,
    *,
    topic_title=None,
    existing_topics=None,
):
    """Keep each accepted field; repair only missing fields, at most twice.

    Transport/authentication errors stop immediately. Exception bodies and raw
    responses are never logged: they may contain provider request information.
    """
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3")
    fields = valid_fields(existing)
    topics_enabled = topic_title is not None and language == "English"
    topics = validated_topics(existing_topics) if topics_enabled else None
    if not missing_fields(fields):
        return EnhancementResult(fields, 0, topics=topics)
    error_type = None
    for attempt in range(1, max_attempts + 1):
        content = summary
        if attempt > 1 or fields:
            content = repair_content(summary, language, fields)
        values = {"language": language, "content": content}
        if topics_enabled:
            values["topic_title"] = topic_title
        try:
            recovered = response_fields(
                chain.invoke(values), topics_enabled=topics_enabled
            )
        except ValidationError as exc:
            # Compatibility with older chains that raise instead of include_raw.
            recovered = {}
            for error in exc.errors(include_url=False, include_context=False):
                recovered.update(_response_values(error.get("input"), topics_enabled))
            error_type = "ValidationError"
        except Exception as exc:
            return EnhancementResult(
                fields, attempt, type(safe_failure(exc)).__name__, topics
            )
        offered_topics = recovered.pop("topics", None)
        if topics is None:
            topics = offered_topics
        for key, value in recovered.items():
            fields.setdefault(key, value)
        if not missing_fields(fields):
            return EnhancementResult(fields, attempt, topics=topics)
        error_type = "IncompleteStructuredOutput"
    return EnhancementResult(fields, max_attempts, error_type, topics)
