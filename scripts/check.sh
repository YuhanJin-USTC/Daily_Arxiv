#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

arxiv_uv=${ARXIV_UV:-uv}
arxiv_node=${ARXIV_NODE:-node}
arxiv_actionlint=${ARXIV_ACTIONLINT:-actionlint}

for tool in "$arxiv_uv" "$arxiv_node" "$arxiv_actionlint" git; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing check tool: $tool" >&2
    exit 1
  fi
done
if [ ! -x .venv/bin/python ]; then
  echo 'Missing .venv/bin/python; prepare dependencies with uv sync --frozen.' >&2
  exit 1
fi
"$arxiv_node" -e 'if (Number(process.versions.node.split(".")[0]) < 22) {
  console.error("Node.js 22 or newer is required."); process.exit(1);
}'
actionlint_version=$("$arxiv_actionlint" -version)
if [ "${actionlint_version%%$'\n'*}" != 1.7.12 ]; then
  echo 'actionlint 1.7.12 is required; set ARXIV_ACTIONLINT to its executable.' >&2
  exit 1
fi

export PYTHONDONTWRITEBYTECODE=1
"$arxiv_uv" lock --check --offline --no-cache --no-python-downloads
run_python() {
  "$arxiv_uv" run --offline --frozen --no-sync --no-cache --no-python-downloads python -B "$@"
}
run_python -m ruff check --no-cache ai daily_arxiv scripts to_md tests
run_python -m ruff format --check --no-cache ai daily_arxiv scripts to_md tests
run_python -m unittest discover -s tests -v
"$arxiv_node" --test tests/*.cjs
for script in run.sh scripts/check.sh; do
  bash -n "$script"
done
"$arxiv_actionlint" -shellcheck= -pyflakes= .github/workflows/*.yml
git diff --check
