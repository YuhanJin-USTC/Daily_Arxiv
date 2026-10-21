# Contributing

Use a feature branch and a pull request. Keep code changes on `main` and generated records on `data`; do not mix the two in one commit.

Run the commands under Local development in README before opening a code PR. Dependencies are locked with uv; keep `pyproject.toml` and `uv.lock` in the same change. Tests must use mocks or public saved fixtures, never real API credentials or paid model requests.

Both editions share the same source. Port a change to both repositories with the same tests; the only intentional source difference is the `language` setting. Do not introduce separate English/Chinese provider implementations or daily workflows.

Preserve the invariants: every expected paper is accounted for, partial output is not publishable, provider errors do not become placeholders, and repair/append operations cannot change healthy record bytes. Add a regression test for a changed invariant. Keep helper modules cohesive and prefer the existing atomic storage and quality checks over duplicate implementations.

Never commit `.env`, virtual environments, caches, generated websites, incomplete candidates, or raw model reasoning. Make PR descriptions state the problem, behavior change, and validation. For data PRs, include the source/candidate hashes and affected IDs; verify again against the current `data` branch before merging.
