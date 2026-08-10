#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
TRADE_DATE="${TRADE_DATE:-$(date +%Y%m%d)}"
export TRADE_DATE

SEND_DAILY_EMAIL=0 TRADE_DATE="$TRADE_DATE" bash entrypoint.sh

set +e
AS_OF_DATE="$TRADE_DATE" SEND_EVAL_EMAIL=0 bash scripts/evaluation_entrypoint.sh
EVAL_STATUS=$?
set -e
if [ "$EVAL_STATUS" -ne 0 ]; then
    echo "[WARN] evaluation entrypoint failed; continue legacy report rendering."
fi

python -m analysis.daily_report --date "$TRADE_DATE" --mode both
python -m analysis.email_sender --date "$TRADE_DATE"
python -m analysis.daily_reconciliation --days 10 --as-of "$TRADE_DATE" --apply
