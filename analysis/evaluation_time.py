"""Canonical trading-day horizons for the evaluation lifecycle."""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd


EVALUATION_SCHEMA_VERSION = "evaluation_v2"


def normalize_trade_date(value) -> str:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid trade date: {value}")
    datetime.strptime(text, "%Y%m%d")
    return text


def _weekday_calendar(start_year=2010, end_year=2035):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


@lru_cache(maxsize=1)
def load_trade_calendar() -> tuple[str, ...]:
    """Load the exchange calendar once; weekday fallback is explicitly degraded."""
    try:
        import akshare as ak

        cal = ak.tool_trade_date_hist_sina()
        dates = pd.to_datetime(cal["trade_date"], errors="coerce").dropna()
        values = sorted(set(dates.dt.strftime("%Y%m%d").tolist()))
        if values:
            return tuple(values)
    except Exception:
        pass
    return tuple(_weekday_calendar())


def resolve_evaluation_horizons(signal_date, as_of_date, calendar=None):
    """Return exact market T+1/T+2/T+3 dates and maturity at as_of_date."""
    signal = normalize_trade_date(signal_date)
    as_of = normalize_trade_date(as_of_date)
    dates = sorted({
        str(value or "").strip().replace("-", "")[:8]
        for value in (calendar or load_trade_calendar())
        if str(value or "").strip()
    })
    future = [value for value in dates if value > signal]
    targets = future[:3]
    t1_date = targets[0] if len(targets) >= 1 else None
    t2_date = targets[1] if len(targets) >= 2 else None
    t3_date = targets[2] if len(targets) >= 3 else None
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "signal_date": signal,
        "run_as_of_date": as_of,
        "t1_date": t1_date,
        "t2_date": t2_date,
        "t3_date": t3_date,
        "t1_mature": bool(t1_date and t1_date <= as_of),
        "t3_mature": bool(t3_date and t3_date <= as_of),
    }
