import numpy as np
import pandas as pd


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


def analyze_market(stock_df, index_df):
    df = stock_df.copy()

    up_count = int((df["pct_chg"] > 0).sum())
    down_count = int((df["pct_chg"] < 0).sum())
    flat_count = int((df["pct_chg"] == 0).sum())

    limit_up = int((df["pct_chg"] >= 9.8).sum())
    limit_down = int((df["pct_chg"] <= -9.8).sum())

    limit_up_20cm = int((df["pct_chg"] >= 19.5).sum())
    limit_down_20cm = int((df["pct_chg"] <= -19.5).sum())

    total_amount = df["amount"].sum() / 1e8

    up_ratio = up_count / max(len(df), 1)
    limit_up_ratio = limit_up / max(len(df), 1)
    down_ratio = down_count / max(len(df), 1)

    # 市场宽度评分（权重调低 up_ratio，平衡涨停/成交额贡献）
    score = (
        up_ratio * 30
        + min(limit_up / 80, 1) * 30
        + min(total_amount / 12000, 1) * 20
        - min(limit_down / 50, 1) * 15
        + 20
    )
    score = max(0, min(100, score))

    status = classify_market_status(score)

    # 高度分化判断：上涨少但涨停不少 → 局部热点活跃
    if up_ratio < 0.30 and limit_up >= 50:
        status = "分化"
    elif up_ratio < 0.50 and down_count > up_count:
        status = "宽度偏弱"

    indices = get_main_indices(index_df)

    if status == "分化":
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
        "score": round(score, 1),
        "status": status,
        "summary": summary,
    }
