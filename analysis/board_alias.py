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
    groups = df.groupby(["trade_date", "board_type", "display_name"], as_index=False, sort=False)
    agg_map = {
        "board_code": "first",
        "pct_chg": "first",
        "amount": "sum",
        "amount_ratio": "sum",
        "turnover": "first",
        "up_count": "sum",
        "down_count": "sum",
        "leader_name": "first",
        "leader_pct_chg": "first",
    }
    # 只聚合存在的列
    agg_actual = {k: v for k, v in agg_map.items() if k in df.columns}

    result = groups.agg(agg_actual).reset_index(drop=True)
    result["board_name"] = result["display_name"]
    result = result.drop(columns=["display_name"])

    return result
