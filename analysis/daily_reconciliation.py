"""Reconcile one trading day's report, signal, K-line and evaluation facts."""
from __future__ import annotations

import argparse
import json
from datetime import date

import psycopg2

from analysis.evaluation_time import resolve_evaluation_horizons
from analysis.evaluation_status import resolve_evaluation_status
from analysis.trade_calendar import get_calendar_status, normalize_trade_date
from data.config import DATABASE_DSN


def _connect():
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    return psycopg2.connect(DATABASE_DSN)


def _sql_date(value):
    text = normalize_trade_date(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _count(cur, sql, params):
    cur.execute(sql, params)
    return int(cur.fetchone()[0] or 0)


def _report_status(report_count):
    return "success" if report_count == 1 else ("missing" if not report_count else "duplicate")


def _email_status(success_count, attempt_count):
    return "success" if success_count else ("missing" if attempt_count else "unknown")


def _overall_status(statuses, deferred_statuses):
    hard = {"missing", "duplicate", "identity_mismatch", "blocked"}
    if any(status in hard for status in statuses):
        return "failed"
    if "failed" in statuses:
        return "failed"
    if "degraded" in statuses:
        return "degraded"
    return "deferred" if "deferred" in deferred_statuses else "success"


def reconcile_trade_date(trade_date, as_of_date=None, conn=None, persist=False):
    trade_text = normalize_trade_date(trade_date)
    as_of_text = normalize_trade_date(as_of_date or date.today())
    own_conn = conn is None
    db = conn or _connect()
    try:
        cur = db.cursor()
        calendar_status = get_calendar_status(trade_text, conn=db)
        raw_signal_count = _count(cur, "SELECT COUNT(*) FROM stock_signal WHERE trade_date=%s", (_sql_date(trade_text),))
        cur.execute(
            """
            SELECT COUNT(*), COUNT(snapshot_row_id), COUNT(evaluation_row_id),
                   COUNT(*) FILTER (WHERE snapshot_row_id IS NULL),
                   COUNT(*) FILTER (WHERE evaluation_row_id IS NULL)
            FROM canonical_signal_lineage
            WHERE trade_date=%s
            """,
            (_sql_date(trade_text),),
        )
        signal_count, snapshot_count, evaluation_count, missing_snapshot_count, missing_evaluation_count = [
            int(value or 0) for value in cur.fetchone()
        ]
        report_count = _count(cur, "SELECT COUNT(*) FROM daily_report WHERE trade_date=%s", (_sql_date(trade_text),))
        horizons = resolve_evaluation_horizons(trade_text, as_of_text)
        target_1d = horizons.get("t1_date")
        covered_count = 0
        if target_1d and signal_count:
            covered_count = _count(
                cur,
                """
                SELECT COUNT(*)
                FROM canonical_signal_lineage s
                WHERE s.trade_date=%s
                  AND EXISTS (
                      SELECT 1 FROM stock_hist_kline k
                      WHERE k.code=s.code AND k.trade_date=%s
                  )
                """,
                (_sql_date(trade_text), _sql_date(target_1d)),
            )
        coverage = covered_count / signal_count if signal_count else 0.0
        email_rows = _count(
            cur,
            """
            SELECT COUNT(*) FROM job_run_log
            WHERE trade_date=%s AND job_name IN ('daily_email','email_sender')
              AND status='success'
            """,
            (_sql_date(trade_text),),
        )
        email_attempt_rows = _count(
            cur,
            """
            SELECT COUNT(*) FROM job_run_log
            WHERE trade_date=%s AND job_name IN ('daily_email','email_sender')
            """,
            (_sql_date(trade_text),),
        )

        missing = []
        report_status = _report_status(report_count)
        signal_status = (
            "success" if signal_count > 0 and signal_count == raw_signal_count
            else "missing" if raw_signal_count == 0
            else "identity_mismatch"
        )
        snapshot_status = "success" if signal_count > 0 and missing_snapshot_count == 0 else "missing"
        if report_status != "success": missing.append("daily_report" if report_count == 0 else "daily_report_duplicate")
        if signal_status != "success": missing.append("stock_signal" if raw_signal_count == 0 else "stock_signal_identity")
        if snapshot_status != "success": missing.append("candidate_feature_snapshot_identity")

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE r.next_1d_return IS NOT NULL),
                COUNT(*) FILTER (
                    WHERE r.is_mature_3d IS TRUE AND r.next_3d_return IS NOT NULL
                )
            FROM canonical_signal_lineage l
            LEFT JOIN canonical_daily_evaluation_result r
              ON r.id=l.evaluation_row_id
            WHERE l.trade_date=%s
            """,
            (_sql_date(trade_text),),
        )
        evaluated_t1_count, evaluated_t3_count = [
            int(value or 0) for value in cur.fetchone()
        ]
        t1_evaluation = resolve_evaluation_status(
            mature=horizons.get("t1_mature", False),
            target_date=target_1d,
            as_of_date=as_of_text,
            eligible_count=signal_count,
            evaluated_count=evaluated_t1_count,
            execution_status="success" if evaluated_t1_count else "unknown",
        )
        t3_evaluation = resolve_evaluation_status(
            mature=horizons.get("t3_mature", False),
            target_date=horizons.get("t3_date"),
            as_of_date=as_of_text,
            eligible_count=signal_count,
            evaluated_count=evaluated_t3_count,
            execution_status="success" if evaluated_t3_count else "unknown",
        )
        t1_status = t1_evaluation["status"]
        t3_status = t3_evaluation["status"]
        kline_status = (
            "pending" if not horizons.get("t1_mature")
            else "success" if coverage >= 0.8
            else "deferred"
        )
        if t1_status in {"missing", "degraded", "failed"}:
            missing.append(f"evaluation_t1_{t1_evaluation['reason_code']}")
        if t3_status in {"missing", "degraded", "failed"}:
            missing.append(f"evaluation_t3_{t3_evaluation['reason_code']}")

        email_status = _email_status(email_rows, email_attempt_rows)
        if email_status == "missing": missing.append("daily_email")
        overall = _overall_status(
            (report_status, signal_status, snapshot_status, t1_status, t3_status, email_status),
            (kline_status, t1_status, t3_status),
        )
        result = {
            "trade_date": trade_text, "as_of_date": as_of_text,
            "calendar_status": calendar_status, "report_status": report_status,
            "signal_status": signal_status, "snapshot_status": snapshot_status,
            "kline_status": kline_status, "kline_coverage": round(coverage, 6),
            "evaluation_t1_status": t1_status, "evaluation_t3_status": t3_status,
            "email_status": email_status, "overall_status": overall,
            "signal_count": signal_count, "snapshot_count": snapshot_count,
            "evaluation_count": evaluation_count, "report_count": report_count,
            "missing_items": missing,
            "diagnostics": {
                "target_1d_date": target_1d,
                "target_3d_date": horizons.get("t3_date"),
                "covered_count": covered_count,
                "raw_signal_count": raw_signal_count,
                "missing_snapshot_identity_count": missing_snapshot_count,
                "missing_evaluation_identity_count": missing_evaluation_count,
                "expected_report_count": 1,
                "email_attempt_count": email_attempt_rows,
                "evaluation": {
                    "t1": t1_evaluation,
                    "t3": t3_evaluation,
                },
            },
        }
        if persist:
            cur.execute(
                """
                INSERT INTO daily_reconciliation (
                    trade_date,as_of_date,calendar_status,report_status,signal_status,
                    snapshot_status,kline_status,kline_coverage,evaluation_t1_status,
                    evaluation_t3_status,email_status,overall_status,signal_count,
                    snapshot_count,evaluation_count,report_count,missing_items_json,
                    diagnostics_json,checked_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,CURRENT_TIMESTAMP)
                ON CONFLICT (trade_date) DO UPDATE SET
                    as_of_date=EXCLUDED.as_of_date,calendar_status=EXCLUDED.calendar_status,
                    report_status=EXCLUDED.report_status,signal_status=EXCLUDED.signal_status,
                    snapshot_status=EXCLUDED.snapshot_status,kline_status=EXCLUDED.kline_status,
                    kline_coverage=EXCLUDED.kline_coverage,evaluation_t1_status=EXCLUDED.evaluation_t1_status,
                    evaluation_t3_status=EXCLUDED.evaluation_t3_status,email_status=EXCLUDED.email_status,
                    overall_status=EXCLUDED.overall_status,signal_count=EXCLUDED.signal_count,
                    snapshot_count=EXCLUDED.snapshot_count,evaluation_count=EXCLUDED.evaluation_count,
                    report_count=EXCLUDED.report_count,missing_items_json=EXCLUDED.missing_items_json,
                    diagnostics_json=EXCLUDED.diagnostics_json,checked_at=CURRENT_TIMESTAMP
                """,
                (_sql_date(trade_text),_sql_date(as_of_text),calendar_status,report_status,signal_status,
                 snapshot_status,kline_status,coverage,t1_status,t3_status,email_status,overall,
                 signal_count,snapshot_count,evaluation_count,report_count,
                 json.dumps(missing,ensure_ascii=False),json.dumps(result["diagnostics"],ensure_ascii=False)),
            )
            db.commit()
        cur.close()
        return result
    finally:
        if own_conn:
            db.close()


def main():
    parser=argparse.ArgumentParser(description="Reconcile one daily pipeline date")
    parser.add_argument("--date")
    parser.add_argument("--days", type=int, default=0, help="Reconcile the latest N signal dates")
    parser.add_argument("--as-of")
    parser.add_argument("--apply", action="store_true")
    args=parser.parse_args()
    if not args.date and args.days <= 0:
        parser.error("either --date or --days is required")
    if args.date:
        result = reconcile_trade_date(args.date,args.as_of,persist=args.apply)
    else:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT trade_date FROM stock_signal ORDER BY trade_date DESC LIMIT %s",
                (args.days,),
            )
            dates = [row[0].strftime("%Y%m%d") for row in cur.fetchall()]
            cur.close()
        finally:
            conn.close()
        result = [
            reconcile_trade_date(item,args.as_of,persist=args.apply)
            for item in reversed(dates)
        ]
    print(json.dumps(result,ensure_ascii=False,indent=2))
    rows = result if isinstance(result, list) else [result]
    if any(item.get("overall_status") == "failed" for item in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
