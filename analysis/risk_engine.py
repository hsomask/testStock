"""
风险引擎模块
计算每只观察池个股的风险等级和操作信号，执行新手防误操作规则
"""
import pandas as pd
import numpy as np


def evaluate_stock_risk(row, market_score, board_context=None):
    """
    评估单只股票的风险等级和操作信号。

    参数：
        row: 个股数据行
        market_score: 市场情绪评分 0-100
        board_context: 板块上下文 (可选) {"hot_board_hit": bool, "board_ratio_declining": bool}

    返回：
        {
            "risk_score": int,
            "risk_level": "低" | "中" | "高",
            "action_signal": "观察" | "谨慎" | "回避" | "数据不足",
            "risk_reasons": [...]
        }
    """
    risk_score = 0
    risk_reasons = []

    pct_chg = row.get("pct_chg", 0)
    pct_20d = row.get("pct_20d", np.nan)
    volume_ratio = row.get("volume_ratio", np.nan)
    turnover = row.get("turnover", np.nan)
    ma5 = row.get("ma5", np.nan)
    ma10 = row.get("ma10", np.nan)
    ma20 = row.get("ma20", np.nan)
    pct_5d = row.get("pct_5d", np.nan)

    # 数据缺失检测
    data_missing = (
        pd.isna(volume_ratio)
        and pd.isna(ma5)
        and pd.isna(pct_20d)
    )

    if data_missing:
        return {
            "risk_score": 8,
            "risk_level": "高",
            "action_signal": "数据不足",
            "risk_reasons": ["关键数据缺失（量比、均线、历史涨幅均不可用），无法做出有效判断。"],
        }

    # 部分数据缺失
    ma_missing = pd.isna(ma5) or pd.isna(ma20)
    if ma_missing:
        risk_score += 2
        risk_reasons.append("均线数据缺失，趋势判断不完整。")

    # 今日涨幅风险评估
    if pd.notna(pct_chg):
        if pct_chg >= 8:
            risk_score += 2
            risk_reasons.append(f"今日涨幅已达 {pct_chg:.1f}%，处于较高位置。")
        elif pct_chg >= 5:
            risk_score += 1

    # 20日涨幅风险评估
    if pd.notna(pct_20d):
        if pct_20d >= 80:
            risk_score += 3
            risk_reasons.append(f"20日涨幅已达 {pct_20d:.1f}%，存在高位回落风险。")
        elif pct_20d >= 40:
            risk_score += 2
            risk_reasons.append(f"20日涨幅 {pct_20d:.1f}%，短期位置不低。")
        elif pct_20d >= 20:
            risk_score += 1

    # 5日涨幅风险
    if pd.notna(pct_5d) and pct_5d >= 15:
        risk_score += 1
        risk_reasons.append(f"5日涨幅 {pct_5d:.1f}%，短期涨速较快。")

    # 量比异常
    if pd.notna(volume_ratio) and volume_ratio >= 5:
        risk_score += 1
        risk_reasons.append(f"量比 {volume_ratio:.1f}，异常放量需警惕。")

    # 换手率过高
    if pd.notna(turnover) and turnover >= 20:
        risk_score += 1
        risk_reasons.append(f"换手率 {turnover:.1f}%，交易分歧较大。")

    # 市场整体偏弱
    if market_score < 45:
        risk_score += 2
        risk_reasons.append("当前市场整体偏弱，个股可能跟随回落。")

    # 板块成交占比下降
    if board_context and board_context.get("board_ratio_declining"):
        risk_score += 2
        risk_reasons.append("所属板块资金关注度下降，持续性不足。")

    # 非强势板块联动
    if board_context and board_context.get("hot_board_hit") is False:
        risk_score += 1
        risk_reasons.append("未明显关联今日强势板块，属于孤立上涨。")

    # 均线空头
    if pd.notna(ma5) and pd.notna(ma20) and ma5 < ma20:
        risk_score += 1

    # 确定风险等级
    if risk_score <= 2:
        risk_level = "低"
    elif risk_score <= 5:
        risk_level = "中"
    else:
        risk_level = "高"

    # 硬规则：20日涨幅 >= 80% → 至少高风险
    if pd.notna(pct_20d) and pct_20d >= 80:
        risk_level = "高"
        if "20日涨幅已达" not in "".join(risk_reasons):
            risk_reasons.append(f"20日涨幅过高（{pct_20d:.1f}%），存在高位回落风险。")

    # 确定操作信号
    action_signal = _determine_signal(risk_level, data_missing, market_score)

    # 如果没有明显风险，也要给基本面提示
    if not risk_reasons:
        risk_reasons.append("暂无明显极端风险，但仍需观察市场情绪和板块持续性。")
        risk_reasons.append("若大盘走弱，个股也可能跟随回落。")

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "action_signal": action_signal,
        "risk_reasons": risk_reasons,
    }


def _determine_signal(risk_level, data_missing, market_score):
    """根据风险等级和市场环境确定操作信号"""
    if data_missing:
        return "数据不足"

    # 硬规则：市场评分 < 45，所有信号最高「谨慎」
    if market_score < 45:
        return "谨慎"

    if risk_level == "高":
        return "回避"
    elif risk_level == "中":
        return "谨慎"
    else:
        return "观察"


def evaluate_pool_risks(pool_df, market_score, board_context_fn=None):
    """
    为观察池中每只股票追加风险评价。

    参数：
        pool_df: 观察池 DataFrame
        market_score: 市场情绪评分
        board_context_fn: 可选函数，签名为 fn(row) -> dict，返回该股票的板块上下文

    返回：
        添加了 risk_level, action_signal, risk_score_val, risk_reasons 列的 DataFrame
    """
    if pool_df is None or pool_df.empty:
        return pool_df

    df = pool_df.copy()
    risk_levels = []
    action_signals = []
    risk_scores = []
    risk_reasons_list = []

    for _, row in df.iterrows():
        board_ctx = None
        if board_context_fn:
            board_ctx = board_context_fn(row)

        result = evaluate_stock_risk(row, market_score, board_ctx)
        risk_levels.append(result["risk_level"])
        action_signals.append(result["action_signal"])
        risk_scores.append(result["risk_score"])
        risk_reasons_list.append("\n".join(f"{i+1}. {r}" for i, r in enumerate(result["risk_reasons"])))

    df["risk_level"] = risk_levels
    df["action_signal"] = action_signals
    df["risk_score_val"] = risk_scores
    df["risk_reasons"] = risk_reasons_list

    return df
