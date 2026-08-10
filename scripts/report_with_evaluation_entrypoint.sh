#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
TRADE_DATE="${TRADE_DATE:-$(date +%Y%m%d)}"

if [ "${USE_LEGACY_PIPELINE:-0}" = "1" ]; then
    echo "[WARN] USE_LEGACY_PIPELINE=1; running compatibility entrypoint."
    exec bash scripts/report_with_evaluation_legacy_entrypoint.sh
fi

exec python -m analysis.pipeline_runner --date "$TRADE_DATE"
