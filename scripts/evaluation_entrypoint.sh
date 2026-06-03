#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

AS_OF_DATE="${AS_OF_DATE:-$(date +%Y%m%d)}"
SEND_EVAL_EMAIL="${SEND_EVAL_EMAIL:-0}"

echo "=== Evaluation EntryPoint ==="
echo "AS_OF_DATE=${AS_OF_DATE}"
echo "SEND_EVAL_EMAIL=${SEND_EVAL_EMAIL}"
echo ""

# ── [1/4] Scheduler Check ──
echo "[1/4] Scheduler check"

CHECK_FILE="reports/evaluation/evaluation_scheduler_check_${AS_OF_DATE}.json"
mkdir -p reports/evaluation

PYTHONIOENCODING=utf-8 python -m analysis.evaluation_scheduler_check --as-of "$AS_OF_DATE" --json > "$CHECK_FILE"

STATUS=$(PYTHONIOENCODING=utf-8 python -c "import json; print(json.load(open('$CHECK_FILE', encoding='utf-8')).get('status','error'))")
SIGNAL_DATE=$(PYTHONIOENCODING=utf-8 python -c "import json; print(json.load(open('$CHECK_FILE', encoding='utf-8')).get('signal_date',''))")

echo "status=${STATUS}"
echo "signal_date=${SIGNAL_DATE}"

if [ "$STATUS" = "skip" ]; then
    echo "[SKIP] Scheduler check returned skip, exiting."
    exit 0
fi

if [ "$STATUS" = "defer" ]; then
    echo "[DEFER] Scheduler check returned defer, price cache not ready. Exiting without evaluation."
    exit 0
fi

if [ "$STATUS" = "error" ]; then
    echo "[ERROR] Scheduler check returned error, exiting."
    exit 1
fi

if [ -z "$SIGNAL_DATE" ]; then
    echo "[ERROR] SIGNAL_DATE is empty, cannot continue."
    exit 1
fi

echo ""

# ── [2/4] Run watchlist_evaluation ──
echo "[2/4] Run watchlist_evaluation --save-db"

python -m analysis.watchlist_evaluation \
    --mode daily \
    --signal-date "$SIGNAL_DATE" \
    --as-of "$AS_OF_DATE" \
    --save-db

echo ""

# ── [3/4] Query latest evaluation ──
echo "[3/4] Query latest evaluation"

python -m analysis.evaluation_query --latest

echo ""

# ── [4/4] Evaluation email ──
echo "[4/4] Evaluation email"

if [ "$SEND_EVAL_EMAIL" = "1" ]; then
    python -m analysis.evaluation_email_sender --latest
else
    echo "[INFO] SEND_EVAL_EMAIL != 1, dry-run only"
    python -m analysis.evaluation_email_sender --latest --dry-run
fi

echo ""
echo "[DONE] evaluation workflow completed."
