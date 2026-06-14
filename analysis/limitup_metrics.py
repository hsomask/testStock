"""
Limit-up metric helpers.

This module keeps limit-up inference outside the report renderer so the
renderer only formats already-computed facts.
"""
import numpy as np
import pandas as pd


REQUIRED_INTRADAY_COLUMNS = {"code", "close", "high", "pre_close"}


def infer_limit_ratio(code: str, name: str = "") -> float:
    """
    Infer the daily price-limit ratio for A-share stocks.

    This is an estimation口径 for reporting and cache enrichment:
    ST names use 5%, STAR/ChiNext use 20%, BSE uses 30%, others use 10%.
    """
    code = str(code or "").strip().lower()
    name = str(name or "").upper()
    plain_code = code[2:] if code.startswith(("sh", "sz", "bj")) else code

    if "ST" in name:
        return 0.05
    if plain_code.startswith(("300", "301", "688", "689")):
        return 0.20
    if plain_code.startswith(("8", "4", "920")):
        return 0.30
    return 0.10


def _ensure_pre_close(df: pd.DataFrame) -> pd.Series:
    pre_close = pd.to_numeric(df.get("pre_close"), errors="coerce")
    close = pd.to_numeric(df.get("close"), errors="coerce")

    if "pct_chg" in df.columns:
        pct_chg = pd.to_numeric(df["pct_chg"], errors="coerce")
        inferred = close / (1 + pct_chg / 100)
        pre_close = pre_close.fillna(inferred)

    if "date" in df.columns:
        sorted_index = df.assign(_limitup_date=pd.to_datetime(df["date"], errors="coerce")).sort_values("_limitup_date").index
        shifted = close.loc[sorted_index].shift(1).reindex(df.index)
        pre_close = pre_close.fillna(shifted)

    return pre_close


def enrich_limitup_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add limit-up/down prices and boolean flags to a stock dataframe.
    """
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    result = df.copy()
    for col in ["close", "high", "low", "pre_close", "pct_chg"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    if "pre_close" not in result.columns:
        result["pre_close"] = np.nan
    result["pre_close"] = _ensure_pre_close(result)

    if "pct_chg" not in result.columns:
        result["pct_chg"] = np.nan
    pct_chg = pd.to_numeric(result["pct_chg"], errors="coerce")
    valid_pct = result["pre_close"].notna() & (result["pre_close"] != 0)
    inferred_pct = (result["close"] / result["pre_close"] - 1) * 100
    result["pct_chg"] = pct_chg.fillna(inferred_pct.where(valid_pct))

    codes = result["code"] if "code" in result.columns else pd.Series([""] * len(result), index=result.index)
    names = result["name"] if "name" in result.columns else pd.Series([""] * len(result), index=result.index)
    result["limit_ratio"] = [
        infer_limit_ratio(code, name)
        for code, name in zip(codes.astype(str), names.astype(str))
    ]

    result["limit_up_price"] = (result["pre_close"] * (1 + result["limit_ratio"])).round(2)
    result["limit_down_price"] = (result["pre_close"] * (1 - result["limit_ratio"])).round(2)

    close = pd.to_numeric(result.get("close"), errors="coerce")
    high = pd.to_numeric(result.get("high"), errors="coerce")
    limit_up_price = pd.to_numeric(result["limit_up_price"], errors="coerce")
    limit_down_price = pd.to_numeric(result["limit_down_price"], errors="coerce")

    valid_up = limit_up_price.notna() & (limit_up_price > 0)
    valid_down = limit_down_price.notna() & (limit_down_price > 0)

    result["is_touched_limit_up"] = valid_up & (high >= limit_up_price * 0.995)
    result["is_limit_up"] = valid_up & (close >= limit_up_price * 0.995)
    result["is_failed_limit_up"] = result["is_touched_limit_up"] & ~result["is_limit_up"]
    result["is_limit_down"] = valid_down & (close <= limit_down_price / 0.995)

    return result


def compute_intraday_limitup_metrics(stock_df: pd.DataFrame) -> dict:
    """
    Summarize same-day limit-up ecology metrics from stock_df.
    """
    if stock_df is None or stock_df.empty:
        return {
            "data_status": "missing",
            "reason": "stock_df 为空",
        }

    missing = sorted(col for col in REQUIRED_INTRADAY_COLUMNS if col not in stock_df.columns)
    if missing:
        return {
            "data_status": "insufficient",
            "reason": "缺少字段: " + ", ".join(missing),
        }

    enriched = enrich_limitup_flags(stock_df)
    required = ["close", "high", "pre_close", "limit_up_price"]
    valid_mask = pd.Series(True, index=enriched.index)
    for col in required:
        valid_mask &= pd.to_numeric(enriched.get(col), errors="coerce").notna()

    valid_count = int(valid_mask.sum())
    total_count = int(len(enriched))
    if valid_count == 0:
        return {
            "data_status": "insufficient",
            "reason": "当日 high/pre_close 数据不足",
            "stock_count": total_count,
            "coverage_ratio": 0.0,
        }

    scoped = enriched.loc[valid_mask]
    touched = int(scoped["is_touched_limit_up"].sum())
    sealed = int(scoped["is_limit_up"].sum())
    failed = int(scoped["is_failed_limit_up"].sum())
    limit_down = int(scoped["is_limit_down"].sum())
    failed_rate = failed / touched if touched else 0.0

    return {
        "data_status": "ok",
        "stock_count": total_count,
        "valid_count": valid_count,
        "coverage_ratio": round(valid_count / max(total_count, 1), 4),
        "touched_limit_up_count": touched,
        "sealed_limit_up_count": sealed,
        "failed_limit_up_count": failed,
        "failed_limit_up_rate": round(failed_rate, 4),
        "limit_up_count": sealed,
        "limit_down_count": limit_down,
        "data_source": "stock_df_intraday",
    }
