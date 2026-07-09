"""Regression checks for correction-effectiveness sample eligibility."""
import sys

import pandas as pd

from analysis.correction_effectiveness import (
    _build_summary,
    _eligible_correction_rows,
    _stock_level_rows,
)


def run_checks():
    rows = pd.DataFrame([
        {
            "code": "old-null",
            "base_layer": None,
            "final_layer": "只观察",
            "correction_engine_version": None,
        },
        {
            "code": "old-nan",
            "base_layer": float("nan"),
            "final_layer": "只观察",
            "correction_engine_version": float("nan"),
        },
        {
            "code": "partial",
            "base_layer": "候选低吸",
            "final_layer": "",
            "correction_engine_version": "2026-07-05-v1",
        },
        {
            "code": "valid",
            "base_layer": "候选低吸",
            "final_layer": "只观察",
            "correction_engine_version": "2026-07-09-v2",
        },
    ])
    eligible = _eligible_correction_rows(rows)
    if eligible["code"].tolist() != ["valid"]:
        return False

    strategy_rows = pd.DataFrame([
        {
            "trade_date": "20260707",
            "as_of_date": "20260708",
            "code": "000001",
            "name": "多策略股票",
            "strategy": "一次起爆",
            "base_layer": "候选低吸",
            "final_layer": "只观察",
            "correction_tags": '["非今日主线"]',
            "correction_engine_version": "2026-07-09-v2",
            "next_1d_return": -0.04,
        },
        {
            "trade_date": "20260707",
            "as_of_date": "20260708",
            "code": "000001",
            "name": "多策略股票",
            "strategy": "短线强势",
            "base_layer": "候选低吸",
            "final_layer": "交易条件不满足",
            "correction_tags": '["策略反馈偏弱"]',
            "correction_engine_version": "2026-07-09-v2",
            "next_1d_return": -0.04,
        },
        {
            "trade_date": "20260707",
            "as_of_date": "20260708",
            "code": "000002",
            "name": "对照股票",
            "strategy": "板块联动",
            "base_layer": "候选低吸",
            "final_layer": "候选低吸",
            "correction_tags": "[]",
            "correction_engine_version": "2026-07-09-v2",
            "next_1d_return": 0.02,
        },
    ])
    stocks = _stock_level_rows(strategy_rows)
    summary = _build_summary(stocks)
    return (
        len(stocks) == 2
        and summary["downgraded"] == 1
        and summary["kept_candidate"] == 1
        and round(summary["correction_net_benefit"], 4) == 0.06
    )


def main():
    if not run_checks():
        print("[FAIL] correction effectiveness regression check")
        sys.exit(1)
    print("[OK] correction effectiveness regression check")


if __name__ == "__main__":
    main()
