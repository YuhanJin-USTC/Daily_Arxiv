#!/usr/bin/env bash
# Local candidates only; publication and mail require separate commands.
set -euo pipefail
cd "$(dirname "$0")"
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ] || { [ "$#" -eq 3 ] && [ "$3" != --generate ]; }; then
  echo 'Usage: ./run.sh DATA_BRANCH_CHECKOUT NEW_OUTPUT_DIRECTORY [--generate]'
  exit 2
fi
arxiv_python=${ARXIV_PYTHON:-.venv/bin/python}
if [ ! -x "$arxiv_python" ]; then
  echo 'Install locked dependencies or set ARXIV_PYTHON.'
  exit 1
fi
source_checkout=$(realpath "$1")
output=$(realpath -m "$2")
if [ -e "$output" ]; then echo 'Output must be a new directory'; exit 1; fi
case "$output/" in
  "$source_checkout/"*) echo 'Output must be outside the data checkout'; exit 1 ;;
esac
mkdir -p "$output"
day=$(date -u +%F)
"$arxiv_python" daily_arxiv/crawl.py --history-dir "$source_checkout/data" \
  --output "$output/$day.jsonl" --audit "$output/coverage.json"
"$arxiv_python" - "$source_checkout" "$output/candidate" <<'PYTHON'
from pathlib import Path
import shutil
import sys
source, target = map(Path, sys.argv[1:])
target.mkdir()
for name in ("data", "assets"):
    if (source / name).exists():
        shutil.copytree(source / name, target / name)
PYTHON
"$arxiv_python" scripts/daily_update.py raw --source "$output/candidate" \
  --raw "$output/$day.jsonl" --coverage "$output/coverage.json" --date "$day" \
  --output "$output/raw-ready"
failed=0
if [ "${3:-}" = --generate ]; then
  for language in English Chinese; do
    "$arxiv_python" scripts/daily_update.py ai --source "$output/candidate" \
      --language "$language" --output "$output/$language" || failed=1
  done
fi
echo "Review candidate at $output/candidate; nothing published or emailed."
exit "$failed"
