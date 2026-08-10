#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

AS_OF_DATE="${AS_OF_DATE:-$(date +%Y%m%d)}"
SEND_EVAL_EMAIL="${SEND_EVAL_EMAIL:-0}"
EVAL_TIME_BUDGET="${EVAL_TIME_BUDGET:-300}"
EVAL_DEEP="${EVAL_DEEP:-0}"
ML_DATASET_MIN_COVERAGE="${ML_DATASET_MIN_COVERAGE:-0.9}"
EVAL_V2_BACKFILL_DAYS="${EVAL_V2_BACKFILL_DAYS:-0}"

echo "=== Evaluation EntryPoint ==="
echo "AS_OF_DATE=${AS_OF_DATE}"
echo "SEND_EVAL_EMAIL=${SEND_EVAL_EMAIL}"
echo "EVAL_TIME_BUDGET=${EVAL_TIME_BUDGET}"
echo "EVAL_DEEP=${EVAL_DEEP}"
echo "ML_DATASET_MIN_COVERAGE=${ML_DATASET_MIN_COVERAGE}"
echo "EVAL_V2_BACKFILL_DAYS=${EVAL_V2_BACKFILL_DAYS}"
echo ""

echo "[0/4] Ensure evaluation schema"
python -m analysis.init_db
echo "[0a/4] Ensure persistent exchange calendar"
python -m analysis.trade_calendar_sync --ensure --future-days 400 --apply

if [ "$EVAL_V2_BACKFILL_DAYS" -gt 0 ]; then
    echo "[0b/4] Rebuild legacy T+1 lifecycle rows"
    python -m analysis.evaluation_v2_backfill \
        --as-of "$AS_OF_DATE" \
        --days "$EVAL_V2_BACKFILL_DAYS" \
        --apply
fi

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
EVALUATION_AS_OF_DATE=$(PYTHONIOENCODING=utf-8 python -c "import json; d=json.load(open('$CHECK_FILE', encoding='utf-8')); print(d.get('evaluation_as_of_date') or d.get('as_of_date',''))")

echo "status=${STATUS}"
echo "signal_date=${SIGNAL_DATE}"
echo "evaluation_as_of_date=${EVALUATION_AS_OF_DATE}"

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
    'evaluation_as_of_date': sc.get('evaluation_as_of_date', ''),
    'target_1d_date': sc.get('target_1d_date'),
    'target_3d_date': sc.get('target_3d_date'),
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
echo "[1b/4] Signal lineage pre-evaluation gate"
python -m analysis.signal_lineage_check --date "$SIGNAL_DATE" --strict

echo ""
echo "[2/4] Run watchlist_evaluation --save-db"

python -m analysis.watchlist_evaluation \
    --mode daily \
    --signal-date "$SIGNAL_DATE" \
    --as-of "$EVALUATION_AS_OF_DATE" \
    --save-db

echo ""
echo "[2a/4] Signal lineage post-evaluation gate"
python -m analysis.signal_lineage_check --date "$SIGNAL_DATE" --strict

echo ""
echo "[2b/4] Patch mature T+3 fields"
python -m analysis.evaluation_maturity_backfill --as-of "$AS_OF_DATE" --days 30 --apply

echo ""
echo "[2c/4] Update strategy feedback"
python -m analysis.strategy_feedback --date "$AS_OF_DATE" --window 20

echo ""
echo "[2d/4] Update context feedback"
set +e
python -m analysis.context_feedback --as-of "$AS_OF_DATE" --window 20
CTX_STATUS=$?
set -e
if [ "$CTX_STATUS" -ne 0 ]; then
    echo "[WARN] context feedback failed, continue evaluation workflow."
fi

echo ""
echo "[2e/4] Check candidate snapshot integrity"
set +e
python -m analysis.snapshot_integrity_check --date "$SIGNAL_DATE"
SNAPSHOT_STATUS=$?
set -e
if [ "$SNAPSHOT_STATUS" -ne 0 ]; then
    echo "[WARN] snapshot integrity check failed, continue evaluation workflow."
fi

echo ""
echo "[2f/4] Build ML dataset sidecar"
set +e
python -m analysis.ml_dataset_builder --as-of "$AS_OF_DATE" --min-coverage "$ML_DATASET_MIN_COVERAGE"
ML_STATUS=$?
set -e
if [ "$ML_STATUS" -ne 0 ]; then
    echo "[WARN] ML dataset builder failed, continue evaluation workflow."
fi

echo ""
echo "[2g/4] Audit correction effectiveness"
set +e
python -m analysis.correction_effectiveness --as-of "$AS_OF_DATE" --min-coverage 0.8
CORRECTION_STATUS=$?
set -e
if [ "$CORRECTION_STATUS" -ne 0 ]; then
    echo "[WARN] correction effectiveness audit failed, continue evaluation workflow."
fi

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
