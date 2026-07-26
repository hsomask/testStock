"""Regression checks for phase-one market-fact and decision convergence.

Run:
  python -m analysis.consistency_regression_check
"""
import sys

import pandas as pd

from analysis.candidate_snapshot import (
    _expand_snapshot_plans,
    _trade_mode as snapshot_trade_mode,
)
from analysis.correction_engine import entry_quality
from analysis.daily_decision import build_daily_decision
from analysis.market import analyze_market
from analysis.market_facts import MarketFactsError, build_market_facts
from analysis.report_renderer import (
    _industry_attention_statistics,
    _trading_mode as renderer_trading_mode,
)
from analysis.sentiment import analyze_sentiment


def _assert(name, condition, detail):
    if not condition:
        return f"{name}: {detail}"
    return None


def _stock_df():
    return pd.DataFrame([
        # Main board sealed at 10%.
        {"code": "000001", "name": "主板封板", "pre_close": 10, "close": 11, "high": 11, "low": 10, "pct_chg": 10, "amount": 1e8},
        # ChiNext +10% is not a 20% limit-up.
        {"code": "300001", "name": "创业板半程", "pre_close": 10, "close": 11, "high": 11, "low": 10, "pct_chg": 10, "amount": 1e8},
        # ChiNext sealed at 20%.
        {"code": "300002", "name": "创业板封板", "pre_close": 10, "close": 12, "high": 12, "low": 10, "pct_chg": 20, "amount": 1e8},
        # Main board touched then failed.
        {"code": "000002", "name": "主板炸板", "pre_close": 10, "close": 10.5, "high": 11, "low": 10, "pct_chg": 5, "amount": 1e8},
        {"code": "000003", "name": "普通下跌", "pre_close": 10, "close": 9.8, "high": 10, "low": 9.8, "pct_chg": -2, "amount": 1e8},
    ])


def _item(code, name, strategy, layer):
    return {
        "code": code,
        "name": name,
        "strategy": strategy,
        "final_layer": layer,
        "reason": layer,
    }


