#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

AS_OF_DATE="${AS_OF_DATE:-$(date +%Y%m%d)}"
SEND_EVAL_EMAIL="${SEND_EVAL_EMAIL:-0}"
EVAL_TIME_BUDGET="${EVAL_TIME_BUDGET:-300}"
EVAL_DEEP="${EVAL_DEEP:-0}"

echo "=== Evaluation EntryPoint ==="
echo "AS_OF_DATE=${AS_OF_DATE}"
echo "SEND_EVAL_EMAIL=${SEND_EVAL_EMAIL}"
echo "EVAL_TIME_BUDGET=${EVAL_TIME_BUDGET}"
echo "EVAL_DEEP=${EVAL_DEEP}"
echo ""

echo "[1/4] Scheduler check and K-line coverage guard"

CHECK_FILE="reports/evaluation/evaluation_scheduler_check_${AS_OF_DATE}.json"
STATUS_FILE="reports/evaluation/evaluation_status_${AS_OF_DATE}.json"
mkdir -p reports/evaluation

DEEP_FLAG=""
if [ "$EVAL_DEEP" = "1" ]; then
    DEEP_FLAG="--deep"
fi

PYTHONIOENCODING=utf-8 python -m analysis.evaluation_scheduler_check \
    --as-of "$AS_OF_DATE" \
    --time-budget "$EVAL_TIME_BUDGET" \
    $DEEP_FLAG \
    --json > "$CHECK_FILE"

STATUS=$(PYTHONIOENCODING=utf-8 python -c "import json; print(json.load(open('$CHECK_FILE', encoding='utf-8')).get('status','error'))")
SIGNAL_DATE=$(PYTHONIOENCODING=utf-8 python -c "import json; print(json.load(open('$CHECK_FILE', encoding='utf-8')).get('signal_date',''))")

echo "status=${STATUS}"
echo "signal_date=${SIGNAL_DATE}"

if [ "$STATUS" = "skip" ]; then
    echo "[SKIP] Scheduler check returned skip, exiting."
    exit 0
fi

if [ "$STATUS" = "error" ]; then
    echo "[ERROR] Scheduler check returned error, exiting."
    exit 1
fi

PYTHONIOENCODING=utf-8 python -c "
import json
with open('$CHECK_FILE', encoding='utf-8') as f:
    sc = json.load(f)

coverage = sc.get('price_cache_coverage', 0) or 0
is_defer = sc.get('status') == 'defer'
defer_reason = sc.get('defer_reason', '') or ('observer_pool_price_not_ready' if is_defer else '')

if is_defer:
    message = sc.get('message') or '今日 T+1 复盘因观察池价格覆盖不足暂缓。'
else:
    message = '正式 evaluation 已满足 K 线覆盖门槛。'

status_data = {
    'available': not is_defer,
    'status': 'defer' if is_defer else ('ready' if coverage >= 0.9 else 'low_weight'),
    'as_of_date': sc.get('as_of_date', '$AS_OF_DATE'),
    'signal_date': sc.get('signal_date', ''),
    'reason': defer_reason,
    'message': message,
    'coverage_scope': sc.get('coverage_scope', 'signal_pool'),
    'price_cache_coverage': coverage,
    'total_signals': sc.get('price_cache_signal_total', sc.get('signal_count', 0)),
    'covered_signals': sc.get('price_cache_cached', 0),
    'attempted_fill': sc.get('attempted_fill', 0),
    'fill_success': sc.get('fill_success', 0),
    'coverage_level': sc.get('coverage_level', 'defer'),
    'quality_weight': sc.get('quality_weight', 0),
    'reason_counts': sc.get('reason_counts', {}),
    'strategy_coverage': sc.get('strategy_coverage', []),
    'risk_coverage': sc.get('risk_coverage', []),
    'layer_coverage': sc.get('layer_coverage', []),
    'upstream_lag_codes': sc.get('upstream_lag_codes', []),
    'upstream_lag_note': sc.get('upstream_lag_note', ''),
    'suspended_or_no_trade_codes': sc.get('suspended_or_no_trade_codes', []),
    'missing_codes': sc.get('missing_codes', []),
    'learning_eligible': (not is_defer) and coverage >= 0.9,
    'learning_weight': 0 if is_defer else sc.get('quality_weight', 0),
}
with open('$STATUS_FILE', 'w', encoding='utf-8') as f:
    json.dump(status_data, f, ensure_ascii=False, indent=2)
print(f'Status file written: $STATUS_FILE')
"

if [ "$STATUS" = "defer" ]; then
    echo "[DEFER] K-line coverage is below 80%, formal evaluation is skipped."
    exit 0
fi

if [ -z "$SIGNAL_DATE" ]; then
    echo "[ERROR] SIGNAL_DATE is empty, cannot continue."
    exit 1
fi

echo ""
echo "[2/4] Run watchlist_evaluation --save-db"

python -m analysis.watchlist_evaluation \
    --mode daily \
    --signal-date "$SIGNAL_DATE" \
    --as-of "$AS_OF_DATE" \
    --save-db

echo ""
echo "[2b/4] Update strategy feedback"
python -m analysis.strategy_feedback --date "$AS_OF_DATE" --window 20

echo ""
echo "[3/4] Query latest evaluation"
python -m analysis.evaluation_query --latest

echo ""
echo "[4/4] Evaluation email"

if [ "$SEND_EVAL_EMAIL" = "1" ]; then
    python -m analysis.evaluation_email_sender --latest
else
    echo "[INFO] SEND_EVAL_EMAIL != 1, dry-run only"
    python -m analysis.evaluation_email_sender --latest --dry-run
fi

echo ""
echo "[DONE] evaluation workflow completed."
