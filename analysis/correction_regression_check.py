"""Regression checks for the unified correction engine.

Run:
  python -m analysis.correction_regression_check
"""
import sys

import pandas as pd

from analysis.correction_engine import evaluate_candidate


def _row(**overrides):
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
        "ma5": 9.9,
        "ma20": 9.5,
    }
    data.update(overrides)
    return pd.Series(data)


def _decision(**kwargs):
    defaults = {
        "base_layer": "候选低吸",
        "base_reason": "满足全部低吸条件",
        "row": _row(),
        "strategy": "板块联动",
        "primary_direction": "机器人",
        "preferred_clusters": ["机器人"],
        "market_status": "强势",
        "data_confidence": 100,
        "strategy_feedback_map": {},
        "context_feedback_map": {},
    }
    defaults.update(kwargs)
    return evaluate_candidate(**defaults)


def _assert(name, condition, detail):
    if not condition:
        return f"{name}: {detail}"
    return None


def run_checks():
    failures = []

    d = _decision()
    failures.append(_assert("主线低吸保留候选", d["final_layer"] == "候选低吸", d))
    failures.append(_assert("主线低吸有决策分", d["decision_score"] > 80, d))
    failures.append(_assert("引擎版本留痕", bool(d.get("correction_engine_version")), d))

    d = _decision(primary_direction="光伏电池组件")
    failures.append(_assert("非今日主线降级", d["final_layer"] == "只观察", d))
    failures.append(_assert("非今日主线标签", "非今日主线" in d["correction_tags"], d))

    d = _decision(row=_row(pct_chg=9.2))
    failures.append(_assert("高位追强降级", d["final_layer"] == "只观察", d))
    failures.append(_assert("高位追强标签", "高位追强" in d["correction_tags"], d))

    d = _decision(strategy_feedback_map={
        "板块联动": {"status": "weak", "sample_count": 12, "win_rate_1d": 0.33, "failed_rate": 0.4}
    })
    failures.append(_assert("策略weak降级", d["final_layer"] == "只观察", d))
    failures.append(_assert("策略weak标签", "策略反馈偏弱" in d["correction_tags"], d))

    d = _decision(strategy_feedback_map={
        "板块联动": {"status": "blocked", "sample_count": 12, "win_rate_1d": 0.2, "failed_rate": 0.6}
    })
    failures.append(_assert("策略blocked强降级", d["final_layer"] == "交易条件不满足", d))

    d = _decision(context_feedback_map={
        ("strategy_market", "板块联动", "强势"): {
            "status": "weak", "sample_count": 12, "win_rate_1d": 0.33, "failed_rate": 0.4,
            "reason": "场景胜率偏弱",
        }
    })
    failures.append(_assert("场景weak降级", d["final_layer"] == "只观察", d))
    failures.append(_assert("场景weak标签", any(str(x).startswith("场景反馈:") for x in d["correction_tags"]), d))

    d = _decision(context_feedback_map={
        ("strategy_market", "板块联动", "强势"): {
            "status": "blocked", "sample_count": 12, "win_rate_1d": 0.2, "failed_rate": 0.6,
            "reason": "场景失败率偏高",
        }
    })
    failures.append(_assert("场景blocked强降级", d["final_layer"] == "交易条件不满足", d))

    d = _decision(strategy="滚雪球趋势", data_confidence=60)
    failures.append(_assert("滚雪球低可信度降级", d["final_layer"] == "只观察", d))
    failures.append(_assert("低可信度标签", "数据可信度不足" in d["correction_tags"], d))

    d = _decision(base_layer="高风险回避", base_reason="信号/风险等级预警", row=_row(risk_level="高"))
    failures.append(_assert("高风险保持回避", d["final_layer"] == "高风险回避", d))

    d = _decision(base_layer="只观察", base_reason="关键指标缺失，只能观察", row=_row(ma5=None, ma20=None))
    failures.append(_assert("指标缺失保持观察", d["final_layer"] == "只观察", d))

    return [x for x in failures if x]


def main():
    failures = run_checks()
    if failures:
        print("[FAIL] correction regression check")
        for item in failures:
            print(f"- {item}")
        sys.exit(1)
    print("[OK] correction regression check")


if __name__ == "__main__":
    main()
