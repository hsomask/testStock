#!/usr/bin/env bash
set -euo pipefail

echo "=================================================="
echo "Daily Report With Evaluation"
echo "=================================================="

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TRADE_DATE="${TRADE_DATE:-$(date +%Y%m%d)}"
export TRADE_DATE

echo "TRADE_DATE=$TRADE_DATE"
echo "=================================================="

echo ""
echo "[1/4] Run daily pipeline without email"
SEND_DAILY_EMAIL=0 TRADE_DATE="$TRADE_DATE" bash entrypoint.sh

echo ""
echo "[2/4] Run evaluation without email"
set +e
AS_OF_DATE="$TRADE_DATE" SEND_EVAL_EMAIL=0 bash scripts/evaluation_entrypoint.sh
EVAL_STATUS=$?
set -e
if [ "$EVAL_STATUS" -ne 0 ]; then
    echo "[WARN] evaluation_entrypoint failed or deferred, continue daily report rendering."
fi

echo ""
echo "[3/4] Re-render daily report with evaluation summary"
python -m analysis.daily_report --date "$TRADE_DATE" --mode both

echo ""
echo "[4/4] Send daily email"
python -m analysis.email_sender --date "$TRADE_DATE"

echo ""
echo "[DONE] daily report with evaluation completed."
