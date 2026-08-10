"""Canonical, database-backed A-share exchange calendar.

Business modules must read this calendar rather than calling an external
calendar API independently. External data acquisition belongs to
``analysis.trade_calendar_sync``.
"""
from __future__ import annotations

import os
import sys
from bisect import bisect_left, bisect_right
from datetime import date, datetime
from functools import lru_cache

import psycopg2

from data.config import DATABASE_DSN


DEFAULT_EXCHANGE = "CN_A"
VALID_STATUSES = {"open", "closed", "unknown"}


class CalendarUnavailableError(RuntimeError):
    """Raised when an authoritative calendar answer is unavailable."""


def normalize_trade_date(value) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y%m%d")
    text = str(value or "").strip().replace("-", "")[:8]
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid trade date: {value}")
    datetime.strptime(text, "%Y%m%d")
    return text


def _sql_date(value) -> str:
    text = normalize_trade_date(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _weekday_fallback_enabled() -> bool:
    value = os.getenv("TRADE_CALENDAR_ALLOW_WEEKDAY_FALLBACK", "0")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _connect():
    if not DATABASE_DSN:
        raise CalendarUnavailableError("DATABASE_DSN is not configured")
    return psycopg2.connect(DATABASE_DSN)


def _table_exists(cur) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'exchange_calendar'
        )
        """
    )
    return bool(cur.fetchone()[0])


@lru_cache(maxsize=4)
def load_calendar_statuses(exchange=DEFAULT_EXCHANGE) -> dict[str, str]:
    db = _connect()
    try:
        cur = db.cursor()
        if not _table_exists(cur):
            raise CalendarUnavailableError("exchange_calendar table does not exist")
        cur.execute(
            """
            SELECT calendar_date, market_status
            FROM exchange_calendar
            WHERE exchange = %s
            ORDER BY calendar_date
            """,
            (exchange,),
        )
        values = {
            row[0].strftime("%Y%m%d"): row[1]
            for row in cur.fetchall()
        }
        cur.close()
        if not values:
            raise CalendarUnavailableError("exchange_calendar is empty")
        return values
    finally:
        db.close()


def get_calendar_status(value, exchange=DEFAULT_EXCHANGE, conn=None) -> str:
    """Return open/closed; unknown and missing rows are not authoritative."""
    normalized = normalize_trade_date(value)
    sql_date = _sql_date(normalized)
    if conn is None:
        status = load_calendar_statuses(exchange).get(normalized)
    else:
        cur = conn.cursor()
        if not _table_exists(cur):
            raise CalendarUnavailableError("exchange_calendar table does not exist")
        cur.execute(
            """
            SELECT market_status
            FROM exchange_calendar
            WHERE exchange = %s AND calendar_date = %s
            """,
            (exchange, sql_date),
        )
        row = cur.fetchone()
        cur.close()
        status = row[0] if row else None
    try:
        if status in {"open", "closed"}:
            return status
        if _weekday_fallback_enabled():
            parsed = datetime.strptime(sql_date, "%Y-%m-%d")
            return "open" if parsed.weekday() < 5 else "closed"
        reason = "missing" if status is None else str(status)
        raise CalendarUnavailableError(
            f"calendar status is not authoritative: date={sql_date} status={reason}"
        )
    except ValueError as exc:
        raise CalendarUnavailableError(str(exc)) from exc


def is_trade_day(value, exchange=DEFAULT_EXCHANGE, conn=None) -> bool:
    return get_calendar_status(value, exchange=exchange, conn=conn) == "open"


def calendar_check_exit_code(value, exchange=DEFAULT_EXCHANGE, conn=None) -> int:
    """Return a process-safe status: 0=open, 10=closed, 20=unavailable."""
    try:
        status = get_calendar_status(value, exchange=exchange, conn=conn)
    except (CalendarUnavailableError, ValueError):
        return 20
    return 0 if status == "open" else 10


def cli_check_date(value, exchange=DEFAULT_EXCHANGE) -> int:
    """Print a concise calendar result and return the documented exit code."""
    try:
        normalized = normalize_trade_date(value)
        status = get_calendar_status(normalized, exchange=exchange)
    except (CalendarUnavailableError, ValueError) as exc:
        print(f"[ERROR] calendar unavailable: date={value} reason={exc}", file=sys.stderr)
        return 20
    print(f"date={normalized} exchange={exchange} status={status}")
    return 0 if status == "open" else 10


@lru_cache(maxsize=4)
def load_open_dates(exchange=DEFAULT_EXCHANGE) -> tuple[str, ...]:
    db = _connect()
    try:
        cur = db.cursor()
        if not _table_exists(cur):
            raise CalendarUnavailableError("exchange_calendar table does not exist")
        cur.execute(
            """
            SELECT calendar_date
            FROM exchange_calendar
            WHERE exchange = %s AND market_status = 'open'
            ORDER BY calendar_date
            """,
            (exchange,),
        )
        values = tuple(row[0].strftime("%Y%m%d") for row in cur.fetchall())
        cur.close()
        if not values:
            raise CalendarUnavailableError("exchange_calendar has no open dates")
        return values
    finally:
        db.close()


def clear_calendar_cache() -> None:
    load_open_dates.cache_clear()
    load_calendar_statuses.cache_clear()


def shift_trade_day(value, offset, exchange=DEFAULT_EXCHANGE, calendar=None) -> str:
    """Shift from a calendar date by N exchange sessions.

    Offset 0 requires ``value`` itself to be an open day. Positive offsets find
    sessions strictly after value; negative offsets find sessions strictly
    before value.
    """
    current = normalize_trade_date(value)
    dates = tuple(calendar) if calendar is not None else load_open_dates(exchange)
    dates = tuple(sorted(normalize_trade_date(item) for item in dates))
    amount = int(offset)
    if amount == 0:
        idx = bisect_left(dates, current)
        if idx >= len(dates) or dates[idx] != current:
            raise CalendarUnavailableError(f"date is not an open session: {current}")
        return current
    if amount > 0:
        idx = bisect_right(dates, current) + amount - 1
    else:
        idx = bisect_left(dates, current) + amount
    if idx < 0 or idx >= len(dates):
        raise CalendarUnavailableError(
            f"calendar does not cover shift: date={current} offset={amount}"
        )
    return dates[idx]


def previous_trade_day(value, exchange=DEFAULT_EXCHANGE, calendar=None) -> str:
    return shift_trade_day(value, -1, exchange=exchange, calendar=calendar)


def next_trade_day(value, exchange=DEFAULT_EXCHANGE, calendar=None) -> str:
    return shift_trade_day(value, 1, exchange=exchange, calendar=calendar)


def trade_days_between(start, end, exchange=DEFAULT_EXCHANGE, calendar=None):
    start_text = normalize_trade_date(start)
    end_text = normalize_trade_date(end)
    if end_text < start_text:
        return []
    dates = tuple(calendar) if calendar is not None else load_open_dates(exchange)
    normalized = tuple(sorted(normalize_trade_date(item) for item in dates))
    left = bisect_left(normalized, start_text)
    right = bisect_right(normalized, end_text)
    return list(normalized[left:right])


def calendar_coverage(exchange=DEFAULT_EXCHANGE):
    db = _connect()
    try:
        cur = db.cursor()
        if not _table_exists(cur):
            return {"status": "missing_table", "exchange": exchange}
        cur.execute(
            """
            SELECT MIN(calendar_date), MAX(calendar_date),
                   COUNT(*) FILTER (WHERE market_status = 'open'),
                   COUNT(*) FILTER (WHERE market_status = 'closed'),
                   COUNT(*) FILTER (WHERE market_status = 'unknown'),
                   MAX(synced_at),
                   MAX(calendar_date) FILTER (WHERE market_status <> 'unknown')
            FROM exchange_calendar
            WHERE exchange = %s
            """,
            (exchange,),
        )
        row = cur.fetchone()
        cur.close()
        return {
            "status": "ok" if row and row[0] else "empty",
            "exchange": exchange,
            "min_date": row[0].strftime("%Y%m%d") if row and row[0] else None,
            "max_date": row[1].strftime("%Y%m%d") if row and row[1] else None,
            "open_days": int(row[2] or 0) if row else 0,
            "closed_days": int(row[3] or 0) if row else 0,
            "unknown_days": int(row[4] or 0) if row else 0,
            "synced_at": row[5].isoformat() if row and row[5] else None,
            "authoritative_max_date": (
                row[6].strftime("%Y%m%d") if row and row[6] else None
            ),
        }
    finally:
        db.close()
