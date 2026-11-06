#!/usr/bin/env bash
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
cd -- "$(dirname -- "$0")"
if [[ -n "${CONTROLLER_PYTHON:-}" ]]; then
    python="$CONTROLLER_PYTHON"
elif [[ -x .venv/bin/python ]]; then
    python=.venv/bin/python
else
    python=python3
fi
exec "$python" -m controller.main "$SIM_URL"
