# Changelog

## 2026-10-21 — Unified English and Chinese recovery

- Fix missing cross-listed papers and add paging/metadata completeness checks.
- Preserve published rows and file inventory on catch-up and same-day runs.
- Stop authentication failures immediately instead of publishing five error strings.
- Retain valid structured fields, retry missing fields locally, and preserve checkpoints.
- Unify both editions on one maximum-capability DeepSeek adapter and one configuration file.
- Add reviewed historical repair and missing-ID backfill workflows with hash-checked application.
- Repair frontend fallback, secondary-category filters, unique counts, and edition language selection.
- Separate website deployment from data publication and stop generated source commits.
- Remove unused LangChain dependencies and duplicate configuration; add frozen dependencies, shared CI, formatter and lint checks.
