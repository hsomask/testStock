"""Regression checks for the canonical persistent exchange calendar."""
from __future__ import annotations

import sys
from datetime import date, timedelta

from analysis.evaluation_time import resolve_evaluation_horizons
from analysis.trade_calendar import (
    CalendarUnavailableError,
    calendar_check_exit_code,
    next_trade_day,
    normalize_trade_date,
    previous_trade_day,
    shift_trade_day,
    trade_days_between,
)
from analysis.trade_calendar_sync import build_calendar, validate_calendar


FIXTURE = [
    "20260925",
    "20260928",
    "20260929",
    "20260930",
    "20261009",
    "20261012",
]


def _assert(name, condition, detail, failures):
    if not condition:
        failures.append(f"{name}: {detail}")


def run_checks():
    failures = []
    _assert("normalize", normalize_trade_date("2026-10-09") == "20261009", "date", failures)
    calendar_module = __import__("analysis.trade_calendar", fromlist=["get_calendar_status"])
    original_get_status = calendar_module.get_calendar_status
    try:
        calendar_module.get_calendar_status = lambda *_args, **_kwargs: "open"
        _assert("open exit code", calendar_check_exit_code("20261009") == 0, "exit", failures)
        calendar_module.get_calendar_status = lambda *_args, **_kwargs: "closed"
        _assert("closed exit code", calendar_check_exit_code("20261010") == 10, "exit", failures)

        def _unavailable(*_args, **_kwargs):
            raise CalendarUnavailableError("fixture unavailable")

        calendar_module.get_calendar_status = _unavailable
        _assert("unavailable exit code", calendar_check_exit_code("20261010") == 20, "exit", failures)
        _assert("invalid date exit code", calendar_check_exit_code("invalid") == 20, "exit", failures)
    finally:
        calendar_module.get_calendar_status = original_get_status
    _assert(
        "previous skips holiday",
        previous_trade_day("20261009", calendar=FIXTURE) == "20260930",
        FIXTURE,
        failures,
    )
    _assert(
        "next skips holiday",
        next_trade_day("20260930", calendar=FIXTURE) == "20261009",
        FIXTURE,
        failures,
    )
    _assert(
        "negative shift",
        shift_trade_day("20261012", -2, calendar=FIXTURE) == "20260930",
        FIXTURE,
        failures,
    )
    _assert(
        "range is inclusive",
        trade_days_between("20260929", "20261009", calendar=FIXTURE)
        == ["20260929", "20260930", "20261009"],
        FIXTURE,
        failures,
    )
    horizons = resolve_evaluation_horizons("20260930", "20261012", calendar=FIXTURE)
    _assert("T+1 exact", horizons["t1_date"] == "20261009", horizons, failures)
    _assert("T+3 exact", horizons["t3_date"] is None, horizons, failures)

    try:
        shift_trade_day("20261012", 1, calendar=FIXTURE)
        failures.append("out-of-range shift did not fail")
    except CalendarUnavailableError:
        pass

    year = date.today().year
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    open_dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            open_dates.append(current)
        current += timedelta(days=1)
    rows, authoritative_end = build_calendar(open_dates, start, future_days=400)
    validation = validate_calendar(rows, authoritative_end)
    _assert("synthetic sync validation", validation["status"] == "pass", validation, failures)
    _assert(
        "future remains unknown",
        any(status == "unknown" for _, status in rows),
        validation,
        failures,
    )
    return failures


def main():
    failures = run_checks()
    if failures:
        print("[FAIL] trade calendar regression check")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)
    print("[OK] trade calendar regression check")


if __name__ == "__main__":
    main()
