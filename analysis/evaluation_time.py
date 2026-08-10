"""Canonical trading-day horizons for the evaluation lifecycle."""
from __future__ import annotations

from analysis.trade_calendar import load_open_dates, normalize_trade_date


EVALUATION_SCHEMA_VERSION = "evaluation_v2"


def load_trade_calendar() -> tuple[str, ...]:
    """Load the canonical persistent exchange calendar."""
    return load_open_dates()


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
