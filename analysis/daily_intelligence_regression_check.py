"""Regression checks for the unified daily intelligence view."""
from analysis.daily_intelligence import (
    build_daily_intelligence,
    intelligence_llm_view,
    intelligence_summary_to_email,
    render_daily_intelligence_markdown,
)
from analysis.watchlist_evaluation import compute_feedback


def main():
    market = {
        "score": 67.2,
        "status": "宽度偏弱",
        "summary": "市场宽度偏弱，下跌多于上涨，操作上应精选方向。",
        "up_count": 2444,
        "down_count": 2914,
        "flat_count": 80,
        "limit_up": 52,
        "limit_down": 4,
        "limitup_stats": {"status": "ok", "failed_limit_up_rate": 0.587},
    }
    trade_plan = {
        "market_restrictions": {"max_position_pct": 3, "single_stock_pct": 1, "allow_real_trade": True},
        "decision": {
            "mode": {"code": "trial", "name": "试错", "summary": "有局部机会，但确认度不足，适合小仓观察。"},
            "execution": {"summary": "当前没有满足条件的候选，继续等待。"},
            "plans": {
                "候选低吸": [],
                "只观察": [],
                "交易条件不满足": [{
                    "code": "603xxx", "name": "样本弱票", "strategy": "N字异动",
                    "observe_low": 9.2, "observe_high": 9.6,
                    "pressure_price": 11.1, "invalid_price": 8.9,
                    "display_reason": "策略反馈偏弱，等待重新转强",
                }],
                "高风险回避": [],
                "不可交易过滤": [],
            },
        },
    }
    t1_data = {
        "available": True,
        "status": "ok",
        "evaluated_1d": 25,
        "total_signals": 25,
        "avg_return_1d": -0.0308,
        "win_rate_1d": 0.20,
        "top_winners": [{
            "name": "强兑现", "ret": 0.0999,
            "attribution_text": "信号日涨幅接近涨停，次日追高风险较高",
        }],
        "top_losers": [{
            "name": "跌停样本", "ret": -0.0999,
            "attribution_text": "信号日涨幅接近涨停，次日追高风险较高；5日涨幅偏大",
        }],
    }
    ctx = build_daily_intelligence(
        trade_date="20260904",
        data_status={},
        quality={"confidence_score": 100},
        market=market,
        sentiment={"score": 71.1, "stage": "过热"},
        trade_plan=trade_plan,
        board_ratio_changes=[],
        t1_data=t1_data,
    )
    report = render_daily_intelligence_markdown(ctx)
    assert "避免后排跟风加仓、情绪高潮追入" in report
    assert "市场宽度正常" not in report
    assert "暂不行动（1只）" in report and "样本弱票" in report
    assert "次日跌停或接近跌停，信号失败" in report
    assert "信号日涨幅接近涨停" in report
    sidecar = intelligence_llm_view(ctx)
    assert sidecar["policy"]["forbidden_tasks"]
    assert sidecar["action_counts"]["交易条件不满足"] == 1
    email_body = intelligence_summary_to_email(sidecar)
    assert "今日结论" in email_body and "明日观察池" in email_body
    assert "暂不行动：1只" in email_body
    assert "llm_context_20260904.json" in email_body

    feedback = compute_feedback(
        {
            "code": "000001", "name": "跌停样本", "pct_chg": 9.9,
            "pct_5d": 25, "strategy": "N字异动",
        },
        {"next_1d_return": -0.099, "next_1d_close": 9.0},
        {},
    )
    assert feedback["feedback_label"] == "failed"
    assert feedback["attribution_text"].startswith("结果事实：次日跌停或接近跌停")
    assert "可能原因：" in feedback["attribution_text"]
    assert "后续处理：" in feedback["attribution_text"]
    print("[OK] daily intelligence regression check")


if __name__ == "__main__":
    main()
