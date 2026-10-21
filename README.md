# daily-arXiv AI enhanced

[![Tests](../../actions/workflows/test.yml/badge.svg)](../../actions/workflows/test.yml)

Daily arXiv announcements with validated AI summaries and a static GitHub Pages reader. One repository stores shared raw metadata and separate English and Chinese AI interpretations. English is the default; EN / 中文 switches only the AI content. The two legacy projects remain historical sources.

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

Edit `[tool.daily_arxiv].categories` in `pyproject.toml` to add, remove, or reorder subscriptions in this repository. Defaults are `physics.plasm-ph`, `physics.acc-ph`, `physics.optics`, `physics.flu-dyn`, `physics.atom-ph`, and `physics.comp-ph`. A nonempty repository Actions variable `CATEGORIES` overrides this list for both daily crawling and website filters; update that override too, or intentionally clear it to use the file. After release activation, merging a file change into `main` runs **Deploy website** and researcher configuration changes refresh historical highlights without enqueueing email. Changing only the variable requires running both **Deploy website** and **Refresh researcher highlights** manually. Do not edit generated `js/data-config.js`. The reviewed October 20 backfill inventory still uses its original six categories.

The model uses the repository Actions secret **`OPENAI_API_KEY`**, containing a valid official DeepSeek credential. Old `MODEL_NAME`, `OPENAI_BASE_URL`, and `LANGUAGE` environment/Actions variables do not override the versioned settings. No credential belongs in source, a command argument, an issue, or a log. An offline format check cannot prove a credential is active.

Researchers use stable IDs, enabled flags, full display names, `aliases` (confirmed), and `suspected_aliases` (unconfirmed). Initial abbreviated names are suspected only; they never trigger mail. Browser author filters are personal and do not control repository notifications. Name-only matching cannot establish identity.

Mail defaults to USTC SMTP SSL, port 465, with `SMTP_USERNAME` and `SMTP_PASSWORD` supplied as Secrets or environment variables; use a client-specific password. `notifications.smtp` also supports Gmail SSL or STARTTLS without code changes. Recipient email addresses are intentionally public in configuration, but are excluded from website bundles. Never put credentials in TOML or chat. See [.env.example](.env.example) and [operations](docs/bilingual-operation.md).

## Local development

Requirements: Python 3.12 or newer and Node.js 22 or newer. Use a virtual environment without activating it. This repository has dependency declarations, not an installable package configuration; install the declared runtime and development dependencies directly:

```bash
python3 -m venv .venv
.venv/bin/python - <<'PY'
import subprocess
import sys
import tomllib
from pathlib import Path

config = tomllib.loads(Path("pyproject.toml").read_text())
dependencies = config["project"]["dependencies"] + config["dependency-groups"]["dev"]
subprocess.check_call([sys.executable, "-m", "pip", "install", *dependencies])
PY
.venv/bin/python -m ruff check ai daily_arxiv scripts to_md tests
.venv/bin/python -m ruff format --check ai daily_arxiv scripts to_md tests
.venv/bin/python -m unittest discover -s tests -v
node --test tests/*.cjs
```

These are Bash/WSL commands; Windows virtual environments use `.venv/Scripts/python.exe`. Pip resolves the declarations and does **not** guarantee the exact versions in `uv.lock`. GitHub Actions installs uv itself and continues to use `uv sync --frozen`. Local `run.sh` uses `.venv/bin/python`; set `ARXIV_PYTHON` to another virtual environment's interpreter when needed.

No keys or live model calls are needed for tests. `bash run.sh DATA_CHECKOUT NEW_OUTPUT` crawls once and prepares a separate raw candidate without changing the supplied checkout. Only an explicit third argument `--generate` enables model requests for both languages; this also processes eligible pending languages when no papers are newly discovered. It never publishes or sends mail. The data checkout must be a separate checkout of the repository's `data` branch.

## Workflows

| Workflow | Purpose | Can publish? |
| --- | --- | --- |
| Tests | Offline Python, frontend, formatting and lint checks | No |
| Daily arXiv | Crawl once; persist raw/cohort; notify; independently save both AI languages | `data` only, activation gated |
| Refresh researcher highlights | Rebuild history index after configuration changes; no email enqueue | `data` only, activation gated |
| Stage historical AI repairs | Audit or repair selected archived dates/IDs | No; artifact only |
| Stage missing 2026-10-20 papers | Fetch only missing IDs from the reviewed 91-paper inventory | No; artifact only |
| Deploy website | Build public settings and deploy the static reader | GitHub Pages only |

Publication is initially gated by repository variables: `ENABLE_PAGES`, `ENABLE_DATA_WRITES`, `ENABLE_DAILY`, `ENABLE_AI`, and `ENABLE_EMAIL` must each equal `true` for their respective actions. Configure these only during the approved rollout. Set **Settings → Pages → Source → GitHub Actions**. Website configuration is generated in the Pages artifact; scheduled jobs no longer commit generated settings to `main`. The reader fetches current data directly from `data`, so a new data commit does not need a website rebuild. Existing `ACCESS_PASSWORD` behavior is retained during the website build.

## Layout and recovery

`ai/` owns provider access, structured recovery, quality checks, and archived repair. `daily_arxiv/` owns crawling and coverage. `to_md/` renders validated records. `scripts/` stages and verifies data and builds the website. `tests/` and `docs/` contain regression tests and operating instructions. Runtime artifacts stay outside the code checkout; temporary atomic-write files are removed in `finally` blocks.

See [architecture](docs/architecture.md), [verified incident findings](docs/incidents-2026-10-21.md), and the [step-by-step guide](docs/upgrade-guide.zh.md). Recovery artifacts include source/candidate hashes and expire after 14 days; retain a reviewed manifest with the data PR. Existing valid summaries and paper metadata must not be regenerated to fix unrelated failures.

The recovery and backfill workflows accept `resume_run_id` together with `resume_artifact_name`. They download only a matching artifact from the same repository and workflow, verify its request, language, model profile and source hashes, then reuse compatible checkpoints. Select the language explicitly. Incompatible legacy partial checkpoints are rejected; archived AI remains readable, and complete old artifacts keep hash-checked compatibility. Backfill resumes the exact saved raw snapshot. Completed and partial fields survive repeated interruptions; older complete artifacts remain inspectable; legacy shared Markdown targets require explicit language-scoped restaging.

If arXiv is unavailable after a successful audit-only backfill, use `metadata_run_id` and `metadata_artifact_name` instead of the resume inputs. The workflow verifies that same-repository audit's request, inventory and file hashes, excludes IDs now published, and requires metadata for every currently selected missing ID. Selected raw lines stay byte-identical; a new request binds them to current published files and records the original artifact hashes. Artifacts containing generated work are rejected here: use checkpoint resume to retain those paid results.

Backfill `ids` selects a subset of the reviewed inventory for a one-paper live check. Publish that complete candidate before fetching the remaining IDs. Historical repairs reuse complete same-language summaries only for the same ID and exact abstract; conflicting values for requested fields stop the operation. Manifest `model_paper_ids` counts papers sent for generation, not HTTP requests or field-repair attempts; `reused_ids`, `checkpoint_reused_ids` and source hashes explain avoided regeneration.

## License and attribution

Modified Apache License, see the unchanged full [LICENSE](LICENSE). This is a customized license, not a declaration of standard Apache-2.0. This project builds on the original daily-arXiv work by Wei Deng and Jian Guan. Paper metadata and abstracts remain attributed to their authors and arXiv. AI summaries require scientific review.
