"""Rebuild legacy daily T+1 rows into the frozen evaluation_v2 lifecycle.

Dry-run is the default. ``--apply`` is required for database writes.
"""
import argparse
import json
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import psycopg2

from analysis.evaluation_time import EVALUATION_SCHEMA_VERSION, resolve_evaluation_horizons
from analysis.watchlist_evaluation import (
    build_result,
    evaluate_records,
    fetch_signals_for_date,
    prime_history_cache_from_db,
    save_evaluation_to_db,
)
from data.config import DATABASE_DSN, REPORT_DIR


def _targets(conn, as_of_date, days):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT s.signal_date
        FROM watchlist_evaluation_summary s
        WHERE s.eval_mode = 'daily'
          AND s.signal_date IS NOT NULL
          AND s.signal_date <> ''
          AND s.signal_date <= %s
          AND NOT EXISTS (
              SELECT 1
              FROM watchlist_evaluation_summary v2
              WHERE v2.eval_mode = 'daily'
                AND v2.signal_date = s.signal_date
                AND v2.evaluation_schema_version = %s
          )
        ORDER BY s.signal_date DESC
        LIMIT %s
        """,
        (as_of_date, EVALUATION_SCHEMA_VERSION, int(days)),
    )
    values = [row[0] for row in cur.fetchall()]
    cur.close()
    return values


def run(as_of_date, days=30, apply=False):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN 未配置")
    conn = psycopg2.connect(DATABASE_DSN)
    evaluation_run_id = str(uuid.uuid4())
    try:
        targets = _targets(conn, as_of_date, days)
        results = []
        for signal_date in targets:
            time_model = resolve_evaluation_horizons(signal_date, as_of_date)
            if not time_model["t1_mature"]:
                continue
            signals = fetch_signals_for_date(conn, signal_date)
            prime_history_cache_from_db(conn, [signal.get("code") for signal in signals])
            records, e1, e3, v1, v3, missing = evaluate_records(
                signals,
                as_of_date=time_model["t1_date"],
                horizon="t1",
            )
            result = build_result(
                records,
                e1,
                e3,
                v1,
                v3,
                Counter(missing),
                {
                    "signal_date": signal_date,
                    "as_of_date": time_model["t1_date"],
                    "run_as_of_date": as_of_date,
                    "target_1d_date": time_model["t1_date"],
                    "target_3d_date": time_model["t3_date"],
                    "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
                    "evaluation_phase": "t1",
                    "run_id": evaluation_run_id,
                    "mode": "daily",
                },
            )
            if apply:
                save_evaluation_to_db(result)
            results.append({
                "signal_date": signal_date,
                "anchor_date": time_model["t1_date"],
                "target_3d_date": time_model["t3_date"],
                "total_signals": len(signals),
                "evaluated_1d": v1,
                "coverage_1d": v1 / len(signals) if signals else 0,
            })
        return {
            "status": "ok",
            "mode": "apply" if apply else "dry_run",
            "as_of_date": as_of_date,
            "run_id": evaluation_run_id,
            "target_count": len(results),
            "targets": results,
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="evaluation_v2历史T+1重建（默认dry-run）")
    parser.add_argument("--as-of", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()
    result = run(args.as_of, days=args.days, apply=args.apply)
    out_dir = Path(REPORT_DIR) / "evaluation"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"evaluation_v2_backfill_{args.as_of}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
