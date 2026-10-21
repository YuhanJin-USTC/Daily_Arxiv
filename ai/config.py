"""One public configuration for both language editions; credentials stay in env."""

import os
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def settings():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "tool"
    ]["daily_arxiv"]
    if config["language"] not in ("English", "Chinese"):
        raise ValueError("Unsupported project language")
    return config


def validate_credentials():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key or any(char.isspace() for char in key):
        raise ValueError("OPENAI_API_KEY is missing or malformed; values suppressed")


def subscribed_categories():
    supplied = os.environ.get("CATEGORIES", "").strip()
    values = supplied.split(",") if supplied else settings()["categories"]
    categories = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    if not categories or any(
        not re.fullmatch(r"[A-Za-z][A-Za-z.-]+", category) for category in categories
    ):
        raise ValueError("CATEGORIES must contain arXiv category names")
    return categories
