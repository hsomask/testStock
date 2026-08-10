"""Reconcile one trading day's report, signal, K-line and evaluation facts."""
from __future__ import annotations

import argparse
import json
from datetime import date

import psycopg2

from analysis.evaluation_time import resolve_evaluation_horizons
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


def reconcile_trade_date(trade_date, as_of_date=None, conn=None, persist=False):
    trade_text = normalize_trade_date(trade_date)
    as_of_text = normalize_trade_date(as_of_date or date.today())
    own_conn = conn is None
    db = conn or _connect()
    try:
        cur = db.cursor()
        calendar_status = get_calendar_status(trade_text, conn=db)
        signal_count = _count(cur, "SELECT COUNT(*) FROM stock_signal WHERE trade_date=%s", (_sql_date(trade_text),))
        snapshot_count = _count(cur, "SELECT COUNT(*) FROM candidate_feature_snapshot WHERE trade_date=%s", (_sql_date(trade_text),))
        report_count = _count(cur, "SELECT COUNT(*) FROM daily_report WHERE trade_date=%s", (_sql_date(trade_text),))
        evaluation_count = _count(
            cur,
            "SELECT COUNT(*) FROM canonical_daily_evaluation_result WHERE signal_trade_date=%s",
            (trade_text,),
        )
        horizons = resolve_evaluation_horizons(trade_text, as_of_text)
        target_1d = horizons.get("t1_date")
        covered_count = 0
        if target_1d and signal_count:
            covered_count = _count(
                cur,
                """
                SELECT COUNT(DISTINCT s.code)
                FROM stock_signal s
                JOIN stock_hist_kline k ON k.code=s.code AND k.trade_date=%s
                WHERE s.trade_date=%s
                """,
                (_sql_date(target_1d), _sql_date(trade_text)),
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

        missing = []
        report_status = "success" if report_count else "missing"
        signal_status = "success" if signal_count else "missing"
        snapshot_status = "success" if signal_count and snapshot_count == signal_count else "missing"
        if report_status == "missing": missing.append("daily_report")
        if signal_status == "missing": missing.append("stock_signal")
        if snapshot_status == "missing": missing.append("candidate_feature_snapshot")

        evaluation_complete = signal_count > 0 and evaluation_count >= signal_count
        if evaluation_complete:
            kline_status = "success"
            t1_status = "success"
        elif not horizons.get("t1_mature"):
            kline_status = "pending"
            t1_status = "pending"
        elif coverage < 0.8:
            kline_status = "deferred"
            t1_status = "deferred" if evaluation_count == 0 else "success"
            if evaluation_count == 0: missing.append("evaluation_t1_low_coverage")
        else:
            kline_status = "success"
            t1_status = "success" if evaluation_count else "missing"
            if t1_status == "missing": missing.append("evaluation_t1")

        if not horizons.get("t3_mature"):
            t3_status = "pending"
        elif not evaluation_count:
            t3_status = "blocked"
            missing.append("evaluation_t3_blocked")
        else:
            t3_complete = _count(
                cur,
                """
                SELECT COUNT(*) FROM canonical_daily_evaluation_result
                WHERE signal_trade_date=%s AND is_mature_3d IS TRUE
                """,
                (trade_text,),
            )
            t3_status = "success" if t3_complete == evaluation_count else "missing"
            if t3_status == "missing": missing.append("evaluation_t3")

        email_status = "success" if email_rows else "unknown"
        hard_missing = any(status == "missing" for status in (report_status, signal_status, snapshot_status, t1_status, t3_status))
        overall = "failed" if hard_missing else ("deferred" if "deferred" in (kline_status, t1_status) else "success")
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
            "diagnostics": {"target_1d_date": target_1d, "target_3d_date": horizons.get("t3_date"), "covered_count": covered_count},
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


if __name__ == "__main__":
    main()
