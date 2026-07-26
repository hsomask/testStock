"""DB-free regression checks for signal/snapshot identity dual writes."""
import sys

import pandas as pd

from analysis.candidate_snapshot import save_candidate_feature_snapshot
from analysis.daily_report import save_stock_signals
from analysis.signal_identity import (
    SIGNAL_ID_SCHEMA_VERSION,
    build_decision_id,
    build_signal_id,
)


class _Cursor:
    def __init__(self, statements):
        self.statements = statements

    def execute(self, sql, params=None):
        if params is not None:
            expected = sql.count("%s")
            actual = len(params)
            if expected != actual:
                raise AssertionError(
                    f"SQL placeholder mismatch: expected={expected}, actual={actual}"
                )
        self.statements.append((sql, params))

    def close(self):
        return None


class _Connection:
    closed = False

    def __init__(self):
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self.statements)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _selector_result():
    return {
        "N字异动": pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "测试股票",
                    "close": 10.0,
                    "pct_chg": 2.0,
                    "volume_ratio": 1.2,
                    "turnover": 3.0,
                    "ma5": 9.8,
                    "ma10": 9.7,
                    "ma20": 9.5,
                    "pct_5d": 4.0,
                    "pct_20d": 8.0,
                    "observe_low": 9.7,
                    "observe_high": 10.1,
                    "pressure_price": 11.0,
                    "invalid_price": 9.4,
                    "risk_level": "低",
                    "action_signal": "观察",
                    "entry_reason": "测试",
                    "risk_reasons": "",
                    "hot_board_hits": [],
                }
            ]
        )
    }


def _trade_plan():
    item = {
        "code": "000001",
        "name": "测试股票",
        "strategy": "N字异动",
        "matched_strategies": ["N字异动"],
        "base_layer": "候选低吸",
        "final_layer": "候选低吸",
        "primary_direction": "测试方向",
        "decision_score": 80,
        "direction_fit_score": 100,
        "entry_quality": "分歧低吸",
        "correction_level": "none",
        "correction_tags": [],
        "display_reason": "测试",
        "correction_engine_version": "test",
    }
    return {
        "decision": {
            "schema_version": "daily_decision_v1",
            "mode": {"name": "试错"},
            "plans": {"候选低吸": [item]},
        },
        "market_restrictions": {"max_position_pct": 2},
    }


def run_checks():
    failures = []
    trade_date = "20260724"
    run_id = "run-test"
    expected_signal_id = build_signal_id(trade_date, "000001", "N字异动")
    expected_decision_id = build_decision_id(trade_date, "000001")

    stock_conn = _Connection()
    save_stock_signals(
        _selector_result(),
        trade_date,
        db_conn=stock_conn,
        source_run_id=run_id,
        trade_plan=_trade_plan(),
    )
    stock_inserts = [
        params
        for sql, params in stock_conn.statements
        if params is not None and "INSERT INTO stock_signal" in sql
    ]
    stock_replacements = [
        params
        for sql, params in stock_conn.statements
        if params is not None and "DELETE FROM stock_signal" in sql
    ]
    if stock_replacements != [(trade_date,)]:
        failures.append(
            f"stock_signal authoritative replacement mismatch: {stock_replacements}"
        )
    if len(stock_inserts) != 1:
        failures.append(f"stock_signal insert count: {len(stock_inserts)}")
    elif stock_inserts[0][:3] != (
        expected_signal_id,
        SIGNAL_ID_SCHEMA_VERSION,
        run_id,
    ):
        failures.append("stock_signal identity fields mismatch")
    elif stock_inserts[0][3:6] != (
        expected_decision_id,
        "daily_decision_v1",
        "候选低吸",
    ):
        failures.append("stock_signal final decision fields mismatch")

    snapshot_conn = _Connection()
    written = save_candidate_feature_snapshot(
        trade_date=trade_date,
        trade_plan=_trade_plan(),
        selector_result=_selector_result(),
        market={"status": "平衡", "score": 55},
        sentiment={"stage": "平衡", "score": 55},
        quality={"confidence_score": 100},
        db_conn=snapshot_conn,
        source_run_id=run_id,
    )
    snapshot_inserts = [
        params
        for sql, params in snapshot_conn.statements
        if params is not None and "INSERT INTO candidate_feature_snapshot" in sql
    ]
    if written != 1 or len(snapshot_inserts) != 1:
        failures.append(
            f"candidate snapshot write mismatch: written={written}, "
            f"inserts={len(snapshot_inserts)}"
        )
    elif snapshot_inserts[0][:3] != (
        expected_signal_id,
        SIGNAL_ID_SCHEMA_VERSION,
        run_id,
    ):
        failures.append("candidate snapshot identity fields mismatch")
    elif snapshot_inserts[0][3] != expected_decision_id:
        failures.append("candidate snapshot decision_id mismatch")
    return failures


def main():
    failures = run_checks()
    if failures:
        print("[FAIL] signal lineage regression check")
        for item in failures:
            print(f"- {item}")
        sys.exit(1)
    print("[OK] signal lineage regression check")


if __name__ == "__main__":
    main()
