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

- Verify the device's registered root daily_arxiv (mapping none). Use `python3 -B "<CONTROL_ROOT>/tools/researchctl.py" context "root:daily_arxiv/<exact-directory>" --view compact --json` or root:daily_arxiv. Checkpoint one completed result there.
- Keep control metadata, SQLite and plans out of source, data, pipeline state and site bundles. Neither the app nor Actions gains workflow hooks. Paper data grants no Case membership or sibling access.

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

- Use Issues and reviewed fix/, feat/ or chore/ PRs for authorized GitHub work. Keep credentials and private research material out of public records. Preserve local work. Push, fetch and fast-forward handoffs only with current-task authorization. Review divergence. Never force sync or publish a feature branch as main via update_git.
- Repository identity determines Pages, raw-data URLs and browser storage namespaces. Preserve the existing derivation instead of adding rename-specific compatibility flags or storage migration logic.
- Read nearby code and tests. With authorization for Git and the required fixtures, use bash scripts/check.sh for offline lockfile, Ruff, Python/Node, shell syntax, site-build, workflow and git diff --check. Prepare locked dependencies separately. Mock services.
- For UI changes, inspect 1440/768/390 widths, keyboard selection, fast toggling, range/filter/detail state, stats deduplication and missing-language fallback. State clearly when browser inspection is unavailable.
- Dependency changes require a matching `uv.lock`; do not silently substitute unlocked tests for locked validation.
- Preserve existing upgrade evidence in artifacts/upgrade/STATE.md, raw snapshots, paid checkpoints, provenance and .venv interpreter targets. Read the state before resuming an upgrade. Obtain approval for new artifact locations or purposes and for exact deletions of user content. Keep private material and generated outputs out of source. Clean only exact task-owned temporary paths with CODEX_TEMP_CLEANUP=1.
- Confirm Git remotes before publication. The legacy local source may be retained as `source-chinese`; never push there. `origin` must identify the authorized target GitHub repository. New GitHub repo creation/push/deployment, real SMTP/paid model calls and old-site changes need separate explicit release authorization. Activation variables are disabled by absence.
- Preserve old sites, branches and migration snapshots until the user explicitly approves any specific deletion. PR descriptions state final behavior, tests, data preservation evidence and known limits.
- When the user has enabled automatic branch deletion after merge, completed PR branches may follow that setting. Keep `main/data`; archive and obtain specific approval before deleting unmerged work. Local `main` tracks `origin/main`, uses fast-forward pulls and defaults to `origin`; temporary migration remotes are not required for normal use.
<!-- research-workflow:policy:start -->
<!-- digest: 255425630765de0b777c8b315a1469fc936fca419187535850dcd16888fc5f5d -->
## Managed Research Workflow Policy

- `case-confirmation`: "Case ownership alone changes no definition. For registration, definition or lifecycle changes, finish files/checks, show the saved plan, ask and await consent, then apply its digest. Equal definitions add no revision."
- `external-operations`: "Require explicit task authorization for Git, network/API, SSH, cluster, transfer, sync, simulation, MATLAB, builds, containers and SIF operations."
- `framework-authority`: "Use Research Workflow 0.2.4 and its unversioned CLI. Preserve journal-only Cases, original Event fields, migrate/tombstone bindings and immutable streams. Stop on forks."
- `indexing`: "SQLite and saved plans are disposable device-local state. Queries may refresh SQLite. Never sync either or use it as authority."
- `multi-device`: "After a switch, preserve local work and separately authorize sync. Check portable authority with doctor, event merge and validate before context or any portable write. Keep TOML, paths and identity local. Upgrade sequentially with old writers stopped through acceptance."
- `propagation`: "Show pending semantics, exact targets, diffs and stable digest. After user approval, record it with policy approve and apply that digest. Preserve cumulative approvals and unmanaged bytes. Data, Notes and body patches need separate exact scope."
- `recording`: "Restore compact Case, Study, Project or exact root/path context. Record one substantive result at its closest eligible owner, with purpose, result, accepted reasons, checks and limits in summary/evidence. Skip ordinary discussion, empty membership and pending queues."
- `workspace-routing`: "Use verified roots and explicit mappings. Unmapped logical memory is readable. Local access and new writes need registration. Data stays read-only. Scope Notes to exact links/sections and writes to explicit requests."

<!-- research-workflow:policy:end -->
