"""Publish only approved generated paths to the expected repository data branch."""

import argparse
from pathlib import Path
import re
import subprocess


def allowed_path(name):
    return bool(
        re.fullmatch(
            r"(?:assets/(?:file-list\.txt|researcher-index\.json)|"
            r"data/(?:pipeline-state|notification-state)\.json|"
            r"data/ai-checkpoints/(?:English|Chinese)\.json|"
            r"data/\d{4}-\d{2}-\d{2}(?:_AI_enhanced_(?:English|Chinese))?\.jsonl|"
            r"data/\d{4}-\d{2}-\d{2}_(?:English|Chinese)\.md)",
            name,
        )
    )


class Publisher:
    def __init__(self, source, repository):
        self.source = Path(source).resolve()
        if not repository or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
        ):
            raise ValueError("An explicit GitHub repository is required")
        self.repository = repository

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.source), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def __call__(self, paths):
        paths = sorted(set(paths))
        if not paths or any(not allowed_path(name) for name in paths):
            raise ValueError("Publication contains an unapproved path")
        if any(
            not (self.source / name).is_file()
            or (self.source / name).is_symlink()
            or not (self.source / name).resolve().is_relative_to(self.source)
            for name in paths
        ):
            raise ValueError(
                "Publication must use regular files inside the data checkout"
            )
        remote = self.git("remote", "get-url", "--push", "origin").lower()
        expected = self.repository.lower()
        if remote not in (
            f"https://github.com/{expected}",
            f"https://github.com/{expected}.git",
            f"git@github.com:{expected}.git",
        ):
            raise ValueError("Refusing publication to an unexpected or local origin")
        if self.git("diff", "--cached", "--name-only"):
            raise ValueError("Refusing a checkout with pre-staged changes")
        self.git("fetch", "--no-tags", "origin", "data")
        if self.git("rev-parse", "HEAD") != self.git(
            "rev-parse", "refs/remotes/origin/data"
        ):
            raise ValueError("Remote data changed; preserve this checkout for review")
        self.git("add", "--", *paths)
        if self.git("diff", "--cached", "--name-only"):
            self.git(
                "-c",
                "user.name=github-actions[bot]",
                "-c",
                "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit",
                "-m",
                "data: save validated pipeline progress",
            )
            self.git("push", "origin", "HEAD:data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    Publisher(args.source, args.repository)(args.paths)


if __name__ == "__main__":
    main()
