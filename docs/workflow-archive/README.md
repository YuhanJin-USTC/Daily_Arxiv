# Archived workflows

These files preserve the original workflow definitions byte for byte. They are reference material outside `.github/workflows`, so they are no longer dispatchable entrypoints. Existing Actions runs and their original workflow paths remain historical evidence.

| File | Original workflow path | Scope |
| --- | --- | --- |
| [backfill.yml](backfill.yml) | `.github/workflows/backfill.yml` | The reviewed 91-paper announcement inventory for **2026-10-20**, with its original six categories. It is not a general daily catch-up. |
| [recover.yml](recover.yml) | `.github/workflows/recover.yml` | Explicit archived-date or exact-ID AI repair. Its October 20 defaults and 59-row example describe the old incident, not current repair instructions. |
| [browser-check.yml](browser-check.yml) | `.github/workflows/browser-check.yml` | The former standalone deployed-site check. Its implementation remains in `scripts/check_live_site.cjs`. |

## Current entrypoints

Daily, Tests, Deploy website and Refresh researcher highlights remain the regular workflows. [Maintenance](../../.github/workflows/release-check.yml) retains the existing `release-check.yml` path and workflow identity. Its five explicit actions are `browser`, `crawl`, `ai`, `smtp-auth` and `recipient-mail`.

Maintenance `ai` accepts one source-bound post-baseline paper ID; it does not repair history. `smtp-auth` only checks authentication. `recipient-mail` uses the existing fixed recipient test scope and skips sent or cancelled tests. The original release workflow's initial-mail and sender-rebind actions remain in Git history; their guarded CLI operations remain in `scripts/release_probe.py`. See [bilingual operations](../bilingual-operation.md) for current usage.

## Offline inspection

Run these commands from the source checkout using its installed dependencies. Replace `DATA_CHECKOUT` with a separate checkout of the `data` branch. The date below is an explicit historical audit example. These commands do not need model or SMTP credentials and do not generate, publish or send anything.

```bash
.venv/bin/python -m ai.recover --help
.venv/bin/python scripts/resume_artifact.py --help
.venv/bin/python scripts/stage_daily.py --help
.venv/bin/python scripts/apply_staged.py --help
.venv/bin/python scripts/release_probe.py --help

.venv/bin/python -m ai.recover --source DATA_CHECKOUT/data \
  --language English --start 2026-10-20 --end 2026-10-20
```

Choose `Chinese` explicitly when auditing that edition. `ai.recover` generates only with `--generate`. In contrast, `stage_daily.py` is a generation command when invoked with working inputs; it has no audit-only mode. The archived backfill workflow and `resume_artifact.py` append mode both depend on `docs/audits/arxiv-2026-10-20.json`. Changing a date argument does not turn that inventory into coverage for another date.

## Reusing a historical artifact

Downloading an artifact does not validate its origin or contents. Before reusing it:

1. Query the run in the intended repository. Confirm `head_repository.full_name` equals that repository and `path` is the exact original `.github/workflows/recover.yml` or `.github/workflows/backfill.yml`, as appropriate. For audit-only metadata reuse, also require `conclusion == success`. A failed generation run can still contain useful checkpoints; success alone does not validate a candidate.
2. Match the run ID and exact artifact name: `arxiv-recovery-RUN-ATTEMPT` for repairs or `arxiv-backfill-RUN-ATTEMPT` for append work. Download into a new directory, keeping the original artifact unchanged. The archived YAML contains the original GitHub checks and download steps.
3. Use the same explicit `GITHUB_REPOSITORY`, language, dates, IDs and count constraint as the saved request. Run `resume_artifact.py` to verify the request, model profile, prompt hashes, source hashes and checkpoint bindings before any paid generation. The tool validates local bindings and paths; it does not independently query GitHub to prove repository or workflow origin.
4. Keep metadata-only reuse separate from checkpoint resume. It requires a successful audit-only backfill artifact with matching inventory, raw and coverage hashes. Generated or partial work must use checkpoint recovery, not the metadata shortcut.
5. Review the resulting manifest and verify a completed candidate before applying it to a separate data checkout. A downloaded directory or incomplete manifest is not permission to publish.

For example, after the origin checks above, validate a repair artifact locally with the original request values. `NEW_AUDIT` must be a new directory separate from `ARTIFACT_DIR` and the data checkout:

```bash
GITHUB_REPOSITORY=YuhanJin-USTC/daily-arxiv \
  .venv/bin/python scripts/resume_artifact.py --kind repair \
  --source DATA_CHECKOUT --output NEW_AUDIT --resume ARTIFACT_DIR \
  --run-id RUN_ID --name ARTIFACT_NAME \
  --language English --start 2026-10-20 --end 2026-10-20

.venv/bin/python scripts/apply_staged.py --source DATA_CHECKOUT \
  --staged COMPLETE_CANDIDATE --verify-only
```

Use the artifact's original repository identity; cross-repository reuse is not implied by this example. Supply its original `--ids` and `--expected-count` when present. The first command validates and writes local request evidence without calling a model; the second verifies an already completed candidate without applying it.

Retain sourced partial checkpoints, accepted fields, raw snapshots, manifests and their origin evidence. Do not discard them as temporary files or edit their hashes to bypass a mismatch. Historical repairs preserve healthy bytes and metadata; historical additions require an explicit baseline review and must not reset live discoveries, paid results, notification state or release probes. History never enters automatic AI or email backfill.
