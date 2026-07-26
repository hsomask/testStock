import numpy as np
import pandas as pd

from analysis.market_facts import (
    build_market_facts,
    project_limitup_metrics,
    project_limitup_stats,
)


def get_main_indices(index_df):
    result = []

    if index_df is None or index_df.empty:
        return result

    name_col = "名称" if "名称" in index_df.columns else None
    code_col = "代码" if "代码" in index_df.columns else None

    target_names = ["上证指数", "深证成指", "创业板指"]

    for name in target_names:
        row = None

        if name_col:
            matched = index_df[index_df[name_col].astype(str).str.contains(name, na=False)]
            if not matched.empty:
                row = matched.iloc[0]

        if row is not None:
            result.append({
                "name": name,
                "close": row.get("最新价", row.get("close", np.nan)),
                "pct_chg": row.get("涨跌幅", row.get("pct_chg", np.nan)),
                "amount": row.get("成交额", row.get("amount", np.nan)),
                "high": row.get("最高", np.nan),
                "low": row.get("最低", np.nan),
                "open": row.get("今开", np.nan),
            })

    return result


def classify_market_status(score):
    if score >= 75:
        return "强势"
    elif score >= 60:
        return "偏强"
    elif score >= 45:
        return "平衡"
    elif score >= 30:
        return "偏弱"
    else:
        return "弱势"


def analyze_market(stock_df, index_df, market_facts=None):
    """Score the market from canonical facts; never infer facts locally."""
    facts = market_facts or build_market_facts(stock_df, strict=False)
    breadth = facts.get("breadth") or {}
    limitup = facts.get("limitup") or {}
    liquidity = facts.get("liquidity") or {}

    up_count = int(breadth.get("up_count", 0))
    down_count = int(breadth.get("down_count", 0))
    flat_count = int(breadth.get("flat_count", 0))
    limit_up = int(limitup.get("sealed_count", 0))
    limit_down = int(limitup.get("limit_down_count", 0))
    total_amount = float(liquidity.get("total_amount_100m", 0) or 0)
    stock_count = int(facts.get("stock_count", len(stock_df)))
    limitup_metrics = project_limitup_metrics(facts)
    limitup_stats = project_limitup_stats(facts)

    limit_up_20cm = int(limitup.get("limit_up_20cm_count", 0))
    limit_down_20cm = int(limitup.get("limit_down_20cm_count", 0))

    up_ratio = up_count / max(stock_count, 1)

    # 市场综合评分（宽度+涨停+成交额综合）
    score = (
        up_ratio * 30
        + min(limit_up / 80, 1) * 30
        + min(total_amount / 12000, 1) * 20
        - min(limit_down / 50, 1) * 15
        + 20
    )
    # Penalize poor market breadth so high volume/limit-up activity does not
    # produce an overly bullish score when most stocks are falling.
    green_ratio = float(breadth.get("green_ratio", down_count / max(stock_count, 1)))
    if green_ratio > 0.60:
        score -= min((green_ratio - 0.60) / 0.20, 1) * 12
    if down_count > up_count:
        score -= min((down_count / max(up_count, 1) - 1) / 1.5, 1) * 8
    score = max(0, min(100, score))

    status = classify_market_status(score)

    # 高度分化判断：上涨少但涨停不少 → 局部热点活跃；若绿盘过高，
    # 对日报用户更应提示为弱势分化/普跌结构，避免“分化”显得过于乐观。
    if up_ratio < 0.25 and green_ratio > 0.75:
        status = "弱势分化"
    elif up_ratio < 0.30 and limit_up >= 50:
        status = "分化"
    elif up_ratio < 0.50 and down_count > up_count:
        status = "宽度偏弱"

    indices = get_main_indices(index_df)

    if status == "弱势分化":
        summary = "市场普跌但局部热点仍活跃，短线生态与全市场赚钱效应背离，不宜开新仓。"
    elif status == "分化":
        summary = "市场宽度偏弱但局部热点活跃，注意区分方向，不要普买。"
    elif status == "宽度偏弱":
        summary = "市场宽度偏弱，下跌多于上涨，操作上应精选方向，控制仓位。"
    elif score >= 60:
        summary = "市场宽度偏强，赚钱效应相对活跃，适合关注主线方向的分歧低吸。"
    elif score >= 45:
        summary = "市场处于震荡平衡状态，板块轮动较快，操作上应控制追高。"
    else:
        summary = "市场宽度偏弱，亏钱效应较明显，应降低仓位并等待情绪修复。"

    return {
        "indices": indices,
        "total_amount": total_amount,
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "limit_up_20cm": limit_up_20cm,
        "limit_down_20cm": limit_down_20cm,
        "market_facts": facts,
        "limitup_metrics": limitup_metrics,
        "limitup_stats": limitup_stats,
        "score": round(score, 1),
        "status": status,
        "summary": summary,
    }
