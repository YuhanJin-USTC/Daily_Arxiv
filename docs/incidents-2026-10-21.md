# Verified incident findings, 2026-10-21

| Issue | Evidence and scope | Shared fix |
| --- | --- | --- |
| Chinese missing conclusion | Run 39379329257, 2026-10-20 06:21:04 UTC: required `Structure.conclusion` missing. 59 rows, 58 complete, one failed: 2610.26164. | Keep valid fields, two local repair attempts, exact-ID staged repair. |
| English authentication failures | Supplied incident package documents 401s for October 15–20; six archived dates independently rechecked: 35, 39, 6, 39, 48, 59 failed rows, total 226. | Redacted 401/403 classification, stop immediately, nonzero exit, no replacement of healthy output. A valid provider key is still required. |
| Missing papers | Six official category lists for October 20 contain 91 unique IDs; both repositories contain the same 59. All 32 missing IDs have a primary category outside the subscription and a secondary category inside it. | Include cross-lists, paginate, compare expected and final ID sets, preserve history, independent archived-inventory backfill. |
| Broken display | Legacy five-field error strings are nonempty, and primary-only filtering omits cross-lists in category views. | Original-abstract fallback with status, secondary-category membership, unique totals, configured edition language. |
| Unsafe publishing | Errors were swallowed; incomplete data, same-day reruns, stale inventories and broad code staging could lose records or misreport success. | Validated staging, byte-preserving append, hash checks, separate code/data/website workflows, non-fast-forward push failure. |

Official October 20 category counts (categories overlap): acc-ph 5, atom-ph 15, comp-ph 19, flu-dyn 20, optics 26, plasm-ph 12. Unique total: 91. Source URLs and all IDs/titles/categories are retained in `audits/arxiv-2026-10-20.json`.

The six English raw/enhanced input files matched the SHA-256 values in the uploaded incident package. An offline stub replay selected exactly 226 failed English records and only the one Chinese target. The Chinese source retained its original SHA-256 `bc61ca82f9c7a7c18657429ea4aa7ca75a362ca35df452087df078098df0ac51`; only line 42 changed in the temporary test candidate, and the other 58 lines remained byte-identical. All stub candidates were deleted; none are model-generated scientific summaries. Details are in `audits/validation-2026-10-21.json`.

The uploaded English package also reports 9,515 invalid records across 257 nonempty historical files, beginning January 30, and one empty August 18 file. This wider aggregate is evidence from the supplied package, not a repeated full-archive audit in this integration. Use `python -m ai.quality DATA_DIRECTORY --audit-history` to obtain the current full inventory before expanding recovery. An invalid earlier record does not prove that its cause was 401. Empty/missing raw dates require separate inventory reconstruction; do not fabricate summaries for unavailable source abstracts.

No live model generation, remote commit, PR, secret inspection or production-data change was performed here. The GitHub integration rejected the prior write attempt with HTTP 403 `Resource not accessible by integration`. This is separate from the model's 401. The owner must apply the code packages, configure an active DeepSeek key, and run/review the staged recoveries.
