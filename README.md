# daily-arXiv AI enhanced

**[Open the website — English / Chinese AI summaries](https://yuhanjin-ustc.github.io/daily-arxiv/)**

The website is deployed on GitHub Pages and opens at the password screen. Use the configured site password to sign in, then select EN / ZH.

[![Tests](https://github.com/YuhanJin-USTC/daily-arxiv/actions/workflows/test.yml/badge.svg)](https://github.com/YuhanJin-USTC/daily-arxiv/actions/workflows/test.yml)

Daily arXiv announcements with validated AI summaries and a static GitHub Pages reader. One repository stores shared raw metadata and separate English and Chinese AI interpretations. English is the default; EN / ZH switches only the AI content. The two legacy projects remain historical sources.

**双语配置、迁移与发布：[docs/bilingual-operation.md](docs/bilingual-operation.md)。** The [older incident guide](docs/upgrade-guide.zh.md) documents the previous two-repository rollout.

## Behavior

- Track the configured categories, including cross-listed papers. Validate pagination, listing totals, metadata coverage, and unique IDs.
- Look back through arXiv's recent announcement window and skip IDs already published on `data` before model calls. This covers new submissions and cross-list announcements in the selected categories, not the entire arXiv archive or replacement-only revisions.
- Use DeepSeek's reviewed maximum profile: `deepseek-flash`, thinking enabled, effort `max`, 393,216 output tokens maximum, native 1M context. Input remains the paper abstract.
- Recover missing structured fields with at most two repair attempts. Keep accepted fields, reject placeholders, stop the batch on authentication/provider failures, and retain partial checkpoints separately.
- Publish verified raw metadata before AI; save each complete language result independently. Persist new-paper language work across empty crawl runs. Preserve historical missing-language baselines, healthy bytes and accepted partial fields.
- Highlight confirmed and suspected researcher names through one backend index. Send one English digest per enabled recipient/day only for reliable new-paper matches; persist queue and uncertainty state before SMTP. No historical email backfill.
- Show the original abstract with an explicit unavailable status when historical AI fields are invalid. Show only the configured subscription filters, including zero counts; cross-listed papers count in each matching filter while the overall count remains unique.

## Configuration

Public settings live in `pyproject.toml`:

```toml
[tool.daily_arxiv]
language = "English"
languages = ["English", "Chinese"]
```

Edit `pyproject.toml`, commit the change and push it to GitHub `main`, normally by merging a reviewed pull request. Local edits alone do not change the deployed site or scheduled jobs.

| Setting | Where to edit | When it takes effect |
| --- | --- | --- |
| Categories | `[tool.daily_arxiv].categories` | The next **Daily arXiv** run crawls the new selection; the push also rebuilds the website filters. |
| Watched researchers | `[[tool.daily_arxiv.researchers]]` | The push automatically runs **Refresh researcher highlights** for existing papers. It does not enqueue historical mail. |
| Mail recipients | `[[tool.daily_arxiv.notifications.recipients]]` | Later new discoveries freeze the updated recipient cohort. Existing frozen cohorts remain unchanged, with no historical email backfill. |

The configured categories are `physics.plasm-ph`, `physics.acc-ph`, `physics.optics`, `physics.flu-dyn`, `physics.atom-ph`, and `physics.comp-ph`. The repository currently has no `CATEGORIES` Actions variable, so this file supplies the selection. If a nonempty `CATEGORIES` override is added later, it takes precedence for crawling and website filters. Changing only that variable requires running **Deploy website** and **Refresh researcher highlights** manually. Do not edit generated `js/data-config.js`. The reviewed October 20 backfill inventory retains its original six categories.

The model uses the repository Actions secret **`OPENAI_API_KEY`**, containing a valid official DeepSeek credential. Old `MODEL_NAME`, `OPENAI_BASE_URL`, and `LANGUAGE` environment/Actions variables do not override the versioned settings. No credential belongs in source, a command argument, an issue, or a log. An offline format check cannot prove a credential is active.

Researchers use stable IDs, enabled flags, full display names, `aliases` (confirmed), and `suspected_aliases` (unconfirmed). Keep verified name variants in `aliases`; ambiguous abbreviations remain suspected and never trigger mail. The current researcher and recipient lists live in `pyproject.toml`. Browser author filters are personal and do not control repository notifications. Name-only matching cannot establish identity.

Mail uses QQ SMTP SSL on port 465, with `SMTP_USERNAME` and `SMTP_PASSWORD` supplied as Secrets or environment variables; use the QQ client authorization code. The configured QQ sender delivers to the enabled USTC recipients. A daily digest is sent only when new papers reliably match watched researchers; a day without such matches produces no paper email. English messages include plain text and HTML alternatives; HTML uses Times New Roman with local serif fallbacks. `notifications.smtp` supports other SSL or STARTTLS providers without transport changes. Mail addresses are intentionally public in configuration, but are excluded from website bundles.

Configure credentials separately in **Settings → Secrets and variables → Actions**: `OPENAI_API_KEY`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and the website's `ACCESS_PASSWORD`. Editing categories, researchers or recipients does not configure these Secrets. Never put credentials in TOML or chat. See [.env.example](.env.example) and [operations](docs/bilingual-operation.md).

## Local development

Requirements: Bash/WSL, Git, uv, Python 3.12 or newer, Node.js 22 or newer, and [actionlint 1.7.12](https://github.com/rhysd/actionlint/releases/tag/v1.7.12). Prepare the dependencies from `uv.lock`, then use the same check entrypoint as GitHub Actions. uv creates the virtual environment; activation is unnecessary:

```bash
uv sync --frozen
bash scripts/check.sh
```

The check script validates the lockfile offline, Ruff, Python tests including site builds, Node tests, shell syntax, active workflows and diff whitespace. It uses the prepared `.venv` without installing or downloading tools or dependencies. Set `ARXIV_UV`, `ARXIV_NODE` or `ARXIV_ACTIONLINT` to an executable path when a tool is not on PATH. Optional ShellCheck and Pyflakes integrations are disabled so actionlint runs the same checks locally and in CI.

Keep dependency changes and the updated `uv.lock` together; do not substitute an unlocked pip installation for validation. Local `run.sh` uses `.venv/bin/python`; set `ARXIV_PYTHON` to another virtual environment's interpreter when needed. Website previews use `scripts/build_site.py` and a new output directory; supply `ACCESS_PASSWORD` through the environment to build authentication. The build copies its explicit static-file allowlist and renders configuration in the output, leaving source files unchanged.

No keys or live model calls are needed for tests. `bash run.sh DATA_CHECKOUT NEW_OUTPUT` crawls once and prepares a separate raw candidate without changing the supplied checkout. Only an explicit third argument `--generate` enables model requests for both languages; this also processes eligible pending languages when no papers are newly discovered. It never publishes or sends mail. The data checkout must be a separate checkout of the repository's `data` branch.

## Workflows

| Workflow | Purpose | Can publish? |
| --- | --- | --- |
| [Tests](.github/workflows/test.yml) | Offline Python, frontend, formatting and lint checks | No |
| [Daily arXiv](.github/workflows/run.yml) | Crawl once; persist raw/cohort; notify reliable matches; independently save both AI languages | `data` only, activation gated |
| [Deploy website](.github/workflows/pages.yml) | Build public settings and deploy the static reader | GitHub Pages only |
| [Refresh researcher highlights](.github/workflows/researchers.yml) | Rebuild history index after configuration changes; no email enqueue | `data` only, activation gated |
| [Maintenance](.github/workflows/release-check.yml) | Explicit manual checks: `browser`, `crawl`, `ai` for one new paper ID, `smtp-auth`, or `recipient-mail` | Selected actions write `data`; `recipient-mail` can send its one-time test email |

**Maintenance** keeps the existing `release-check.yml` workflow identity. Use `browser` to verify the deployed reader, optionally with a paper ID whose two AI languages are complete. The `ai` action requires one genuinely new post-baseline ID; it does not regenerate historical papers. `smtp-auth` checks transport authentication without sending mail. `recipient-mail` uses a fixed scope per configured recipient and skips a test already marked sent.

Publication is initially gated by repository variables: `ENABLE_PAGES`, `ENABLE_DATA_WRITES`, `ENABLE_DAILY`, `ENABLE_AI`, and `ENABLE_EMAIL` must each equal `true` for their respective actions. Configure these only during the approved rollout. Set **Settings → Pages → Source → GitHub Actions**. Website configuration is generated in the Pages artifact; scheduled jobs no longer commit generated settings to `main`. The reader fetches current data directly from `data`, so a new data commit does not need a website rebuild. Existing `ACCESS_PASSWORD` behavior is retained during the website build.

## Layout and recovery

`ai/` owns provider access, structured recovery, quality checks, and archived repair. `daily_arxiv/` owns crawling and coverage. `to_md/` renders validated records. `scripts/` stages and verifies data and builds the website. `tests/` and `docs/` contain regression tests and operating instructions. Runtime artifacts stay outside the code checkout; temporary atomic-write files are removed in `finally` blocks.

See [architecture](docs/architecture.md), [verified incident findings](docs/incidents-2026-10-21.md), and the [step-by-step guide](docs/upgrade-guide.zh.md). Recovery artifacts include source/candidate hashes and expire after 14 days; retain a reviewed manifest with the data PR. Existing valid summaries and paper metadata must not be regenerated to fix unrelated failures.

The former recovery, October 20 backfill and standalone browser workflows are preserved under [docs/workflow-archive](docs/workflow-archive/README.md) as historical reference, outside active Actions entrypoints. CLI recovery remains available through `ai/recover.py`, `scripts/resume_artifact.py` and `scripts/apply_staged.py`; use the archive guide for the corresponding commands and provenance requirements.

The archived workflows document `resume_run_id` / `resume_artifact_name`, audit-only `metadata_run_id` / `metadata_artifact_name`, and exact-ID `ids` selection. These are historical workflow inputs, not controls in **Maintenance**. Recovery verifies the request, explicit language, model profile and exact source hashes before reusing checkpoints. Backfill retains its saved raw snapshot; incompatible legacy partial checkpoints fail explicitly, and legacy shared Markdown targets require language-specific restaging. Completed and partial fields survive interruptions without changing healthy records.

Historical repairs reuse complete same-language summaries only for the same ID and exact abstract; conflicting values stop the operation. Manifest `model_paper_ids` counts papers sent for generation, not HTTP requests or field-repair attempts; `reused_ids`, `checkpoint_reused_ids` and source hashes explain avoided regeneration.

## License and attribution

Modified Apache License, see the unchanged full [LICENSE](LICENSE). This is a customized license, not a declaration of standard Apache-2.0. This project builds on the original daily-arXiv work by Wei Deng and Jian Guan. Paper metadata and abstracts remain attributed to their authors and arXiv. AI summaries require scientific review.
