# daily-arXiv AI enhanced

[![Tests](../../actions/workflows/test.yml/badge.svg)](../../actions/workflows/test.yml)

Daily arXiv announcements with validated AI summaries and a static GitHub Pages reader. The English and Chinese repositories use the same implementation; only `tool.daily_arxiv.language` in `pyproject.toml` differs.

**中文升级与历史修复教程：[docs/upgrade-guide.zh.md](docs/upgrade-guide.zh.md)。**

## Behavior

- Track the configured categories, including cross-listed papers. Validate pagination, listing totals, metadata coverage, and unique IDs.
- Look back through arXiv's recent announcement window and skip IDs already published on `data` before model calls. This covers new submissions and cross-list announcements in the selected categories, not the entire arXiv archive or replacement-only revisions.
- Use DeepSeek's reviewed maximum profile: `deepseek-flash`, thinking enabled, effort `max`, 393,216 output tokens maximum, native 1M context. Input remains the paper abstract.
- Recover missing structured fields with at most two repair attempts. Keep accepted fields, reject placeholders, stop the batch on authentication/provider failures, and retain partial checkpoints separately.
- Publish only complete validated candidates. Preserve existing records byte-for-byte on same-day appends. Stage historical repairs for review instead of automatically overwriting archives.
- Show the original abstract with an explicit unavailable status when historical AI fields are invalid. Show only the configured subscription filters, including zero counts; cross-listed papers count in each matching filter while the overall count remains unique.

## Configuration

Public settings live in `pyproject.toml`. The editions differ only in:

```toml
[tool.daily_arxiv]
language = "English" # Chinese in the Chinese repository
```

Edit `[tool.daily_arxiv].categories` in `pyproject.toml` to add, remove, or reorder subscriptions in both editions. Defaults are `physics.plasm-ph`, `physics.acc-ph`, `physics.optics`, `physics.flu-dyn`, `physics.atom-ph`, and `physics.comp-ph`. A nonempty repository Actions variable `CATEGORIES` overrides this list for both daily crawling and website filters; update that override too, or intentionally clear it to use the file. Merging a file change into `main` automatically runs **Deploy website**. Changing only the variable requires running **Deploy website** manually. Do not edit generated `js/data-config.js`. The reviewed October 20 backfill inventory still uses its original six categories.

The model uses the repository Actions secret **`OPENAI_API_KEY`**, containing a valid official DeepSeek credential. Old `MODEL_NAME`, `OPENAI_BASE_URL`, and `LANGUAGE` environment/Actions variables do not override the versioned settings. No credential belongs in source, a command argument, an issue, or a log. An offline format check cannot prove a credential is active.

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

No keys or live model calls are needed for tests. `bash run.sh DATA_CHECKOUT NEW_OUTPUT` stages a local daily candidate and never publishes. Without a configured model key it stops after validated crawling. The data checkout must be a separate checkout of the repository's `data` branch.

## Workflows

| Workflow | Purpose | Can publish? |
| --- | --- | --- |
| Tests | Offline Python, frontend, formatting and lint checks | No |
| Daily arXiv | Crawl, validate, enhance, merge and commit complete data | `data` only |
| Stage historical AI repairs | Audit or repair selected archived dates/IDs | No; artifact only |
| Stage missing 2026-10-20 papers | Fetch only missing IDs from the reviewed 91-paper inventory | No; artifact only |
| Deploy website | Build public settings and deploy the static reader | GitHub Pages only |

Set **Settings → Pages → Source → GitHub Actions**. Website configuration is generated in the Pages artifact; scheduled jobs no longer commit generated settings to `main`. The reader fetches current data directly from `data`, so a new data commit does not need a website rebuild. Existing `ACCESS_PASSWORD` behavior is retained during the website build.

## Layout and recovery

`ai/` owns provider access, structured recovery, quality checks, and archived repair. `daily_arxiv/` owns crawling and coverage. `to_md/` renders validated records. `scripts/` stages and verifies data and builds the website. `tests/` and `docs/` contain regression tests and operating instructions. Runtime artifacts stay outside the code checkout; temporary atomic-write files are removed in `finally` blocks.

See [architecture](docs/architecture.md), [verified incident findings](docs/incidents-2026-10-21.md), and the [step-by-step guide](docs/upgrade-guide.zh.md). Recovery artifacts include source/candidate hashes and expire after 14 days; retain a reviewed manifest with the data PR. Existing valid summaries and paper metadata must not be regenerated to fix unrelated failures.

The recovery and backfill workflows accept `resume_run_id` together with `resume_artifact_name`. They download only a matching artifact from the same repository and workflow, verify its request, language, model profile and source hashes, then reuse its checkpoints. Backfill resumes the exact saved raw snapshot. Completed and partial fields survive repeated interruptions; older complete artifacts remain publishable with `apply_staged.py`.

If arXiv is unavailable after a successful audit-only backfill, use `metadata_run_id` and `metadata_artifact_name` instead of the resume inputs. The workflow verifies that same-repository audit's request, inventory and file hashes, excludes IDs now published, and requires metadata for every currently selected missing ID. Selected raw lines stay byte-identical; a new request binds them to current published files and records the original artifact hashes. Artifacts containing generated work are rejected here: use checkpoint resume to retain those paid results.

Backfill `ids` selects a subset of the reviewed inventory for a one-paper live check. Publish that complete candidate before fetching the remaining IDs. Historical repairs reuse complete same-language summaries only for the same ID and exact abstract; conflicting values for requested fields stop the operation. Manifest `model_paper_ids` counts papers sent for generation, not HTTP requests or field-repair attempts; `reused_ids`, `checkpoint_reused_ids` and source hashes explain avoided regeneration.

## License and attribution

Apache-2.0, see [LICENSE](LICENSE). This project builds on the original daily-arXiv work by Wei Deng and Jian Guan. Paper metadata and abstracts remain attributed to their authors and arXiv. AI summaries require scientific review.
