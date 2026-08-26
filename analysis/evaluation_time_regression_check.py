"""Regression checks for the frozen T+1 / independent T+3 lifecycle."""
import sys
from collections import Counter

import pandas as pd

import analysis.watchlist_evaluation as evaluation
from analysis.evaluation_maturity_backfill import (
    T1_IMMUTABLE_COLUMNS,
    T3_PATCH_COLUMNS,
    _apply_target,
    build_t3_patch,
)
from analysis.evaluation_time import EVALUATION_SCHEMA_VERSION, resolve_evaluation_horizons


CALENDAR = [
    "20260717",
    "20260720",
    "20260721",
    "20260722",
    "20260723",
]


def _assert(name, condition, detail):
    return None if condition else f"{name}: {detail}"


def _signal():
    return {
        "id": 1,
        "trade_date": "20260717",
        "code": "000001",
        "name": "测试股票",
        "strategy": "测试策略",
        "watchlist_layer": "观察",
        "close_price": 10,
        "pct_chg": 2,
    }


def run_checks():
    failures = []
    horizons = resolve_evaluation_horizons("20260717", "20260722", calendar=CALENDAR)
    failures.append(_assert("T+1使用交易日", horizons["t1_date"] == "20260720", horizons))
    failures.append(_assert("T+3使用第三个交易日", horizons["t3_date"] == "20260722", horizons))
    failures.append(_assert("时间模型版本固定", horizons["schema_version"] == EVALUATION_SCHEMA_VERSION, horizons))

    hist = pd.DataFrame([
        {"date": "20260717", "close": 10, "high": 10, "low": 10},
        {"date": "20260720", "close": 11, "high": 11.2, "low": 10.8},
        {"date": "20260721", "close": 9, "high": 11.5, "low": 8.8},
        {"date": "20260722", "close": 8, "high": 9.2, "low": 7.8},
    ])
    original = evaluation._cached_get_history
    evaluation._cached_get_history = lambda code, days=80: hist
    try:
        t1_metrics, t1_status = evaluation.evaluate_signal_performance(
            _signal(),
            as_of_date="20260722",
            horizon="t1",
            calendar=CALENDAR,
        )
        failures.append(_assert("T+1运行不计算T+3", t1_metrics["next_3d_return"] is None, t1_metrics))
        failures.append(_assert("T+1精确取目标日", round(t1_metrics["next_1d_return"], 6) == 0.1, t1_metrics))
        failures.append(_assert("T+1成熟状态独立", t1_status["eligible_1d"] and not t1_status["eligible_3d"], t1_status))

        full_metrics, full_status = evaluation.evaluate_signal_performance(
            _signal(),
            as_of_date="20260722",
            horizon="t3",
            calendar=CALENDAR,
        )
        failures.append(_assert("T+3独立计算", round(full_metrics["next_3d_return"], 6) == -0.2, full_metrics))
        t1_feedback = evaluation.compute_feedback(_signal(), t1_metrics, t1_status)
        full_feedback = evaluation.compute_feedback(_signal(), full_metrics, full_status)
        failures.append(_assert(
            "T+3数据不得改变T+1标签",
            t1_feedback["feedback_label"] == full_feedback["feedback_label"]
            and t1_feedback["feedback_score"] == full_feedback["feedback_score"],
            (t1_feedback, full_feedback),
        ))

        records, *_ = evaluation.evaluate_records(
            [_signal()],
            as_of_date="20260722",
            horizon="t3",
            calendar=CALENDAR,
        )
        patch = build_t3_patch(records[0])
        failures.append(_assert("T+3补丁不含T+1字段", not (set(patch) & T1_IMMUTABLE_COLUMNS), patch))
        failures.append(_assert("T+3补丁字段受白名单约束", set(patch) <= T3_PATCH_COLUMNS, patch))

        sql_mismatches = []

        class FakeCursor:
            rowcount = 1

            def execute(self, sql, params=None):
                if params is not None and sql.count("%s") != len(params):
                    sql_mismatches.append((sql.count("%s"), len(params)))

            def close(self):
                pass

        class FakeConnection:
            closed = False

            def cursor(self):
                return FakeCursor()

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        original_connect = evaluation.psycopg2.connect
        original_dsn = evaluation.DATABASE_DSN
        evaluation.psycopg2.connect = lambda dsn: FakeConnection()
        evaluation.DATABASE_DSN = "postgresql://placeholder"
        try:
            result = evaluation.build_result(
                records,
                1,
                1,
                1,
                1,
                Counter(),
                {
                    "signal_date": "20260717",
                    "as_of_date": "20260720",
                    "run_as_of_date": "20260722",
                    "target_1d_date": "20260720",
                    "target_3d_date": "20260722",
                    "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
                    "evaluation_phase": "t1",
                    "mode": "daily",
                },
            )
            evaluation.save_evaluation_to_db(result)
        finally:
            evaluation.psycopg2.connect = original_connect
            evaluation.DATABASE_DSN = original_dsn
        failures.append(_assert("evaluation SQL参数数量一致", not sql_mismatches, sql_mismatches))

        maturity_mismatches = []

        class MaturityCursor(FakeCursor):
            def execute(self, sql, params=None):
                if params is not None and sql.count("%s") != len(params):
                    maturity_mismatches.append((sql.count("%s"), len(params)))

            def fetchone(self):
                return None

        class MaturityConnection(FakeConnection):
            def cursor(self):
                return MaturityCursor()

        _apply_target(
            MaturityConnection(),
            {
                "signal_date": "20260717",
                "anchor_date": "20260720",
                "total_signals": 1,
            },
            records,
            evaluation.aggregate_metrics(records),
            "20260722",
        )
        failures.append(_assert("T+3补齐SQL参数数量一致", not maturity_mismatches, maturity_mismatches))

        detail_update_count = []
        current_patch = build_t3_patch(records[0])
        current_row = (
            current_patch["next_3d_return"], current_patch["max_3d_return"],
            current_patch["max_3d_drawdown"], current_patch["is_mature_3d"],
            current_patch["target_3d_date"], current_patch["t3_price_status"],
            current_patch["t3_missing_reason"], current_patch["verification_tag_3d"],
            current_patch["feedback_label_3d"], current_patch["feedback_score_3d"],
            current_patch["attribution_tags_3d"], current_patch["attribution_text_3d"],
        )

        class UnchangedMaturityCursor(MaturityCursor):
            def execute(self, sql, params=None):
                super().execute(sql, params)
                if "UPDATE watchlist_evaluation_result" in sql:
                    detail_update_count.append(1)

            def fetchone(self):
                return current_row

        class UnchangedMaturityConnection(MaturityConnection):
            def cursor(self):
                return UnchangedMaturityCursor()

        _apply_target(
            UnchangedMaturityConnection(),
            {"signal_date": "20260717", "anchor_date": "20260720", "total_signals": 1},
            records, evaluation.aggregate_metrics(records), "20260722",
        )
        failures.append(_assert("T+3业务字段未变化时不重复写detail", not detail_update_count, detail_update_count))

        suspended = hist[hist["date"] != "20260720"].copy()
        evaluation._cached_get_history = lambda code, days=80: suspended
        missing_metrics, missing_status = evaluation.evaluate_signal_performance(
            _signal(),
            as_of_date="20260722",
            horizon="t1",
            calendar=CALENDAR,
        )
        failures.append(_assert("停牌不得顺延到下一根K线", missing_metrics is None, missing_metrics))
        failures.append(_assert("缺失目标日有明确原因", "missing_t1_price" in missing_status["missing_reasons"], missing_status))
    finally:
        evaluation._cached_get_history = original

    return [failure for failure in failures if failure]


def main():
    failures = run_checks()
    if failures:
        print("[FAIL] evaluation time regression check")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)
    print("[OK] evaluation time regression check")


if __name__ == "__main__":
    main()
