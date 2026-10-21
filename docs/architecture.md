# Shared architecture and invariants

The repositories are two language editions of the same project. Their reviewed source trees differ only at `pyproject.toml: tool.daily_arxiv.language`. Repository owner/name are injected at website build time from `GITHUB_REPOSITORY`.

## Boundaries

- `ai/config.py`: reads public settings; checks only credential presence/format.
- `ai/deepseek.py`: one provider adapter using the already-tested OpenAI SDK. No generic provider or forced-tool fallback. JSON output retains raw final content for field recovery; reasoning traces never enter published data or checkpoints.
- `ai/structured_output.py`: validates five fields, retains accepted strings, performs up to three invocations total, and stops on provider exceptions. Legacy tool argument/Pydantic extraction remains supported for reusable recovery tests.
- `ai/enhance.py`: content checks and sequential batches. 401/403 cannot leave a large pending queue. A content service failure or positive rejection stops publication instead of silently removing a paper. Checkpoints are separate from the final file.
- `ai/recover.py` and `ai/reuse.py`: exact-ID or date-range repairs and complete-summary reuse keyed by normalized ID, exact abstract and language. Conflicting requested fields fail closed; manifest provenance records source filenames and hashes. Atomic checkpoint snapshots retain inherited fields across repeated interruptions. Raw archived abstracts must match enhanced records. Healthy lines and existing valid fields are immutable; target metadata, order and IDs are preserved.
- `daily_arxiv/crawl.py` and the spider: full listing selection, history exclusions before metadata calls, actual-page-length pagination, metadata and ID-set verification, atomic output.
- `scripts/stage_daily.py`: append new rows to published bytes, update the full file inventory, render Markdown, and stage a manifest. Persist every completed paper and preserve inherited completed/partial fields before another request.
- `scripts/resume_artifact.py`: validate same-repository/workflow resume selection, bind request/language/model/prompt/source hashes, and reuse the exact backfill raw snapshot. Downloaded paths must stay within the artifact directory; old complete manifests remain compatible with publication.
- `scripts/apply_staged.py`: verify all candidate/source hashes and byte-preservation invariants before changing a separate data checkout. A failed operation is not committed/pushed automatically. Multi-file disk writes are not a filesystem transaction; inspect an interrupted checkout before retrying.
- `scripts/build_site.py`: copy only static assets, render public repository/language settings and existing password-hash configuration. Generated files never enter the source branch.

## Completeness boundaries

Recent crawling covers the selected categories' official recent announcement window, normally five announcement days. It does not claim complete historical coverage after arbitrarily long outages. The dated October 20 inventory supports that specific backfill after the window has expired. An optional exact-ID subset supports a one-paper live check; coverage records the inventory, published IDs, selected IDs and remaining IDs. Each paper is processed once across the repository's published IDs; a later cross-list of an already-published paper does not trigger another AI generation.

The inventory has 91 unique IDs. Both original October 20 archives had 59, missing 32 externally cross-listed papers. A default recent catch-up can also discover unpublished papers on other dates; the dedicated historical backfill limits selection to the reviewed inventory.

## Configuration and model limits

The official documentation on 2026-10-21 maps `deepseek-flash` to DeepSeek-V4.1-Flash-1017. The release announcement reports benchmarks above V4 Pro; this does not guarantee superiority on every paper. Thinking uses `reasoning_effort=max`. `max_tokens=393216` permits up to 384K tokens including reasoning and final output. The model's context capacity is 1M; there is no invented `context_length` API parameter. Abstracts are not truncated, padded, or automatically replaced with full-text PDFs.

JSON mode avoids forced `tool_choice`, unsupported in thinking mode. Invalid/truncated/refused output cannot publish. Temperature and penalties are not treated as reasoning-strength controls. SDK transient retries remain bounded; 401/403 do not enter schema retries. Timeout is 1,800 seconds per request; workflows allow up to six hours. Prefer per-day historical jobs at maximum reasoning.

Sources: [model limits](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/), [release log](https://api-docs.deepseek.com/zh-cn/updates/), [thinking](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/), [JSON output](https://api-docs.deepseek.com/zh-cn/guides/json_mode/), [Chat API](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/), [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
