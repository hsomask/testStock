"""Regression checks for trade_plan orchestration around correction_engine.

Run:
  python -m analysis.trade_plan_regression_check
"""
import sys

import pandas as pd

import analysis.trade_plan as trade_plan


def _base_row(**overrides):
    data = {
        "action_signal": "观察",
        "risk_level": "低",
        "pct_chg": 2.0,
        "pct_5d": 5.0,
        "pct_20d": 10.0,
        "volume_ratio": 1.2,
        "turnover": 5.0,
        "close": 10.0,
        "observe_low": 9.8,
        "observe_high": 10.2,
        "pressure_price": 11.0,
        "invalid_price": 9.5,
        "ma5": 9.9,
        "ma20": 9.5,
        "hot_board_hits": ["机器人"],
    }
    data.update(overrides)
    return data


def _build_plan():
    trade_plan.DATABASE_DSN = None
    trade_plan.load_strategy_feedback = lambda window_days=5: {}
    trade_plan.load_context_feedback = lambda: {}

    df = pd.DataFrame([
        _base_row(code="000001", name="主线低吸"),
        _base_row(code="000002", name="非主线", hot_board_hits=["光伏电池组件"]),
        _base_row(code="000003", name="高位追强", pct_chg=9.2),
        _base_row(code="000004", name="高风险", risk_level="高"),
    ])
    market = {
        "score": 75,
        "status": "强势",
        "up_count": 3000,
        "down_count": 1000,
        "limit_up": 80,
        "limit_down": 5,
    }
    quality = {"confidence_score": 100}
    return trade_plan.generate_trade_plan(
        "20260703",
        market,
        quality,
        [{"name": "机器人"}],
        {"板块联动": df},
        [{
            "code": "000005",
            "name": "不可交易",
            "strategy": "板块联动",
            "exclude_reason": "上市未满30日",
        }],
    )


def _flatten(plan):
    rows = {}
    for layer, items in plan.get("plans", {}).items():
        for item in items:
            rows[item["name"]] = (layer, item)
    return rows


def _assert(name, condition, detail):
    if not condition:
        return f"{name}: {detail}"
    return None


def run_checks():
    plan = _build_plan()
    rows = _flatten(plan)
    failures = []

    failures.append(_assert("主线低吸仍是候选", rows["主线低吸"][0] == "候选低吸", rows["主线低吸"]))
    failures.append(_assert("非主线被降级", rows["非主线"][0] == "只观察", rows["非主线"]))
    failures.append(_assert("高位追强被降级", rows["高位追强"][0] == "只观察", rows["高位追强"]))
    failures.append(_assert("高风险保持回避", rows["高风险"][0] == "高风险回避", rows["高风险"]))
    failures.append(_assert("不可交易保持过滤", rows["不可交易"][0] == "不可交易过滤", rows["不可交易"]))

    required = [
        "base_layer", "final_layer", "decision_score", "direction_fit_score",
        "entry_quality", "correction_level", "correction_tags", "display_reason",
        "correction_engine_version",
    ]
    for stock_name, (_, item) in rows.items():
        missing = [key for key in required if key not in item]
        failures.append(_assert(f"{stock_name}统一字段齐全", not missing, missing))
        failures.append(_assert(f"{stock_name}final_layer一致", item["final_layer"] in plan["plans"], item))

    return [x for x in failures if x]


def main():
    failures = run_checks()
    if failures:
        print("[FAIL] trade_plan regression check")
        for item in failures:
            print(f"- {item}")
        sys.exit(1)
    print("[OK] trade_plan regression check")


if __name__ == "__main__":
    main()
