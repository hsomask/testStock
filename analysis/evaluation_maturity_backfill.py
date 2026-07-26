"""Safely patch mature T+3 fields without rewriting frozen T+1 facts.

Dry-run is the default:
  python -m analysis.evaluation_maturity_backfill --as-of 20260725
Apply after reviewing:
  python -m analysis.evaluation_maturity_backfill --as-of 20260725 --apply
"""
import argparse
import json
import uuid
from datetime import datetime
from pathlib import Path

import psycopg2

from analysis.evaluation_time import EVALUATION_SCHEMA_VERSION
from analysis.watchlist_evaluation import (
    aggregate_metrics,
    evaluate_records,
    fetch_signals_for_date,
    prime_history_cache_from_db,
)
from data.config import DATABASE_DSN, REPORT_DIR


T1_IMMUTABLE_COLUMNS = {
    "entry_close",
    "next_1d_return",
    "verification_tag",
    "feedback_label",
    "feedback_score",
    "attribution_tags",
    "attribution_text",
    "t1_evaluated_at",
}
T3_PATCH_COLUMNS = {
    "next_3d_return",
    "max_3d_return",
    "max_3d_drawdown",
    "is_mature_3d",
    "target_3d_date",
    "t3_price_status",
    "t3_missing_reason",
    "verification_tag_3d",
    "feedback_label_3d",
    "feedback_score_3d",
    "attribution_tags_3d",
    "attribution_text_3d",
    "t3_evaluated_at",
}


def build_t3_patch(detail):
    status = detail.get("status") or {}
    metrics = detail.get("metrics") or {}
    missing = [
        reason for reason in status.get("missing_reasons", [])
        if reason in ("missing_t3_window_price", "not_mature_3d", "price_fetch_failed")
    ]
    return {
        "next_3d_return": metrics.get("next_3d_return"),
        "max_3d_return": metrics.get("max_3d_return"),
        "max_3d_drawdown": metrics.get("max_3d_drawdown"),
        "is_mature_3d": bool(status.get("eligible_3d")),
        "target_3d_date": status.get("target_3d_date"),
        "t3_price_status": "ok" if status.get("evaluated_3d") else "missing",
        "t3_missing_reason": missing[0] if missing else None,
        "verification_tag_3d": detail.get("verification_tag_3d"),
        "feedback_label_3d": detail.get("feedback_label_3d"),
        "feedback_score_3d": detail.get("feedback_score_3d"),
        "attribution_tags_3d": detail.get("attribution_tags_3d") or [],
        "attribution_text_3d": detail.get("attribution_text_3d"),
    }


