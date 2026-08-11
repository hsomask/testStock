"""Read-only diagnostics for report identities and task-ledger coverage."""

import argparse
import json

import psycopg2

from data.config import DATABASE_DSN


def run(days=10):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    conn = psycopg2.connect(DATABASE_DSN)
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor()
        cur.execute(
            """
            WITH recent AS (
                SELECT DISTINCT trade_date
                FROM stock_signal
                ORDER BY trade_date DESC
                LIMIT %s
            )
            SELECT r.trade_date, COALESCE(r.report_mode, '<NULL>'),
                   COALESCE(r.report_type, '<NULL>'), COUNT(*)
            FROM daily_report r
            JOIN recent d ON d.trade_date=r.trade_date
            GROUP BY r.trade_date, r.report_mode, r.report_type
            ORDER BY r.trade_date, r.report_mode, r.report_type
            """,
            (int(days),),
        )
        reports = [
            {"trade_date": str(row[0]), "report_mode": row[1], "report_type": row[2], "count": row[3]}
            for row in cur.fetchall()
        ]
        cur.execute(
            """
            WITH recent AS (
                SELECT DISTINCT trade_date
                FROM stock_signal
                ORDER BY trade_date DESC
                LIMIT %s
            )
            SELECT d.trade_date, COUNT(j.id),
                   COUNT(j.id) FILTER (
                       WHERE j.job_name IN ('daily_email','email_sender')
                         AND j.status='success'
                   )
            FROM recent d
            LEFT JOIN job_run_log j ON j.trade_date=d.trade_date
            GROUP BY d.trade_date
            ORDER BY d.trade_date
            """,
            (int(days),),
        )
        ledger = [
            {"trade_date": str(row[0]), "task_rows": row[1], "email_success_rows": row[2]}
            for row in cur.fetchall()
        ]
        cur.close()
        return {"reports": reports, "ledger": ledger}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(run(args.days), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
