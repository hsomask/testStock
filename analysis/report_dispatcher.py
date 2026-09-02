"""Route a daily report date to first generation or safe rerender."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import psycopg2

from analysis.report_rerender import rerender_report
from analysis.report_recovery import recover_missing_report
from analysis.trade_calendar import normalize_trade_date
from data.config import DATABASE_DSN


def inspect_signal_set(trade_date: str, *, conn=None) -> dict:
    date_text = normalize_trade_date(trade_date)
    sql_date = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"
    own_conn = conn is None
    db = conn or psycopg2.connect(DATABASE_DSN)
    try:
        cur = db.cursor()
        cur.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE signal_id IS NULL),
                   COUNT(*) FILTER (WHERE decision_id IS NULL),
                   COUNT(DISTINCT signal_id)
            FROM stock_signal WHERE trade_date=%s
            """,
            (sql_date,),
        )
        count, missing_signal_id, missing_decision_id, distinct_signal_ids = [
            int(value or 0) for value in cur.fetchone()
        ]
        cur.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE snapshot_row_id IS NULL)
            FROM canonical_signal_lineage WHERE trade_date=%s
            """,
            (sql_date,),
        )
        lineage_count, missing_snapshots = [int(value or 0) for value in cur.fetchone()]
        cur.close()
    finally:
        if own_conn:
            db.close()
    if count == 0:
        state = "missing"
    elif (
        missing_signal_id == 0
        and missing_decision_id == 0
        and distinct_signal_ids == count
        and lineage_count == count
        and missing_snapshots == 0
    ):
        state = "complete"
    else:
        state = "incomplete"
    return {
        "state": state,
        "trade_date": date_text,
        "signal_count": count,
        "lineage_count": lineage_count,
        "missing_signal_id_count": missing_signal_id,
        "missing_decision_id_count": missing_decision_id,
        "missing_snapshot_count": missing_snapshots,
        "duplicate_signal_id_count": max(count - distinct_signal_ids, 0),
    }


def dispatch_report(trade_date: str, *, executor=None) -> dict:
    state = inspect_signal_set(trade_date)
    if state["state"] == "complete":
        try:
            result = rerender_report(trade_date)
            route = "rerender"
        except RuntimeError as exc:
            if "canonical daily report is missing" not in str(exc):
                raise
            result = recover_missing_report(trade_date)
            route = "recover_missing_report"
        return {**result, "route": route, "signal_state": state}
    if state["state"] == "incomplete":
        raise RuntimeError(f"incomplete_existing_signal_set:{json.dumps(state, ensure_ascii=False)}")
    execute = executor or subprocess.run
    env = os.environ.copy()
    env["TRADE_DATE"] = normalize_trade_date(trade_date)
    env.setdefault("SEND_DAILY_EMAIL", "0")
    proc = execute(
        ("bash", "entrypoint.sh"),
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"daily generation failed: exit_code={proc.returncode}")
    return {
        "status": "success",
        "trade_date": normalize_trade_date(trade_date),
        "route": "generate",
        "signal_state": state,
    }


def main():
    parser = argparse.ArgumentParser(description="Dispatch first report generation or safe rerender")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    print(json.dumps(dispatch_report(args.date), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
