#!/usr/bin/env bash
# One-time environment setup + verification gate.
# Usage: scripts/bootstrap.sh [--core-only]
set -euo pipefail
cd "$(dirname "$0")/.."

EXTRAS="dev,geo"
if [[ "${1:-}" == "--core-only" ]]; then EXTRAS="dev"; fi

if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install --upgrade pip
pip install -e ".[${EXTRAS}]"

ruff check src tests
pytest
python -m ii_hotspot --selftest

echo "bootstrap complete: environment verified."
