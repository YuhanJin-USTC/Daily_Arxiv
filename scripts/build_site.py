"""Build static Pages assets; never commit generated configuration to main."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "daily_arxiv"))
from ai.config import settings, subscribed_categories
from daily_arxiv.researchers import config_digest

STATIC_FILES = (
    "index.html",
    "login.html",
    "settings.html",
    "statistic.html",
    "assets/logo2-removebg-preview.png",
    "css/settings.css",
    "css/statistic.css",
    "css/styles.css",
    "js/app.js",
    "js/auth-config.js",
    "js/auth.js",
    "js/data-config.js",
    "js/login.js",
    "js/papers.js",
    "js/settings.js",
    "js/statistic.js",
)


def build(output, repository, data_base_url=""):
    if output.exists():
        raise ValueError("Site output must be a new directory")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected owner/repository")
    output.mkdir(parents=True)
    for name in STATIC_FILES:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    config = settings()
    language = config["language"]
    categories = subscribed_categories()
    owner, name = repository.split("/")
    script = (ROOT / "js/data-config.js").read_text()
    for key, value in {
        "__OWNER__": owner,
        "__REPOSITORY__": name,
        "__LANGUAGE__": language,
        "__CATEGORIES__": categories,
        "__LANGUAGES__": config.get("languages", ["English", "Chinese"]),
        "__NAMESPACE__": "daily-arxiv:" + repository.lower(),
        "__RESEARCHERS_DIGEST__": config_digest(
            config.get("researchers", []), categories
        ),
        "__DATA_BASE_URL__": data_base_url,
    }.items():
        script = script.replace(json.dumps(key), json.dumps(value))
    (output / "js/data-config.js").write_text(script)
    papers = output / "js/papers.js"
    papers.write_text(
        papers.read_text().replace(
            json.dumps("__DEFAULT_CATEGORIES__"), json.dumps(categories)
        )
    )
    password = os.environ.get("ACCESS_PASSWORD", "")
    password_hash = (
        hashlib.sha256(password.encode()).hexdigest()
        if password
        else "DISABLED_NO_PASSWORD_SET_IN_SECRETS"
    )
    auth = (ROOT / "js/auth-config.js").read_text()
    auth = re.sub(
        r"passwordHash:\s*'[^']*'", "passwordHash: '" + password_hash + "'", auth
    )
    namespace = "arxiv_auth:" + repository.lower()
    for key, suffix in (("storageKey", "token"), ("storageExpireKey", "expire")):
        auth = re.sub(
            rf"(?m)^    {key}:.*$",
            f"    {key}: {json.dumps(namespace + ':' + suffix)},",
            auth,
        )
    (output / "js/auth-config.js").write_text(auth)
    versions = {
        path.relative_to(output).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()[:16]
        for path in (output / "js").glob("*.js")
    }
    for page in output.glob("*.html"):
        content = page.read_text()
        content = re.sub(
            r'(src=")(js/[^"?]+\.js)(?:\?[^\"]*)?(")',
            lambda match: match[1] + match[2] + "?v=" + versions[match[2]] + match[3],
            content,
        )
        content = re.sub(
            r"https://github.com/yuhanjin-ustc/daily-arXiv-ai-enhanced(?:-chinese)?",
            "https://github.com/" + repository,
            content,
            flags=re.IGNORECASE,
        )
        page.write_text(content)
    (output / ".nojekyll").touch()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-base-url", default="", help="Local preview data URL")
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY"),
        required=not os.environ.get("GITHUB_REPOSITORY"),
    )
    args = parser.parse_args()
    build(args.output, args.repository, args.data_base_url)


if __name__ == "__main__":
    main()
