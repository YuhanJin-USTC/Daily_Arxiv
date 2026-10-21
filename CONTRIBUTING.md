# Contributing

Use a feature branch and a pull request. Keep code changes on `main` and generated records on `data`; do not mix the two in one commit.

Run the commands under Local development in README before opening a code PR. Dependencies are locked with uv; keep `pyproject.toml` and `uv.lock` in the same change. Tests must use mocks or public saved fixtures, never real API credentials or paid model requests.

Maintain this repository only; the legacy repositories are read-only migration sources. Language is an explicit generation/recovery argument. Do not introduce separate English/Chinese provider implementations or crawlers. Shared raw metadata defines the paper set, and a baseline excludes historical gaps from automatic generation.

Preserve the invariants: every expected paper is accounted for, partial output is not publishable, provider errors do not become placeholders, and repair/append operations cannot change healthy record bytes. Add a regression test for a changed invariant. Keep helper modules cohesive and prefer the existing atomic storage and quality checks over duplicate implementations.

Never commit `.env`, virtual environments, caches, generated websites, incomplete candidates, or raw model reasoning. Make PR descriptions state the problem, behavior change, and validation. For data PRs, include the source/candidate hashes and affected IDs; verify again against the current `data` branch before merging.

All data writers share Actions concurrency group `arxiv-data` and verify current remote HEAD before publication. Raw metadata, frozen notification eligibility and index updates belong to the same commit. SMTP sending state must be durable before transport; ambiguous outcomes require manual evidence, never blind retry. Keep repository identities at build time and mail settings out of public website bundles.

Validate Python/Ruff, Node, shell syntax, static builds and changed workflow YAML. Use mocks for model and SMTP services. For UI changes, check 1440/768/390 widths, keyboard controls and a Pages subpath. For migration changes, prove raw union/order and byte-preserved AI/Markdown against immutable snapshots. Do not turn placeholder or partial AI fields into completed output to make tests pass.
