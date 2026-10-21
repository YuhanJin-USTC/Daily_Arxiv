"""One public configuration for both language editions; credentials stay in env."""

import os
from pathlib import Path
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
