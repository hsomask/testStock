"""Backfill deterministic signal_id values without fabricating snapshots.

Dry-run is the default. Use ``--apply`` only after ``sql/schema.sql`` has been
applied so the additive lineage columns exist.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

from analysis.signal_identity import (
    SIGNAL_ID_SCHEMA_VERSION,
    build_decision_id,
    build_signal_id,
)
from data.config import DATABASE_DSN


def _table_columns(cur, table_name):
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
        """,
        (table_name,),
    )
    return {row[0] for row in cur.fetchall()}


def _load_rows(cur, table_name):
    cur.execute(
        f"""
        SELECT id, trade_date, code, strategy
        FROM {table_name}
        ORDER BY id
        """
    )
    return [
        {
            "id": row[0],
            "trade_date": row[1],
            "code": row[2],
            "strategy": row[3],
            "signal_id": build_signal_id(row[1], row[2], row[3]),
            "decision_id": build_decision_id(row[1], row[2]),
        }
        for row in cur.fetchall()
    ]


def _load_evaluation_rows(cur):
    cur.execute(
        """
        SELECT id, signal_trade_date, code, strategy
        FROM watchlist_evaluation_result
        ORDER BY id
        """
    )
    return [
        {
            "id": row[0],
            "trade_date": row[1],
            "code": row[2],
            "strategy": row[3],
            "signal_id": build_signal_id(row[1], row[2], row[3]),
            "decision_id": build_decision_id(row[1], row[2]),
        }
        for row in cur.fetchall()
    ]


def _duplicate_count(rows):
    counts = Counter(row["signal_id"] for row in rows)
    return sum(1 for count in counts.values() if count > 1)


def _apply_simple(cur, table_name, rows, extra_sql=""):
    values = [(row["id"], row["signal_id"]) for row in rows]
    if not values:
        return 0
    execute_values(
        cur,
        f"""
        UPDATE {table_name} AS target
        SET signal_id = source.signal_id
            {extra_sql}
        FROM (VALUES %s) AS source(id, signal_id)
        WHERE target.id = source.id
        """,
        values,
        template="(%s, %s)",
    )
    # execute_values may split input into pages; cursor.rowcount then reports
    # only the final page on some psycopg2/PostgreSQL combinations.
    return len(values)


def _apply_decision_ids(cur, table_name, rows):
    values = [(row["id"], row["decision_id"]) for row in rows]
    if not values:
        return 0
    execute_values(
        cur,
        f"""
        UPDATE {table_name} AS target
        SET decision_id = source.decision_id
        FROM (VALUES %s) AS source(id, decision_id)
        WHERE target.id = source.id
        """,
        values,
        template="(%s, %s)",
    )
    return len(values)


