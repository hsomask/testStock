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
    echo "[DEFER] Scheduler check returned defer, writing status file."
    # 写 status 文件供日报读取
    STATUS_FILE="reports/evaluation/evaluation_status_${AS_OF_DATE}.json"
    mkdir -p reports/evaluation
    PYTHONIOENCODING=utf-8 python -c "
import json
with open('$CHECK_FILE', encoding='utf-8') as f:
    sc = json.load(f)
status_data = {
    'available': False,
    'status': 'defer',
    'as_of_date': sc.get('as_of_date', '$AS_OF_DATE'),
    'signal_date': sc.get('signal_date', ''),
    'reason': 'observer_pool_price_not_ready',
    'message': '今日 T+1 复盘因观察池价格覆盖不足暂缓。',
    'coverage_scope': sc.get('coverage_scope', 'signal_pool'),
    'price_cache_coverage': sc.get('price_cache_coverage', 0),
    'total_signals': sc.get('signal_count', 0),
    'covered_signals': sc.get('price_cache_cached', 0),
    'missing_codes': sc.get('missing_codes', []),
}
with open('$STATUS_FILE', 'w', encoding='utf-8') as f:
    json.dump(status_data, f, ensure_ascii=False, indent=2)
print(f'Status file written: $STATUS_FILE')
"
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
