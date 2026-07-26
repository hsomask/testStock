"""Read-only integrity gate for the canonical signal lineage."""
from __future__ import annotations

import argparse
import json
import sys

import psycopg2

from analysis.signal_identity import (
    SIGNAL_ID_SCHEMA_VERSION,
    build_decision_id,
    build_signal_id,
)
from data.config import DATABASE_DSN


LINEAGE_CUTOVER_DATE = "20260725"


def _yyyymmdd(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value or "").replace("-", "")[:8]


def run(trade_date=None, strict=False):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    conn = psycopg2.connect(DATABASE_DSN)
    conn.set_session(readonly=True, autocommit=True)
    try:
        cur = conn.cursor()
        if trade_date is None:
            cur.execute("SELECT MAX(trade_date) FROM stock_signal")
            value = cur.fetchone()[0]
            trade_date = _yyyymmdd(value) if value else None
        if not trade_date:
            return {"status": "no_data", "trade_date": None}
        sql_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

        cur.execute(
            """
            SELECT id, code, strategy, signal_id, signal_schema_version,
                   source_run_id, decision_id, decision_schema_version,
                   final_decision_layer
            FROM stock_signal
            WHERE trade_date = %s
            ORDER BY code, strategy
            """,
            (sql_date,),
        )
        signals = cur.fetchall()
        identity_mismatches = []
        decision_identity_mismatches = []
        missing_final_decisions = 0
        missing_source_run_ids = 0
        for (
            row_id,
            code,
            strategy,
            signal_id,
            schema_version,
            source_run_id,
            decision_id,
            decision_schema_version,
            final_decision_layer,
        ) in signals:
            expected = build_signal_id(trade_date, code, strategy)
            if signal_id != expected or schema_version != SIGNAL_ID_SCHEMA_VERSION:
                identity_mismatches.append(
                    {
                        "row_id": row_id,
                        "code": code,
                        "strategy": strategy,
                        "actual": signal_id,
                        "expected": expected,
                        "schema_version": schema_version,
                    }
                )
            expected_decision_id = build_decision_id(trade_date, code)
            if decision_id != expected_decision_id:
                decision_identity_mismatches.append(
                    {
                        "row_id": row_id,
                        "code": code,
                        "actual": decision_id,
                        "expected": expected_decision_id,
                    }
                )
            if trade_date > LINEAGE_CUTOVER_DATE and not source_run_id:
                missing_source_run_ids += 1
            if trade_date > LINEAGE_CUTOVER_DATE and (
                not decision_schema_version or not final_decision_layer
            ):
                missing_final_decisions += 1

        cur.execute(
            """
            SELECT COUNT(*)
            FROM candidate_feature_snapshot c
            LEFT JOIN stock_signal s ON s.signal_id = c.signal_id
            WHERE c.trade_date = %s
              AND s.id IS NULL
            """,
            (sql_date,),
        )
        orphan_snapshots = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM stock_signal s
            LEFT JOIN candidate_feature_snapshot c ON c.signal_id = s.signal_id
            WHERE s.trade_date = %s
              AND c.id IS NULL
            """,
            (sql_date,),
        )
        missing_snapshots = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT code
                FROM candidate_feature_snapshot
                WHERE trade_date = %s
                GROUP BY code
                HAVING COUNT(DISTINCT canonical_final_layer) > 1
            ) conflicts
            """,
            (sql_date,),
        )
        final_layer_conflicts = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT code
                FROM stock_signal
                WHERE trade_date = %s
                GROUP BY code
                HAVING COUNT(DISTINCT final_decision_layer) > 1
            ) conflicts
            """,
            (sql_date,),
        )
        stock_final_layer_conflicts = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM canonical_daily_evaluation_result r
            LEFT JOIN stock_signal s ON s.signal_id = r.signal_id
            WHERE r.signal_trade_date = %s
              AND s.id IS NULL
            """,
            (trade_date,),
        )
        orphan_evaluations = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM canonical_daily_evaluation_result
            WHERE signal_trade_date = %s
              AND evaluation_run_id IS NULL
            """,
            (trade_date,),
        )
        missing_evaluation_run_ids = (
            cur.fetchone()[0] if trade_date > LINEAGE_CUTOVER_DATE else 0
        )
        cur.execute(
            """
            SELECT COUNT(*)
            FROM candidate_feature_snapshot c
            JOIN stock_signal s ON s.signal_id = c.signal_id
            WHERE c.trade_date = %s
              AND c.source_run_id IS DISTINCT FROM s.source_run_id
            """,
            (sql_date,),
        )
        run_id_mismatches = (
            cur.fetchone()[0] if trade_date > LINEAGE_CUTOVER_DATE else 0
        )
        cur.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT signal_id)
            FROM stock_signal
            WHERE trade_date = %s
            """,
            (sql_date,),
        )
        signal_count, distinct_signal_ids = cur.fetchone()
        cur.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT signal_id)
            FROM candidate_feature_snapshot
            WHERE trade_date = %s
            """,
            (sql_date,),
        )
        snapshot_count, distinct_snapshot_ids = cur.fetchone()
        cur.close()

        failures = {
            "identity_mismatches": len(identity_mismatches),
            "decision_identity_mismatches": len(decision_identity_mismatches),
            "duplicate_signal_ids": signal_count - distinct_signal_ids,
            "duplicate_snapshot_ids": snapshot_count - distinct_snapshot_ids,
            "orphan_snapshots": orphan_snapshots,
            "missing_snapshots": missing_snapshots,
            "final_layer_conflicts": final_layer_conflicts,
            "stock_final_layer_conflicts": stock_final_layer_conflicts,
            "orphan_evaluations": orphan_evaluations,
            "missing_source_run_ids": missing_source_run_ids,
            "missing_final_decisions": missing_final_decisions,
            "missing_evaluation_run_ids": missing_evaluation_run_ids,
            "run_id_mismatches": run_id_mismatches,
        }
        status = "pass" if not any(failures.values()) else "fail"
        if not strict and status == "fail" and not signals:
            status = "no_data"
        return {
            "status": status,
            "trade_date": trade_date,
            "signal_count": signal_count,
            "snapshot_count": snapshot_count,
            "snapshot_coverage": (
                snapshot_count / signal_count if signal_count else None
            ),
            **failures,
            "identity_mismatch_examples": identity_mismatches[:10],
            "decision_identity_mismatch_examples":
                decision_identity_mismatches[:10],
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="YYYYMMDD; default latest signal date")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = run(args.date, strict=args.strict)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and result["status"] != "pass":
        sys.exit(1)


if __name__ == "__main__":
    main()
