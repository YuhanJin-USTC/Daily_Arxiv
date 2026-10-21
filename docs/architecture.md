# Shared architecture and invariants

The repository has one raw archive and two language outputs. Its source history derives from Chinese main; both old projects remain independently preserved. Repository owner/name are injected at website build time from `GITHUB_REPOSITORY`.

## Boundaries

- `ai/config.py`: reads public settings; checks only credential presence/format.
- `ai/deepseek.py`: one provider adapter using the already-tested OpenAI SDK. No generic provider or forced-tool fallback. JSON output retains raw final content for field recovery; reasoning traces never enter published data or checkpoints.
- `ai/structured_output.py`: validates five fields, retains accepted strings, performs up to three invocations total, and stops on provider exceptions. Legacy tool argument/Pydantic extraction remains supported for reusable recovery tests.
- `ai/enhance.py`: content checks and sequential batches. 401/403 cannot leave a large pending queue. A content service failure or positive rejection stops publication instead of silently removing a paper. Checkpoints are separate from the final file.
- `ai/recover.py` and `ai/reuse.py`: exact-ID or date-range repairs and complete-summary reuse keyed by normalized ID, exact abstract and language. Conflicting requested fields fail closed; manifest provenance records source filenames and hashes. Atomic checkpoint snapshots retain inherited fields across repeated interruptions. Raw archived abstracts must match enhanced records. Healthy lines and existing valid fields are immutable; target metadata, order and IDs are preserved.
- `daily_arxiv/crawl.py` and the spider: full listing selection, history exclusions before metadata calls, actual-page-length pagination, metadata and ID-set verification, atomic output.
- `scripts/stage_daily.py`: append new rows to published bytes, update the full file inventory, render Markdown, and stage a manifest. Persist every completed paper and preserve inherited completed/partial fields before another request.
- `scripts/resume_artifact.py`: validate same-repository/workflow resume selection, bind request/language/model/prompt/source hashes, and reuse the exact backfill raw snapshot. Downloaded paths must stay within the artifact directory; legacy shared Markdown manifests are explicitly rejected rather than silently converted; archived results remain readable.
- `scripts/apply_staged.py`: verify all candidate/source hashes and byte-preservation invariants before changing a separate data checkout. A failed operation is not committed/pushed automatically. Multi-file disk writes are not a filesystem transaction; inspect an interrupted checkout before retrying.
- `scripts/build_site.py`: copy only static assets, render public repository/language settings and existing password-hash configuration. Generated files never enter the source branch.

## Completeness boundaries

Recent crawling covers the selected categories' official recent announcement window, normally five announcement days. It does not claim complete historical coverage after arbitrarily long outages. The dated October 20 inventory supports that specific backfill after the window has expired. An optional exact-ID subset supports a one-paper live check; coverage records the inventory, published IDs, selected IDs and remaining IDs. Discovery, per-language completion and per-recipient notification are separate states. A later cross-list/version does not trigger new discovery or duplicate mail; pending post-baseline languages are retried even when crawling finds no new IDs. Historical missing translations are not automatically generated.

The inventory has 91 unique IDs. Both original October 20 archives had 59, missing 32 externally cross-listed papers. A default recent catch-up can also discover unpublished papers on other dates; the dedicated historical backfill limits selection to the reviewed inventory.

## Configuration and model limits

The official documentation on 2026-10-21 maps `deepseek-flash` to DeepSeek-V4.1-Flash-1017. The release announcement reports benchmarks above V4 Pro; this does not guarantee superiority on every paper. Thinking uses `reasoning_effort=max`. `max_tokens=393216` permits up to 384K tokens including reasoning and final output. The model's context capacity is 1M; there is no invented `context_length` API parameter. Abstracts are not truncated, padded, or automatically replaced with full-text PDFs.

JSON mode avoids forced `tool_choice`, unsupported in thinking mode. Invalid/truncated/refused output cannot publish. Temperature and penalties are not treated as reasoning-strength controls. SDK transient retries remain bounded; 401/403 do not enter schema retries. Timeout is 1,800 seconds per request; workflows allow up to six hours. Prefer per-day historical jobs at maximum reasoning.

Sources: [model limits](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/), [release log](https://api-docs.deepseek.com/zh-cn/updates/), [thinking](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/), [JSON output](https://api-docs.deepseek.com/zh-cn/guides/json_mode/), [Chat API](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/), [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Bilingual data and notifications

`migrate_history.py` scans immutable source trees rather than old inventories. It unions normalized IDs per date (Chinese order, then English-only), fails on conflicting metadata or healthy same-language duplicates, and retains enhanced JSONL and renamed Markdown bytes. The manifest contains source commits, file hashes, day counts, availability and target hashes. `data/pipeline-state.json` stores the migration baseline and post-cutover discoveries. `data/notification-state.json` stores frozen discovery eligibility and per-recipient delivery state.

`bilingual_daily.py` stages verified raw data or one language independently. Its checkpoint reuse binds normalized ID, exact abstract/source record, language, model profile and prompt hashes. A failed language saves accepted progress and does not prevent another language. Raw records, language files and `DATE_LANGUAGE.md` have distinct paths. `apply_staged.py` verifies all paths and source/candidate hashes before any writes; multi-file disk writes are recoverable, not a filesystem transaction.

`daily_update.py` adds a frozen recipient/match cohort and public index to the raw stage, publishes it before mail, and commits accepted language stages independently. `publish_data.py` permits only generated paths, refuses local/unexpected origins, checks current remote data HEAD, then commits/pushes without force. All workflows that access shared data use `arxiv-data` concurrency. `researchers.yml` refreshes the index only; it never enqueues historical email.

`researchers.py` normalizes case, Unicode, spaces and abbreviation dots without fuzzy/substring rules. The public index records identity, original author, reliability and basis and binds researcher configuration plus effective categories. Both UI and notifications consume this backend matching rule. UI joins selected AI by normalized ID and exact abstract to raw papers; stale index digests are not trusted. Personal preferences use a repository namespace with nondestructive fallback to old keys; authentication retains separate repository keys.

`notifications.py` freezes the discovery cohort once, even when no names match. Only reliable matches enqueue. Stable recipient ID + normalized paper ID deduplicates versions/cross-lists/languages. Sending state is durably published before SMTP; explicit rejection can retry within bounds, while disconnect/unknown acceptance or post-send persistence failure becomes uncertain. A recovered sending state also becomes uncertain. Resolve a digest only after checking evidence. SMTP does not guarantee exactly-once delivery. Notifications run before AI and their failure is reported after independent AI saving.
