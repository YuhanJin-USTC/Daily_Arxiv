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
- Show the original abstract with an explicit unavailable status when historical AI fields are invalid. Secondary-category filters include cross-listed papers; the overall count remains unique.

## Configuration

Public settings live in `pyproject.toml`. The editions differ only in:

```toml
[tool.daily_arxiv]
language = "English" # Chinese in the Chinese repository
```

Default categories: `physics.plasm-ph`, `physics.acc-ph`, `physics.optics`, `physics.flu-dyn`, `physics.atom-ph`, and `physics.comp-ph`. A nonempty Actions variable `CATEGORIES` overrides daily crawling. The reviewed October 20 backfill inventory uses those six original categories.

The model uses the repository Actions secret **`OPENAI_API_KEY`**, containing a valid official DeepSeek credential. Old `MODEL_NAME`, `OPENAI_BASE_URL`, and `LANGUAGE` environment/Actions variables do not override the versioned settings. No credential belongs in source, a command argument, an issue, or a log. An offline format check cannot prove a credential is active.

## Local development

Requirements: Python 3.12, uv, and Node.js 22 or newer for frontend tests.

```bash
uv sync --frozen
uv run --frozen ruff check ai daily_arxiv scripts to_md tests
uv run --frozen ruff format --check ai daily_arxiv scripts to_md tests
uv run --frozen python -m unittest discover -s tests -v
node --test tests/test_frontend.cjs
```

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

## License and attribution

Apache-2.0, see [LICENSE](LICENSE). This project builds on the original daily-arXiv work by Wei Deng and Jian Guan. Paper metadata and abstracts remain attributed to their authors and arXiv. AI summaries require scientific review.