def run(apply=False):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    conn = psycopg2.connect(DATABASE_DSN)
    try:
        cur = conn.cursor()
        stock_rows = _load_rows(cur, "stock_signal")
        snapshot_rows = _load_rows(cur, "candidate_feature_snapshot")
        evaluation_rows = _load_evaluation_rows(cur)
        performance_rows = _load_rows(cur, "signal_performance")

        stock_ids = {row["signal_id"] for row in stock_rows}
        snapshot_ids = {row["signal_id"] for row in snapshot_rows}
        evaluation_ids = {row["signal_id"] for row in evaluation_rows}
        dates_with_snapshots = {
            str(row["trade_date"])[:10] for row in snapshot_rows
        }
        stock_without_snapshot = [
            row
            for row in stock_rows
            if str(row["trade_date"])[:10] in dates_with_snapshots
            and row["signal_id"] not in snapshot_ids
        ]

        result = {
            "status": "ok",
            "mode": "apply" if apply else "dry_run",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "signal_schema_version": SIGNAL_ID_SCHEMA_VERSION,
            "stock_signal_rows": len(stock_rows),
            "snapshot_rows": len(snapshot_rows),
            "evaluation_rows": len(evaluation_rows),
            "signal_performance_rows": len(performance_rows),
            "stock_signal_generated_id_duplicates": _duplicate_count(stock_rows),
            "snapshot_generated_id_duplicates": _duplicate_count(snapshot_rows),
            "snapshot_without_stock_signal": len(snapshot_ids - stock_ids),
            "evaluation_without_stock_signal": len(evaluation_ids - stock_ids),
            "historical_stock_without_snapshot": len(stock_without_snapshot),
            "historical_stock_without_snapshot_examples": [
                {
                    "trade_date": str(row["trade_date"]),
                    "code": str(row["code"]),
                    "strategy": str(row["strategy"]),
                    "signal_id": row["signal_id"],
                }
                for row in stock_without_snapshot[:20]
            ],
            "fabricated_snapshot_rows": 0,
            "updated": {},
        }

        hard_errors = {
            "stock_signal_generated_id_duplicates":
                result["stock_signal_generated_id_duplicates"],
            "snapshot_generated_id_duplicates":
                result["snapshot_generated_id_duplicates"],
            "snapshot_without_stock_signal": result["snapshot_without_stock_signal"],
            "evaluation_without_stock_signal": result["evaluation_without_stock_signal"],
        }
        if any(hard_errors.values()):
            result["status"] = "blocked"
            result["hard_errors"] = hard_errors
            conn.rollback()
            return result

        if apply:
            required = {
                "stock_signal": {
                    "signal_id",
                    "signal_schema_version",
                    "decision_id",
                    "decision_schema_version",
                    "final_decision_layer",
                },
                "candidate_feature_snapshot": {
                    "signal_id",
                    "signal_schema_version",
                    "snapshot_schema_version",
                    "decision_schema_version",
                    "decision_id",
                    "canonical_final_layer",
                },
                "watchlist_evaluation_result": {"signal_id", "decision_id"},
                "signal_performance": {"signal_id"},
            }
            missing = {}
            for table_name, columns in required.items():
                absent = columns - _table_columns(cur, table_name)
                if absent:
                    missing[table_name] = sorted(absent)
            if missing:
                raise RuntimeError(
                    "apply sql/schema.sql before lineage backfill: "
                    + json.dumps(missing, ensure_ascii=False)
                )

            result["updated"]["stock_signal"] = _apply_simple(
                cur,
                "stock_signal",
                stock_rows,
                extra_sql=", signal_schema_version = 'signal_id_v1'",
            )
            result["updated"]["candidate_feature_snapshot"] = _apply_simple(
                cur,
                "candidate_feature_snapshot",
                snapshot_rows,
                extra_sql=(
                    ", signal_schema_version = 'signal_id_v1'"
                    ", snapshot_schema_version = COALESCE("
                    "target.snapshot_schema_version, 'legacy_snapshot')"
                    ", decision_schema_version = COALESCE("
                    "target.decision_schema_version, 'legacy_trade_plan')"
                ),
            )
            result["updated"]["watchlist_evaluation_result"] = _apply_simple(
                cur,
                "watchlist_evaluation_result",
                evaluation_rows,
            )
            result["updated"]["signal_performance"] = _apply_simple(
                cur,
                "signal_performance",
                performance_rows,
            )
            result["updated"]["stock_signal_decision_ids"] = _apply_decision_ids(
                cur, "stock_signal", stock_rows
            )
            result["updated"]["snapshot_decision_ids"] = _apply_decision_ids(
                cur, "candidate_feature_snapshot", snapshot_rows
            )
            result["updated"]["evaluation_decision_ids"] = _apply_decision_ids(
                cur, "watchlist_evaluation_result", evaluation_rows
            )
            cur.execute(
                """
                WITH winners AS (
                    SELECT
                        decision_id,
                        (
                            ARRAY_AGG(
                                rule_layer
                                ORDER BY CASE rule_layer
                                    WHEN '不可交易过滤' THEN 50
                                    WHEN '高风险回避' THEN 40
                                    WHEN '交易条件不满足' THEN 30
                                    WHEN '只观察' THEN 20
                                    WHEN '候选低吸' THEN 10
                                    ELSE 0
                                END DESC
                            )
                        )[1] AS final_layer
                    FROM candidate_feature_snapshot
                    WHERE decision_id IS NOT NULL
                    GROUP BY decision_id
                )
                UPDATE candidate_feature_snapshot c
                SET canonical_final_layer = w.final_layer
                FROM winners w
                WHERE c.decision_id = w.decision_id
                  AND c.canonical_final_layer IS DISTINCT FROM w.final_layer
                """
            )
            result["updated"]["snapshot_canonical_final_layers"] = cur.rowcount
            cur.execute(
                """
                WITH winners AS (
                    SELECT decision_id, MAX(canonical_final_layer) AS final_layer
                    FROM candidate_feature_snapshot
                    WHERE decision_id IS NOT NULL
                      AND canonical_final_layer IS NOT NULL
                    GROUP BY decision_id
                )
                UPDATE stock_signal s
                SET final_decision_layer = w.final_layer,
                    decision_schema_version = COALESCE(
                        s.decision_schema_version,
                        'legacy_trade_plan'
                    )
                FROM winners w
                WHERE w.decision_id = s.decision_id
                  AND (
                      s.final_decision_layer IS DISTINCT FROM w.final_layer
                      OR s.decision_schema_version IS NULL
                  )
                """
            )
            result["updated"]["stock_signal_final_layers"] = cur.rowcount
            conn.commit()
        else:
            conn.rollback()
        cur.close()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="稳定signal_id历史回填（默认dry-run，不补造历史快照）"
    )
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
