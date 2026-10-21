#!/usr/bin/env bash
# Local staging only: bash run.sh /path/to/data-checkout /path/to/new-output
set -euo pipefail
cd "$(dirname "$0")"
if [ "$#" -ne 2 ]; then
  echo 'Usage: ./run.sh DATA_BRANCH_CHECKOUT NEW_OUTPUT_DIRECTORY'
  exit 2
fi
source_checkout=$(realpath "$1")
output=$(realpath -m "$2")
if [ -e "$output" ]; then echo 'Output must be a new directory'; exit 1; fi
mkdir -p "$output"
day=$(date -u +%F)
uv run --frozen python daily_arxiv/crawl.py --history-dir "$source_checkout/data" \
  --output "$output/$day.jsonl" --audit "$output/coverage.json"
if [ ! -s "$output/$day.jsonl" ]; then echo 'No unpublished papers'; exit 0; fi
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo 'Crawl complete. Model credentials unavailable; AI generation was not run.'
  exit 0
fi
uv run --frozen python scripts/stage_daily.py --source "$source_checkout" \
  --raw "$output/$day.jsonl" --date "$day" --output "$output/ready"
echo 'Complete candidate staged. Apply only after review; the data checkout is unchanged.'