def run_checks():
    failures = []
    stock_df = _stock_df()
    facts = build_market_facts(stock_df, trade_date="20260725")
    limitup = facts["limitup"]
    failures.append(_assert("封板数按板块涨跌幅计算", limitup["sealed_count"] == 2, limitup))
    failures.append(_assert("触板等于封板加炸板", limitup["touched_count"] == 3, limitup))
    failures.append(_assert("炸板数一致", limitup["failed_count"] == 1, limitup))
    failures.append(_assert("20cm封板单独正确", limitup["limit_up_20cm_count"] == 1, limitup))
    failures.append(_assert("市场事实校验通过", facts["validation"]["valid"], facts["validation"]))
    failures.append(_assert(
        "创业板10%不被当作接近涨停",
        entry_quality(stock_df.iloc[1]) != "高位追强",
        entry_quality(stock_df.iloc[1]),
    ))
    failures.append(_assert(
        "创业板20%被识别为接近涨停",
        entry_quality(stock_df.iloc[2]) == "高位追强",
        entry_quality(stock_df.iloc[2]),
    ))

    industry_3d = pd.DataFrame([
        {"board_name": "行业A", "ratio_change_3d": 0.03, "pct_chg": 2},
        {"board_name": "行业B", "ratio_change_3d": 0.02, "pct_chg": 1},
        {"board_name": "行业C", "ratio_change_3d": 0.01, "pct_chg": -1},
        {"board_name": "行业D", "ratio_change_3d": -0.01, "pct_chg": -2},
        {"board_name": "行业E", "ratio_change_3d": -0.02, "pct_chg": -1},
        {"board_name": "行业F", "ratio_change_3d": -0.03, "pct_chg": 1},
    ])
    industry_5d = pd.DataFrame([
        {"board_name": "行业A", "ratio_change_5d": 0.03},
        {"board_name": "行业B", "ratio_change_5d": 0.02},
        {"board_name": "行业C", "ratio_change_5d": 0.01},
        {"board_name": "行业D", "ratio_change_5d": 0.01},
        {"board_name": "行业E", "ratio_change_5d": -0.02},
        {"board_name": "行业F", "ratio_change_5d": -0.03},
    ])
    attention = _industry_attention_statistics({
        "industry_ratio_3d_all": industry_3d,
        "industry_ratio_5d_all": industry_5d,
    })
    failures.append(_assert(
        "3日行业关注度为均衡",
        attention["cycles"][0] == {
            "window": 3, "rising": 3, "falling": 3,
            "expansion": 0.5, "status": "相对均衡",
        },
        attention["cycles"],
    ))
    failures.append(_assert(
        "5日行业关注度识别扩散",
        attention["cycles"][1]["rising"] == 4
        and attention["cycles"][1]["falling"] == 2
        and attention["cycles"][1]["status"] == "关注扩散",
        attention["cycles"],
    ))
    failures.append(_assert(
        "行业量价结构四象限统计正确",
        [item["count"] for item in attention["structure"]] == [2, 1, 2, 1],
        attention["structure"],
    ))

    empty_boards = pd.DataFrame()
    market = analyze_market(stock_df, empty_boards, market_facts=facts)
    sentiment = analyze_sentiment(stock_df, empty_boards, empty_boards, market_facts=facts)
    failures.append(_assert("市场和情绪共享同一事实对象", market["market_facts"] is sentiment["market_facts"], "object identity differs"))
    failures.append(_assert("市场和情绪封板数一致", market["limit_up"] == sentiment["limitup_metrics"]["limit_up_count"] == 2, (market, sentiment)))

    raw_plans = {
        "候选低吸": [
            _item("000001", "冲突票", "策略A", "候选低吸"),
            _item("000003", "可执行票", "策略A", "候选低吸"),
        ],
        "只观察": [_item("000002", "观察票", "策略A", "只观察")],
        "交易条件不满足": [],
        "高风险回避": [_item("000001", "冲突票", "策略B", "高风险回避")],
        "不可交易过滤": [],
    }
    restrictions = {
        "allow_real_trade": True,
        "max_position_pct": 5,
    }
    decision = build_daily_decision(market, restrictions, raw_plans)
    all_items = [
        item
        for items in decision["plans"].values()
        for item in items
    ]
    conflict = next(item for item in all_items if item["code"] == "000001")
    failures.append(_assert("同股只保留一个最终层级", sum(item["code"] == "000001" for item in all_items) == 1, all_items))
    failures.append(_assert("冲突按风险优先级归层", conflict["final_layer"] == "高风险回避", conflict))
    failures.append(_assert("多策略来源被保留", conflict["matched_strategies"] == ["策略A", "策略B"], conflict))
    snapshot_rows = _expand_snapshot_plans(decision["plans"])["高风险回避"]
    failures.append(_assert(
        "快照按策略留痕但不改变最终层级",
        [item["strategy"] for item in snapshot_rows] == ["策略A", "策略B"]
        and all(item["final_layer"] == "高风险回避" for item in snapshot_rows),
        snapshot_rows,
    ))
    failures.append(_assert("摘要等于最终股票数", sum(decision["summary"].values()) == decision["distinct_stock_count"] == 3, decision))
    failures.append(_assert("执行许可基于最终候选", decision["execution"]["execution_allowed"], decision["execution"]))

    trade_plan = {
        "decision": decision,
        "market_restrictions": {
            **restrictions,
            "trade_mode": decision["mode"]["name"],
        },
    }
    renderer_mode, _ = renderer_trading_mode(0, {}, {}, 0, trade_plan)
    failures.append(_assert("渲染和快照消费相同模式", renderer_mode == snapshot_trade_mode(trade_plan) == decision["mode"]["name"], trade_plan))

    no_candidate = build_daily_decision(
        market,
        restrictions,
        {**raw_plans, "候选低吸": []},
    )
    failures.append(_assert("无最终候选不得允许执行", not no_candidate["execution"]["execution_allowed"], no_candidate["execution"]))

    try:
        build_market_facts(pd.DataFrame([{"code": "000001", "pct_chg": 10, "amount": 1e8}]))
    except MarketFactsError:
        pass
    else:
        failures.append("事实不足必须失败: incomplete input was accepted")

    return [failure for failure in failures if failure]


def main():
    failures = run_checks()
    if failures:
        print("[FAIL] consistency regression check")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)
    print("[OK] consistency regression check")


if __name__ == "__main__":
    main()
