"""
账户过滤模块
根据用户配置过滤不可交易或不适合交易的股票
"""
import pandas as pd

from data.config import (
    ALLOW_MAIN_BOARD, ALLOW_CHINEXT, ALLOW_STAR, ALLOW_BSE,
    EXCLUDE_ST, MIN_PRICE, MAX_PRICE, MIN_AMOUNT,
)

# 板块代码前缀
MAIN_BOARD_PREFIXES = ("000", "001", "002", "600", "601", "603", "605")
CHINEXT_PREFIXES = ("300", "301")
STAR_PREFIXES = ("688",)
BSE_PREFIXES = ("8", "4", "9")


def _board_check(code):
    """判断股票属于哪个板块"""
    code = str(code).strip()
    if code.startswith(CHINEXT_PREFIXES):
        return "创业板", ALLOW_CHINEXT
    if code.startswith(STAR_PREFIXES):
        return "科创板", ALLOW_STAR
    if code.startswith(BSE_PREFIXES):
        return "北交所", ALLOW_BSE
    if code.startswith(MAIN_BOARD_PREFIXES):
        return "主板", ALLOW_MAIN_BOARD
    return "未知", False


def filter_tradeable_stocks(selector_result):
    """
    过滤观察池股票

    返回:
        (filtered_result, excluded_result)
        filtered_result: 每个池只保留可交易的股票
        excluded_result: 被排除的股票列表 [{code, name, strategy, exclude_reason}]
    """
    filtered = {}
    excluded = []

    for pool_name, pool_df in selector_result.items():
        if pool_df is None or pool_df.empty:
            filtered[pool_name] = pool_df
            continue

        keep_mask = pd.Series(True, index=pool_df.index)

        for idx, row in pool_df.iterrows():
            code = str(row.get("code", ""))
            name = str(row.get("name", ""))
            reasons = []

            # 1. ST 过滤
            if EXCLUDE_ST and ("ST" in name or "*ST" in name or "退" in name):
                reasons.append("ST/退市")

            # 2. 板块权限
            board_name, board_allowed = _board_check(code)
            if not board_allowed:
                reasons.append(f"{board_name}未开放")

            # 3. 价格过滤
            close = row.get("close")
            if pd.notna(close):
                if close < MIN_PRICE:
                    reasons.append(f"价格{close:.2f}<{MIN_PRICE}")
                if close > MAX_PRICE:
                    reasons.append(f"价格{close:.2f}>{MAX_PRICE}")

            # 4. 成交额过滤
            amount = row.get("amount")
            if pd.notna(amount) and amount < MIN_AMOUNT:
                reasons.append(f"成交额{amount/1e8:.1f}亿<{MIN_AMOUNT/1e8:.0f}亿")

            if reasons:
                keep_mask.at[idx] = False
                excluded.append({
                    "code": code,
                    "name": name,
                    "strategy": pool_name,
                    "exclude_reason": "；".join(reasons),
                })

        filtered[pool_name] = pool_df[keep_mask].copy() if not keep_mask.all() else pool_df

    return filtered, excluded
