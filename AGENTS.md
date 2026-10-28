# Daily_Arxiv maintenance

## Scope and layout

- Maintain this single bilingual repository. Legacy Chinese/English repositories are read-only sources; do not synchronize code changes back to them.
- The project is `Daily_Arxiv`, an independent repository under `Tool_Project`; its authorized GitHub identity is `YuhanJin-USTC/Daily_Arxiv`. Keep Python package/module names and the Research Workflow root ID `daily_arxiv` stable.
- Source lives on `main`; generated raw/AI/Markdown, pipeline state, notification state and public indexes live on `data`. Never mix generated data into source commits.
- Public settings belong only in `[tool.daily_arxiv]` in `pyproject.toml`. Preserve the existing model profile and moderation/quality checks unless separately requested.
- `ai/` owns model access, quality, provenance and recovery; `daily_arxiv/daily_arxiv/` owns crawl/history, researcher matching and notification semantics; `scripts/` owns staging/application/publication/build; `to_md/` owns rendering; `js/`, `css/` and HTML own the static reader.
- Use one implementation with explicit English/Chinese arguments. Do not add a frontend framework, service or database for these features.
- Keep five regular Actions entrypoints: Tests, Daily arXiv, Deploy website, Refresh researcher highlights and Maintenance. Maintenance retains `release-check.yml` for its existing history; retired workflow definitions belong in `docs/workflow-archive/`, not the active workflow directory.

## Research Workflow

- This is the independent `daily_arxiv` source root with mapping `none`. Resolve `CONTROL_ROOT`, the local project path and device identity from the verified device-local `workspace.toml`; keep the same root ID across devices.
- Before work, use `python3 -B "<CONTROL_ROOT>/tools/researchctl.py" context "root:daily_arxiv/<exact-directory>" --view compact --json`, replacing the placeholders. Use `root:daily_arxiv` for root-wide work; matching is exact unless recursion is explicitly requested.
- Record one substantive completed result with an event-only `checkpoint` at its exact owner. Retain purpose, result, accepted reasons, checks and limits in existing summary/evidence fields. Do not log ordinary discussion or planning, create empty Project/Study/Case membership, or invent historical work.
- Keep research authority in the control repository. Do not copy its metadata, SQLite or saved plans into this source tree, the `data` branch, pipeline state or website bundles. The application and Actions gain no Research Workflow runtime dependency or automatic recording hook.
- Registration does not pair paper data with simulation Cases, authorize another root, or change source/data separation, paid model, SMTP or publication gates. Preserve existing project boundaries and explicit user constraints.
- After changing devices, preserve local work and obtain separate synchronization authorization, then complete `doctor`, `event merge` and `validate` before context or any portable write. Do not copy device identity, local paths, SQLite or saved plans between devices. Portable policy history and cumulative approvals synchronize with the control repository; historical approval is not consent for a new device or target.
- A device without this project may read synchronized logical memory, but local access and new events require its verified root registration. New policy targets require local preview, real user approval and digest-bound apply; retain cumulative device approvals.

## Data and delivery invariants

- Validate raw coverage once. Raw normalized IDs define the paper set; each language may be complete or pending independently. Never hide raw papers because AI is absent.
- Preserve migration baselines: historical gaps never enter automatic AI or email backfill. Post-baseline language work must continue on runs with no new papers.
- Retain healthy JSONL bytes, accepted partial fields, full LICENSE and original attribution. Conflicting raw metadata/healthy same-language content stops migration for user review. Use new candidate directories and exact source/candidate hashes.
- AI reuse binds ID, exact abstract/source, language, model and prompt. Incompatible checkpoints must fail explicitly before paid requests. Markdown uses `DATE_English.md` and `DATE_Chinese.md`; never implicitly convert legacy shared Markdown targets.
- Researcher matches come from the backend module only. Reliable full names/confirmed aliases may enqueue mail; suspected names never do. Index digests bind researchers and effective categories. Escape all dynamic frontend text.
- Freeze raw discovery, researcher evidence and recipient cohort together before publication. Stable recipient ID plus normalized paper ID deduplicates mail. Persist/push sending state before SMTP; uncertain or interrupted delivery requires manual evidence and resolution, not automatic resend.
- Release probes are explicit manual checks: one source-bound post-baseline paper for AI, and one durable infrastructure email distinct from paper notifications. Never reinterpret historical gaps as new discoveries to satisfy a live test. Preserve release_probes alongside ordinary delivery state.
- Explicit recipient layout tests use one fixed scope per stable recipient ID. Preserve the initial sent probe; never generate arbitrary test IDs or reuse historical papers to trigger mail. Recipient changes cannot prevent evidence-backed resolution of saved uncertain delivery.
- Diagnose SMTP connection/auth failures with the manual auth-only check before another send. Keep diagnostics allowlisted; never record server response text, credentials or authentication payloads.
- Changing a frozen release-probe sender requires an explicit audited rebind from failed state. Preserve attempts, recipient and Message-ID; never rebind sent, sending or uncertain probes. Confirm replacement SMTP Secrets before authenticating with a new provider.
- All data workflows share `concurrency.group: arxiv-data`, `cancel-in-progress: false`; verify remote data HEAD before writes. Never force-push to recover a conflict. Configuration refresh updates highlights only, never historic mail.
- Daily and manual data operations honor `ENABLE_DATA_WRITES`; AI and email retain their separate gates. Maintenance runs only from `main`, and browser/auth jobs do not receive model or sending credentials beyond their own task.
- Mail uses English plain text plus an escaped HTML alternative with inline Times New Roman, Times and serif fallbacks. Never load remote fonts or change delivery identity for formatting.
- Keep mail recipients/SMTP configuration out of site bundles; credentials only in Secrets/environment. Do not infer authentication from recipient addresses. Preserve repository-specific authentication and Pages subpaths.
- Website builds copy the explicit static-file allowlist in `scripts/build_site.py`. Use that build for local authentication previews and Pages; never rewrite source authentication settings or copy whole source directories into the bundle.

