# Contributing

Create a `codex/` feature branch from `main`, open a pull request, and merge after review and required checks pass. Keep source changes on `main` and generated records on `data`; do not mix the two in one commit. Local configuration edits take effect on the hosted pipeline only after the commit reaches GitHub `main`.

After merging, confirm that the branch contains no unmerged work before considering cleanup. Deleting remote or local branches requires the user's explicit approval or an explicitly approved repository setting. Do not assume automatic branch deletion is enabled; preserve `main`, `data` and any branch with unmerged work.

Prepare dependencies with `uv sync --frozen`, then run `bash scripts/check.sh` before opening a code PR. Install the tools listed under Local development in README separately; the check script never installs or downloads them. Dependencies are locked with uv; keep dependency changes in `pyproject.toml` and `uv.lock` together. Tests must use mocks or public saved fixtures, never real API credentials or paid model requests.

Maintain this repository only; the legacy repositories are read-only migration sources. Language is an explicit generation/recovery argument. Do not introduce separate English/Chinese provider implementations or crawlers. Shared raw metadata defines the paper set, and a baseline excludes historical gaps from automatic generation.

Preserve the invariants: every expected paper is accounted for, partial output is not publishable, provider errors do not become placeholders, and repair/append operations cannot change healthy record bytes. Add a regression test for a changed invariant. Keep helper modules cohesive and prefer the existing atomic storage and quality checks over duplicate implementations.

Never commit `.env`, virtual environments, caches, generated websites, incomplete candidates, or raw model reasoning. Make PR descriptions state the problem, behavior change, and validation. For data PRs, include the source/candidate hashes and affected IDs; verify again against the current `data` branch before merging.

All data writers share Actions concurrency group `arxiv-data` and verify current remote HEAD before publication. Raw metadata, frozen notification eligibility and index updates belong to the same commit. SMTP sending state must be durable before transport; ambiguous outcomes require manual evidence, never blind retry. Keep repository identities at build time and mail settings out of public website bundles.

Keep local and CI validation in `scripts/check.sh`: lockfile, Python/Ruff, Node, shell syntax, site-build tests, active workflow YAML and diff whitespace. Add public static files to the allowlist in `scripts/build_site.py`; use that build for authenticated previews instead of rewriting source authentication settings. For UI changes, check 1440/768/390 widths, keyboard controls and a Pages subpath. For migration changes, prove raw union/order and byte-preserved AI/Markdown against immutable snapshots. Do not turn placeholder or partial AI fields into completed output to make tests pass.
