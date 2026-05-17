import pandas as pd
import numpy as np


def classify_emotion(row):
    pct = row.get("pct_chg", 0)
    score = row.get("strength_score", pct)

    if pd.isna(pct):
        return "数据暂缺"

    if pct >= 5 or score >= 6:
        return "高潮"
    elif pct >= 2:
        return "过热"
    elif pct >= 0:
        return "平衡"
    elif pct >= -2:
        return "退潮"
    else:
        return "冰点"


def distribution(df):
    if df is None or df.empty:
        return {}

    temp = df.copy()
    if "strength_score" not in temp.columns:
        temp["strength_score"] = temp.get("pct_chg", 0)

    temp["emotion"] = temp.apply(classify_emotion, axis=1)

    order = ["高潮", "过热", "平衡", "退潮", "冰点"]
    result = {}

    total = len(temp)
    for label in order:
        count = int((temp["emotion"] == label).sum())
        pct = count / max(total, 1) * 100
        result[label] = {
            "count": count,
            "ratio": round(pct, 1),
        }

    return result


def analyze_sentiment(stock_df, industry_df, concept_df):
    up_count = int((stock_df["pct_chg"] > 0).sum())
    down_count = int((stock_df["pct_chg"] < 0).sum())
    limit_up = int((stock_df["pct_chg"] >= 9.8).sum())
    limit_down = int((stock_df["pct_chg"] <= -9.8).sum())
    amount = stock_df["amount"].sum() / 1e8

    raw_score = (
        up_count / max(len(stock_df), 1) * 40
        + min(limit_up / 80, 1) * 30
        + min(amount / 12000, 1) * 20
        - min(limit_down / 50, 1) * 20
        + 20
    )

    score = max(0, min(100, raw_score))

    if score >= 75:
        stage = "高潮"
        comment = "市场情绪处于高潮区，注意高位分歧和次日兑现压力。"
    elif score >= 60:
        stage = "过热"
        comment = "市场情绪较热，主线方向仍有机会，但追高风险上升。"
    elif score >= 45:
        stage = "平衡"
        comment = "市场处于平衡震荡阶段，资金轮动较快。"
    elif score >= 30:
        stage = "退潮"
        comment = "市场处于退潮阶段，需等待亏钱效应释放。"
    else:
        stage = "冰点"
        comment = "市场情绪接近冰点，短线风险较高，但也可能孕育修复机会。"

    return {
        "score": round(score, 1),
        "stage": stage,
        "comment": comment,
        "industry_distribution": distribution(industry_df),
        "concept_distribution": distribution(concept_df),
    }
