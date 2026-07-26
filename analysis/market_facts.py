"""Build and validate the canonical market facts consumed by daily analysis."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from analysis.limitup_metrics import compute_intraday_limitup_metrics


MARKET_FACTS_SCHEMA_VERSION = "market_facts_v1"
MIN_LIMITUP_COVERAGE = 0.80


class MarketFactsError(ValueError):
    """Raised when canonical market facts cannot be built safely."""


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, default))


def _normalize_trade_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return datetime.fromisoformat(text[:10]).date().isoformat()
    except ValueError:
        return text


def _daily_limitup_candidate(stats: dict) -> dict | None:
    if not isinstance(stats, dict) or stats.get("status") != "ok":
        return None
    sealed = _integer(stats.get("limit_up_count"))
    touched = _integer(stats.get("touched_limit_up_count"))
    failed = _integer(stats.get("failed_limit_up_count"))
    coverage = _number(stats.get("coverage_ratio"), 1.0)
    if min(sealed, touched, failed) < 0:
        return None
    if touched != sealed + failed or coverage < MIN_LIMITUP_COVERAGE:
        return None
    return {
        "status": "ok",
        "source": str(stats.get("data_source") or "limitup_daily_stats"),
        "coverage_ratio": coverage,
        "sealed_count": sealed,
        "touched_count": touched,
        "failed_count": failed,
        "failed_rate": failed / touched if touched else 0.0,
        "limit_down_count": _integer(stats.get("limit_down_count")),
    }


def _intraday_limitup_candidate(metrics: dict) -> dict | None:
    if not isinstance(metrics, dict) or metrics.get("data_status") != "ok":
        return None
    sealed = _integer(metrics.get("sealed_limit_up_count"))
    touched = _integer(metrics.get("touched_limit_up_count"))
    failed = _integer(metrics.get("failed_limit_up_count"))
    coverage = _number(metrics.get("coverage_ratio"))
    if min(sealed, touched, failed) < 0:
        return None
    if touched != sealed + failed or coverage < MIN_LIMITUP_COVERAGE:
        return None
    return {
        "status": "ok",
        "source": str(metrics.get("data_source") or "stock_df_intraday"),
        "coverage_ratio": coverage,
        "sealed_count": sealed,
        "touched_count": touched,
        "failed_count": failed,
        "failed_rate": failed / touched if touched else 0.0,
        "limit_down_count": _integer(metrics.get("limit_down_count")),
    }


def validate_market_facts(facts: dict, *, strict: bool = True) -> list[str]:
    """Validate invariants once, before facts reach scoring or rendering."""
    errors = []
    breadth = facts.get("breadth") or {}
    limitup = facts.get("limitup") or {}
    stock_count = _integer(facts.get("stock_count"))
    breadth_total = sum(_integer(breadth.get(key)) for key in ("up_count", "down_count", "flat_count"))

    if stock_count < 0 or breadth_total > stock_count:
        errors.append("市场宽度计数超出股票总数")
    if limitup.get("status") != "ok":
        errors.append(str(limitup.get("reason") or "涨跌停事实不可用"))
    else:
        sealed = _integer(limitup.get("sealed_count"))
        touched = _integer(limitup.get("touched_count"))
        failed = _integer(limitup.get("failed_count"))
        if min(sealed, touched, failed, _integer(limitup.get("limit_down_count"))) < 0:
            errors.append("涨跌停计数不能为负数")
        if touched != sealed + failed:
            errors.append(f"涨停口径冲突：触板{touched} != 封板{sealed} + 炸板{failed}")

    facts["validation"] = {"valid": not errors, "errors": errors}
    if strict and errors:
        raise MarketFactsError("；".join(errors))
    return errors


def build_market_facts(
    stock_df: pd.DataFrame,
    trade_date: str | None = None,
    limitup_daily_stats: dict | None = None,
    *,
    strict: bool = True,
) -> dict:
    """Create the only market-fact object used by the daily-report pipeline."""
    df = stock_df.copy() if stock_df is not None else pd.DataFrame()
    pct_source = df["pct_chg"] if "pct_chg" in df.columns else pd.Series(index=df.index, dtype=float)
    amount_source = df["amount"] if "amount" in df.columns else pd.Series(index=df.index, dtype=float)
    pct_chg = pd.to_numeric(pct_source, errors="coerce")
    amount = pd.to_numeric(amount_source, errors="coerce")
    stock_count = int(len(df))
    up_count = int((pct_chg > 0).sum())
    down_count = int((pct_chg < 0).sum())
    flat_count = int((pct_chg == 0).sum())
    classified_count = up_count + down_count + flat_count

    intraday_metrics = compute_intraday_limitup_metrics(df)
    daily_stats = limitup_daily_stats if isinstance(limitup_daily_stats, dict) else {}
    limitup = _daily_limitup_candidate(daily_stats)
    if limitup is None:
        limitup = _intraday_limitup_candidate(intraday_metrics)
    if limitup is None:
        daily_reason = daily_stats.get("reason") if daily_stats else None
        intraday_reason = intraday_metrics.get("reason") if isinstance(intraday_metrics, dict) else None
        limitup = {
            "status": "missing",
            "source": None,
            "reason": daily_reason or intraday_reason or "没有满足一致性和覆盖率要求的涨停事实",
            "coverage_ratio": 0.0,
            "sealed_count": 0,
            "touched_count": 0,
            "failed_count": 0,
            "failed_rate": 0.0,
            "limit_down_count": 0,
        }

    facts = {
        "schema_version": MARKET_FACTS_SCHEMA_VERSION,
        "trade_date": _normalize_trade_date(trade_date),
        "stock_count": stock_count,
        "breadth": {
            "up_count": up_count,
            "down_count": down_count,
            "flat_count": flat_count,
            "unclassified_count": max(stock_count - classified_count, 0),
            "advance_ratio": up_count / max(down_count, 1),
            "green_ratio": down_count / max(stock_count, 1),
        },
        "liquidity": {
            "total_amount_100m": _number(amount.sum()) / 1e8,
        },
        "limitup": {
            **limitup,
            "limit_up_20cm_count": _integer(intraday_metrics.get("limit_up_20cm_count")),
            "limit_down_20cm_count": _integer(intraday_metrics.get("limit_down_20cm_count")),
            "max_consecutive_limit_up": daily_stats.get("max_consecutive_limit_up"),
            "three_board_plus_count": daily_stats.get("three_board_plus_count"),
            "yesterday_limit_up_avg_return": daily_stats.get("yesterday_limit_up_avg_return"),
            "yesterday_limit_up_win_rate": daily_stats.get("yesterday_limit_up_win_rate"),
        },
        # Keep raw evidence for audit. Consumers must use breadth/limitup above.
        "evidence": {
            "intraday_metrics": intraday_metrics,
            "daily_stats": daily_stats,
        },
    }
    validate_market_facts(facts, strict=strict)
    return facts


def project_limitup_metrics(facts: dict) -> dict:
    """Compatibility projection for report helpers during phase-one migration."""
    limitup = (facts or {}).get("limitup") or {}
    return {
        "data_status": limitup.get("status", "missing"),
        "coverage_ratio": limitup.get("coverage_ratio", 0.0),
        "touched_limit_up_count": _integer(limitup.get("touched_count")),
        "sealed_limit_up_count": _integer(limitup.get("sealed_count")),
        "failed_limit_up_count": _integer(limitup.get("failed_count")),
        "failed_limit_up_rate": _number(limitup.get("failed_rate")),
        "limit_up_count": _integer(limitup.get("sealed_count")),
        "limit_down_count": _integer(limitup.get("limit_down_count")),
        "internally_consistent": bool((facts or {}).get("validation", {}).get("valid")),
        "data_source": limitup.get("source"),
        "reason": limitup.get("reason"),
    }


def project_limitup_stats(facts: dict) -> dict:
    """Compatibility projection carrying richer ecology facts."""
    limitup = (facts or {}).get("limitup") or {}
    return {
        "status": limitup.get("status", "missing"),
        "trade_date": (facts or {}).get("trade_date"),
        "limit_up_count": _integer(limitup.get("sealed_count")),
        "limit_down_count": _integer(limitup.get("limit_down_count")),
        "touched_limit_up_count": _integer(limitup.get("touched_count")),
        "failed_limit_up_count": _integer(limitup.get("failed_count")),
        "failed_limit_up_rate": _number(limitup.get("failed_rate")),
        "max_consecutive_limit_up": limitup.get("max_consecutive_limit_up"),
        "three_board_plus_count": limitup.get("three_board_plus_count"),
        "yesterday_limit_up_avg_return": limitup.get("yesterday_limit_up_avg_return"),
        "yesterday_limit_up_win_rate": limitup.get("yesterday_limit_up_win_rate"),
        "data_source": limitup.get("source"),
        "coverage_ratio": limitup.get("coverage_ratio"),
        "reason": limitup.get("reason"),
    }
