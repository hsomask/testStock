"""
板块名称标准化模块
将东方财富/申万等层级名称统一到同花顺常用口径
"""
import re

# 手工映射（优先级高于自动规则）
BOARD_ALIAS = {}

# 自动规则：去除结尾罗马数字层级 Ⅱ/Ⅲ/II/III/Ⅳ/IV
_ROMAN_SUFFIX = re.compile(r"[ 　]*(Ⅱ|Ⅲ|Ⅳ|II|III|IV)$")


def normalize_board_name(raw_name):
    """标准化板块名称"""
    if not raw_name:
        return raw_name

    # 1. 手工映射优先
    if raw_name in BOARD_ALIAS:
        return BOARD_ALIAS[raw_name]

    # 2. 自动去除罗马层级后缀
    cleaned = _ROMAN_SUFFIX.sub("", raw_name).strip()
    if cleaned != raw_name:
        # 如果去掉后缀后与其他板块同名，返回清理后的名称
        return cleaned

    return raw_name


def build_alias_map(board_names):
    """批量建立 name → display_name 映射"""
    alias_map = {}
    for name in board_names:
        alias_map[name] = normalize_board_name(name)
    return alias_map


def aggregate_by_display_name(df):
    """
    按 (trade_date, display_name) 聚合板块数据
    每天同名的 Ⅱ/Ⅲ 层级板块合并
    """
    import pandas as pd
    import numpy as np

    if df is None or df.empty:
        return df

    df = df.copy()
    if "trade_date" not in df.columns:
        return df

    df["display_name"] = df["board_name"].apply(normalize_board_name)

    # 不需要聚合
    if len(df) == len(df["display_name"].unique()):
        return df

    # 按 (trade_date, board_type, display_name) 分组聚合
    import numpy as np

    results = []
    for (td, bt, dname), group in df.groupby(["trade_date", "board_type", "display_name"], sort=False):
        row = {"trade_date": td, "board_type": bt, "board_name": dname}

        row["amount"] = group["amount"].sum() if "amount" in group.columns else None
        row["amount_ratio"] = group["amount_ratio"].sum() if "amount_ratio" in group.columns else None
        row["up_count"] = int(group["up_count"].sum()) if "up_count" in group.columns else 0
        row["down_count"] = int(group["down_count"].sum()) if "down_count" in group.columns else 0
        row["board_code"] = group["board_code"].iloc[0] if "board_code" in group.columns else ""

        # pct_chg 按 amount 加权平均
        if "pct_chg" in group.columns and "amount" in group.columns:
            v = group[group["amount"].notna() & group["pct_chg"].notna()]
            total_amt = v["amount"].sum()
            row["pct_chg"] = (v["pct_chg"] * v["amount"]).sum() / total_amt if total_amt > 0 else group["pct_chg"].mean()
        elif "pct_chg" in group.columns:
            row["pct_chg"] = group["pct_chg"].mean()

        # turnover 按 amount 加权
        if "turnover" in group.columns and "amount" in group.columns:
            v = group[group["amount"].notna() & group["turnover"].notna()]
            total_amt = v["amount"].sum()
            row["turnover"] = (v["turnover"] * v["amount"]).sum() / total_amt if total_amt > 0 else group["turnover"].mean()
        elif "turnover" in group.columns:
            row["turnover"] = group["turnover"].mean()

        # leader 取涨幅最大的
        if "leader_pct_chg" in group.columns:
            valid = group[group["leader_pct_chg"].notna()]
            if not valid.empty:
                best = valid.loc[valid["leader_pct_chg"].idxmax()]
                row["leader_name"] = best.get("leader_name", "")
                row["leader_pct_chg"] = best["leader_pct_chg"]
            else:
                row["leader_name"] = group["leader_name"].iloc[0] if "leader_name" in group.columns else ""
                row["leader_pct_chg"] = None

        results.append(row)

    return pd.DataFrame(results)
