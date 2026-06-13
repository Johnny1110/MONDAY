#!/usr/bin/env bash
# Run the Monday engine test suite. Prefers the venv's pytest; falls back to stdlib unittest
# (the pure-logic suite — the pipeline smoke auto-skips without pyarrow/pydantic-settings).
set -euo pipefail
cd "$(dirname "$0")/../engine"
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m pytest -q "$@"
fi
echo "no .venv — running stdlib unittest (pure-logic suite only)"
exec python3 -m unittest discover -s tests -t .
