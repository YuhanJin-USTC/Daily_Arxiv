"""Bounded, field-preserving recovery of structured model responses.

No network/client setup lives here, so recovery can be tested offline.
"""

import json
from dataclasses import dataclass

from pydantic import ValidationError
from .errors import safe_failure


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


def _raw_fields(raw):
    # Accept only the requested tool; never blindly merge arbitrary tool data.
    calls = getattr(raw, "tool_calls", None) or []
    matching = [call for call in calls if call.get("name") == "Structure"]
    if len(matching) == 1:
        return valid_fields(_json_object(matching[0].get("args")))
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
        return valid_fields(_json_object(matching[0].get("arguments")))
    if not calls and not functions:
        # JSON mode retains the original content when its schema is incomplete.
        return valid_fields(_json_object(getattr(raw, "content", None)))
    return {}


def response_fields(response):
    if isinstance(response, dict) and "raw" in response:
        raw = response["raw"]
        if isinstance(getattr(raw, "content", None), str) and raw.content:
            # A parser may auto-close truncated JSON. Do not accept such invented
            # closure as a complete structured response; validate the raw JSON.
            if not getattr(raw, "tool_calls", None):
                return _raw_fields(raw)
        # Parsed data is preferred, raw arguments rescue validation failures.
        return {**_raw_fields(response["raw"]), **valid_fields(response.get("parsed"))}
    return valid_fields(response)


@dataclass(frozen=True)
class EnhancementResult:
    fields: dict
    attempts: int
    error_type: str | None = None

    @property
    def missing(self):
        return missing_fields(self.fields)

    @property
    def complete(self):
        return not self.missing


def enhance_fields(chain, summary, language, existing=None, max_attempts=3):
    """Keep each accepted field; repair only missing fields, at most twice.

    Transport/authentication errors stop immediately. Exception bodies and raw
    responses are never logged: they may contain provider request information.
    """
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3")
    fields = valid_fields(existing)
    if not missing_fields(fields):
        return EnhancementResult(fields, 0)
    error_type = None
    for attempt in range(1, max_attempts + 1):
        content = summary
        if attempt > 1 or fields:
            content += (
                "\n\nRepair the structured analysis above. Return a JSON object "
                "with all five required fields as non-empty strings in "
                + language
                + ". "
                "Copy the retained fields exactly; generate only these missing/invalid "
                "fields: " + ", ".join(missing_fields(fields)) + ". "
                "Use only information supported by the abstract; state limitations "
                "explicitly rather than inventing results. Retained fields (JSON):\n"
                + json.dumps(fields, ensure_ascii=False)
            )
        try:
            recovered = response_fields(
                chain.invoke({"language": language, "content": content})
            )
        except ValidationError as exc:
            # Compatibility with older chains that raise instead of include_raw.
            recovered = {}
            for error in exc.errors(include_url=False, include_context=False):
                recovered.update(valid_fields(error.get("input")))
            error_type = "ValidationError"
        except Exception as exc:
            return EnhancementResult(fields, attempt, type(safe_failure(exc)).__name__)
        for key, value in recovered.items():
            fields.setdefault(key, value)
        if not missing_fields(fields):
            return EnhancementResult(fields, attempt)
        error_type = "IncompleteStructuredOutput"
    return EnhancementResult(fields, max_attempts, error_type)
