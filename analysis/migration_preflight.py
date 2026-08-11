"""Read-only preflight for the R1/R4 schema convergence migration."""

import json

import psycopg2

from data.config import DATABASE_DSN


def run():
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    conn = psycopg2.connect(DATABASE_DSN)
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(SUM(row_count - 1), 0), COUNT(*)
            FROM (
                SELECT COUNT(*) AS row_count
                FROM daily_report
                GROUP BY trade_date,
                         COALESCE(NULLIF(report_mode, ''), 'legacy'),
                         COALESCE(NULLIF(report_type, ''), 'daily')
                HAVING COUNT(*) > 1
            ) duplicates
            """
        )
        report_rows_to_remove, duplicate_report_keys = [int(value or 0) for value in cur.fetchone()]
        cur.execute(
            """
            SELECT COUNT(*) FROM daily_report
            WHERE report_mode IS NULL OR report_mode=''
               OR report_type IS NULL OR report_type=''
            """
        )
        report_keys_to_normalize = int(cur.fetchone()[0] or 0)
        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT idempotency_key, attempt_no
                FROM job_run_log
                WHERE idempotency_key IS NOT NULL
                GROUP BY idempotency_key, attempt_no
                HAVING COUNT(*) > 1
            ) duplicates
            """
        )
        duplicate_idempotency_attempts = int(cur.fetchone()[0] or 0)
        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT idempotency_key
                FROM job_run_log
                WHERE idempotency_key IS NOT NULL
                  AND status='running'
                  AND job_name='daily_pipeline'
                GROUP BY idempotency_key
                HAVING COUNT(*) > 1
            ) duplicates
            """
        )
        duplicate_active_pipelines = int(cur.fetchone()[0] or 0)
        cur.close()
        return {
            "status": "ready" if duplicate_idempotency_attempts == 0 and duplicate_active_pipelines == 0 else "blocked",
            "daily_report": {
                "duplicate_keys": duplicate_report_keys,
                "rows_to_remove": report_rows_to_remove,
                "keys_to_normalize": report_keys_to_normalize,
            },
            "job_run_log": {
                "duplicate_idempotency_attempts": duplicate_idempotency_attempts,
                "duplicate_active_pipelines": duplicate_active_pipelines,
            },
        }
    finally:
        conn.close()


def main():
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
