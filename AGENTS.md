# Daily-Arxiv maintenance

## Scope and layout

- Maintain this single bilingual repository. Legacy Chinese/English repositories are read-only sources; do not synchronize code changes back to them.
- Source lives on `main`; generated raw/AI/Markdown, pipeline state, notification state and public indexes live on `data`. Never mix generated data into source commits.
- Public settings belong only in `[tool.daily_arxiv]` in `pyproject.toml`. Preserve the existing model profile and moderation/quality checks unless separately requested.
- `ai/` owns model access, quality, provenance and recovery; `daily_arxiv/daily_arxiv/` owns crawl/history, researcher matching and notification semantics; `scripts/` owns staging/application/publication/build; `to_md/` owns rendering; `js/`, `css/` and HTML own the static reader.
- Use one implementation with explicit English/Chinese arguments. Do not add a frontend framework, service or database for these features.

## Data and delivery invariants

- Validate raw coverage once. Raw normalized IDs define the paper set; each language may be complete or pending independently. Never hide raw papers because AI is absent.
- Preserve migration baselines: historical gaps never enter automatic AI or email backfill. Post-baseline language work must continue on runs with no new papers.
- Retain healthy JSONL bytes, accepted partial fields, full LICENSE and original attribution. Conflicting raw metadata/healthy same-language content stops migration for user review. Use new candidate directories and exact source/candidate hashes.
- AI reuse binds ID, exact abstract/source, language, model and prompt. Incompatible checkpoints must fail explicitly before paid requests. Markdown uses `DATE_English.md` and `DATE_Chinese.md`; never implicitly convert legacy shared Markdown targets.
- Researcher matches come from the backend module only. Reliable full names/confirmed aliases may enqueue mail; suspected names never do. Index digests bind researchers and effective categories. Escape all dynamic frontend text.
- Freeze raw discovery, researcher evidence and recipient cohort together before publication. Stable recipient ID plus normalized paper ID deduplicates mail. Persist/push sending state before SMTP; uncertain or interrupted delivery requires manual evidence and resolution, not automatic resend.
- Release probes are explicit manual checks: one source-bound post-baseline paper for AI, and one durable infrastructure email distinct from paper notifications. Never reinterpret historical gaps as new discoveries to satisfy a live test. Preserve release_probes alongside ordinary delivery state.
- Diagnose SMTP connection/auth failures with the manual auth-only check before another send. Keep diagnostics allowlisted; never record server response text, credentials or authentication payloads.
- All data workflows share `concurrency.group: arxiv-data`, `cancel-in-progress: false`; verify remote data HEAD before writes. Never force-push to recover a conflict. Configuration refresh updates highlights only, never historic mail.
- Keep mail recipients/SMTP configuration out of site bundles; credentials only in Secrets/environment. Do not infer authentication from recipient addresses. Preserve repository-specific authentication and Pages subpaths.

## Checks and handoff

- Read nearby files first; match existing organization, concise English comments and tests. Run Ruff check/format, Python unittest, Node tests, shell syntax, workflow validation and relevant builds. Services must be mocked in tests.
- For UI changes, inspect 1440/768/390 widths, keyboard selection, fast toggling, range/filter/detail state, stats deduplication and missing-language fallback. State clearly when browser inspection is unavailable.
- Dependency changes require a matching `uv.lock`; do not silently substitute unlocked tests for locked validation.
- Keep one-time evidence in ignored `artifacts/upgrade/STATE.md`; do not commit credentials, caches, previews, checkpoints or personal work logs to source. Before resuming a large upgrade, read that state and necessary diffs.
- Follow the user's deletion rules. Never discard pre-existing changes. Remove only your own temporary outputs when obsolete, marking cleanup with `CODEX_TEMP_CLEANUP=1` and exact paths.
- Confirm Git remotes before publication. The legacy local source may be retained as `source-chinese`; never push there. `origin` must identify the authorized target GitHub repository. New GitHub repo creation/push/deployment, real SMTP/paid model calls and old-site changes need separate explicit release authorization. Activation variables are disabled by absence.
- Preserve old sites, branches and migration snapshots until the user explicitly approves any specific deletion. PR descriptions state final behavior, tests, data preservation evidence and known limits.