## Checks and handoff

- Use GitHub Issues for the maintenance backlog and short-lived `fix/`, `feat/` or `chore/` branches with linked PRs. Keep each change coherent and review it before merge. Public issues, source and reports must not contain credentials or private research material.
- Keep each device's clone and environment independent. Preserve/push local task work before handoff, fetch before resuming, and use fast-forward-only updates for clean `main`. Review divergence; never force synchronization. The shared `update_git` helper must not publish a feature branch as `main`.
- Repository identity determines Pages, raw-data URLs and browser storage namespaces. Preserve the existing derivation instead of adding rename-specific compatibility flags or storage migration logic.
- Read nearby files first; match existing organization, concise English comments and tests. Prepare locked dependencies separately, then run `bash scripts/check.sh` for the shared local/CI lockfile, Ruff, Python/Node tests, shell syntax, site-build tests, workflow and whitespace checks. The script does not install tools or dependencies; services must be mocked in tests.
- For UI changes, inspect 1440/768/390 widths, keyboard selection, fast toggling, range/filter/detail state, stats deduplication and missing-language fallback. State clearly when browser inspection is unavailable.
- Dependency changes require a matching `uv.lock`; do not silently substitute unlocked tests for locked validation.
- Keep the existing upgrade evidence in ignored `artifacts/upgrade/STATE.md`; before resuming a large upgrade, read that state and necessary diffs. Keep later task evidence in its own ignored artifacts directory. Do not commit credentials, caches, previews, checkpoints or personal work logs to source.
- Remove obsolete generated caches, duplicate checkouts and previews after acceptance. Retain compact provenance, unique raw snapshots, sourced paid checkpoints and interpreter targets still used by `.venv`; verify retained copies before deleting duplicates.
- Follow the user's deletion rules. Never discard pre-existing changes. Remove only your own temporary outputs when obsolete, marking cleanup with `CODEX_TEMP_CLEANUP=1` and exact paths.
- Confirm Git remotes before publication. The legacy local source may be retained as `source-chinese`; never push there. `origin` must identify the authorized target GitHub repository. New GitHub repo creation/push/deployment, real SMTP/paid model calls and old-site changes need separate explicit release authorization. Activation variables are disabled by absence.
- Preserve old sites, branches and migration snapshots until the user explicitly approves any specific deletion. PR descriptions state final behavior, tests, data preservation evidence and known limits.
- When the user has enabled automatic branch deletion after merge, completed PR branches may follow that setting. Keep `main/data`; archive and obtain specific approval before deleting unmerged work. Local `main` tracks `origin/main`, uses fast-forward pulls and defaults to `origin`; temporary migration remotes are not required for normal use.
<!-- research-workflow:policy:start -->
<!-- digest: 53b828bcd3473143cd53c8eb3790393d6fec47f065abe2b14e0e167f32b593b7 -->
## Managed Research Workflow Policy

- `case-confirmation`: "A Case target does not imply a Case edit. For explicit registration or simulation-definition changes, finish files/checks, show the saved preview, actually ask and await the user, then apply the exact plan. A digest is not consent; unchanged accepted definitions add no revision."
- `external-operations`: "Do not run cluster, simulation, MATLAB, network, sync, build, or Git mutations without explicit user authorization."
- `framework-authority`: "Use Research Workflow 0.2.3 and the unversioned researchctl CLI. Preserve journal-only Case authority, original Event fields, historical migrate/tombstone bindings, immutable streams, and fail-closed forks."
- `indexing`: "Treat SQLite and saved plans as device-local derived state. Queries may refresh the disposable index; never synchronize it or use it as authority."
- `multi-device`: "Synchronize and check portable authority before context or any portable write after switching devices, including event-only work. Keep local TOML/device/paths, upgrade devices sequentially, and stop old metadata writers until local acceptance. External sync remains separately authorized."
- `propagation`: "Preview pending policy semantics, exact targets and differences; obtain real user approval of the stable digest, record it through policy approve, then apply. Preserve cumulative device approvals and unmanaged AGENTS bytes; Data/Notes and body patches require exact separate scope."
- `recording`: "Restore bounded Case, Study, Project, or exact root/path memory. Record one substantive result as an event at the most specific owner; retain purpose, result, accepted reasons, validation level and limits in existing summary/evidence. Do not log ordinary Q&A or create empty membership or pending queues."
- `workspace-routing`: "Resolve local access through verified roots and explicit mappings. Logical memory may be queried without a local mapping, but new writes require local registration. Keep Data read-only and Notes access within exact authorized links/sections."

<!-- research-workflow:policy:end -->
