#!/usr/bin/env bash
# Full production run: gate -> pipeline -> deliverables.
# Usage: scripts/run_pipeline.sh configs/<municipality>.toml
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG="${1:?usage: scripts/run_pipeline.sh <pilot.toml>}"
: "${KNMI_API_KEY:?KNMI_API_KEY is not set (free key: developer.dataplatform.knmi.nl)}"

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python -m ii_hotspot --selftest
python -m ii_hotspot --run --config "$CONFIG"