def load_targets(conn, as_of_date, days):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT signal_date, as_of_date, target_3d_date, total_signals,
               COALESCE(evaluated_3d, 0)
        FROM watchlist_evaluation_summary
        WHERE eval_mode = 'daily'
          AND evaluation_schema_version = %s
          AND target_3d_date IS NOT NULL
          AND target_3d_date <= %s
          AND (
              COALESCE(evaluated_3d, 0) < COALESCE(total_signals, 0)
              OR summary_json->>'evaluated_3d' IS DISTINCT FROM COALESCE(evaluated_3d, 0)::text
              OR EXISTS (
                  SELECT 1
                  FROM watchlist_evaluation_result r
                  WHERE r.eval_mode = 'daily'
                    AND r.evaluation_schema_version = %s
                    AND r.signal_trade_date = watchlist_evaluation_summary.signal_date
                    AND r.as_of_date = watchlist_evaluation_summary.as_of_date
                    AND (
                        r.feedback_label_3d = 'data_insufficient'
                        OR r.verification_tag_3d = 'insufficient'
                    )
              )
          )
        ORDER BY signal_date DESC
        LIMIT %s
        """,
        (EVALUATION_SCHEMA_VERSION, as_of_date, EVALUATION_SCHEMA_VERSION, int(days)),
    )
    rows = cur.fetchall()
    cur.close()
    return [
        {
            "signal_date": row[0],
            "anchor_date": row[1],
            "target_3d_date": row[2],
            "total_signals": int(row[3] or 0),
            "evaluated_3d_before": int(row[4] or 0),
        }
        for row in rows
    ]


def _apply_target(conn, target, records, overall, as_of_date, run_id=None):
    cur = conn.cursor()
    updated = 0
    for detail in records:
        patch = build_t3_patch(detail)
        cur.execute(
            """
            UPDATE watchlist_evaluation_result
            SET next_3d_return = COALESCE(next_3d_return, %s),
                max_3d_return = COALESCE(max_3d_return, %s),
                max_3d_drawdown = COALESCE(max_3d_drawdown, %s),
                is_mature_3d = %s,
                target_3d_date = COALESCE(target_3d_date, %s),
                t3_price_status = %s,
                t3_missing_reason = %s,
                verification_tag_3d = CASE
                    WHEN verification_tag_3d IS NULL OR verification_tag_3d = 'insufficient'
                    THEN %s ELSE verification_tag_3d END,
                feedback_label_3d = CASE
                    WHEN feedback_label_3d IS NULL OR feedback_label_3d = 'data_insufficient'
                    THEN %s ELSE feedback_label_3d END,
                feedback_score_3d = COALESCE(feedback_score_3d, %s),
                attribution_tags_3d = CASE
                    WHEN feedback_label_3d IS NULL OR feedback_label_3d = 'data_insufficient'
                    THEN %s::jsonb ELSE attribution_tags_3d END,
                attribution_text_3d = CASE
                    WHEN feedback_label_3d IS NULL OR feedback_label_3d = 'data_insufficient'
                    THEN %s ELSE attribution_text_3d END,
                t3_evaluated_at = CASE WHEN %s = 'ok'
                    THEN COALESCE(t3_evaluated_at, NOW()) ELSE t3_evaluated_at END,
                t3_run_id = %s,
                evaluated_at = NOW()
            WHERE eval_mode = 'daily'
              AND evaluation_schema_version = %s
              AND signal_trade_date = %s
              AND as_of_date = %s
              AND signal_key = %s
            """,
            (
                patch["next_3d_return"],
                patch["max_3d_return"],
                patch["max_3d_drawdown"],
                patch["is_mature_3d"],
                patch["target_3d_date"],
                patch["t3_price_status"],
                patch["t3_missing_reason"],
                patch["verification_tag_3d"],
                patch["feedback_label_3d"],
                patch["feedback_score_3d"],
                json.dumps(patch["attribution_tags_3d"], ensure_ascii=False),
                patch["attribution_text_3d"],
                patch["t3_price_status"],
                run_id,
                EVALUATION_SCHEMA_VERSION,
                target["signal_date"],
                target["anchor_date"],
                detail["signal_key"],
            ),
        )
        updated += cur.rowcount

    total = target["total_signals"]
    evaluated_3d = sum(1 for row in records if row.get("status", {}).get("evaluated_3d"))
    metrics = overall.get("__all__", {})
    cur.execute(
        """
        UPDATE watchlist_evaluation_summary
        SET eligible_3d = %s,
            evaluated_3d = %s,
            coverage_3d = %s,
            avg_next_3d_return = %s,
            win_rate_3d = %s,
            avg_max_3d_return = %s,
            avg_max_3d_drawdown = %s,
            summary_json = COALESCE(summary_json, '{}'::jsonb)
                || jsonb_build_object(
                    'eligible_3d', %s,
                    'evaluated_3d', %s,
                    'coverage_3d', %s
                ),
            diagnostics_json = jsonb_set(
                jsonb_set(
                    jsonb_set(
                        COALESCE(diagnostics_json, '{}'::jsonb),
                        '{data_quality,eligible_3d}', to_jsonb(%s::integer), true
                    ),
                    '{data_quality,evaluated_3d}', to_jsonb(%s::integer), true
                ),
                '{data_quality,coverage_3d}', to_jsonb(%s::numeric), true
            ),
            evaluation_phase = 't1+t3',
            run_as_of_date = %s,
            t3_updated_at = NOW(),
            t3_run_id = %s,
            generated_at = NOW()
        WHERE eval_mode = 'daily'
          AND evaluation_schema_version = %s
          AND signal_date = %s
          AND as_of_date = %s
        """,
        (
            total,
            evaluated_3d,
            evaluated_3d / total if total else 0,
            metrics.get("avg_next_3d_return"),
            metrics.get("win_rate_3d"),
            metrics.get("avg_max_3d_return"),
            metrics.get("avg_max_3d_drawdown"),
            total,
            evaluated_3d,
            evaluated_3d / total if total else 0,
            total,
            evaluated_3d,
            evaluated_3d / total if total else 0,
            as_of_date,
            run_id,
            EVALUATION_SCHEMA_VERSION,
            target["signal_date"],
            target["anchor_date"],
        ),
    )
    cur.close()
    return updated


def run(as_of_date, days=30, apply=False):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN 未配置")
    conn = psycopg2.connect(DATABASE_DSN)
    run_id = str(uuid.uuid4())
    try:
        targets = load_targets(conn, as_of_date, days)
        cleared_placeholders = 0
        if apply:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE watchlist_evaluation_result
                SET verification_tag_3d = NULL,
                    feedback_label_3d = NULL,
                    feedback_score_3d = NULL,
                    attribution_tags_3d = NULL,
                    attribution_text_3d = NULL
                WHERE evaluation_schema_version = %s
                  AND COALESCE(is_mature_3d, FALSE) = FALSE
                  AND next_3d_return IS NULL
                  AND feedback_label_3d = 'data_insufficient'
                """,
                (EVALUATION_SCHEMA_VERSION,),
            )
            cleared_placeholders = cur.rowcount
            cur.close()
        results = []
        for target in targets:
            signals = fetch_signals_for_date(conn, target["signal_date"])
            prime_history_cache_from_db(conn, [signal.get("code") for signal in signals])
            records, _, _, _, evaluated_3d, _ = evaluate_records(
                signals,
                as_of_date=as_of_date,
                horizon="t3",
            )
            overall = aggregate_metrics(records)
            updated = 0
            if apply:
                updated = _apply_target(
                    conn, target, records, overall, as_of_date, run_id
                )
            results.append({
                **target,
                "evaluated_3d_after": evaluated_3d,
                "detail_rows_to_patch": len(records),
                "updated_rows": updated,
            })
        if apply:
            conn.commit()
        else:
            conn.rollback()
        return {
            "status": "ok",
            "mode": "apply" if apply else "dry_run",
            "as_of_date": as_of_date,
            "run_id": run_id,
            "target_count": len(targets),
            "targets": results,
            "t1_columns_touched": [],
            "cleared_unmatured_placeholders": cleared_placeholders,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="T+3成熟补齐（默认dry-run）")
    parser.add_argument("--as-of", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()
    result = run(args.as_of, days=args.days, apply=args.apply)
    out_dir = Path(REPORT_DIR) / "evaluation"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"evaluation_maturity_{args.as_of}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
