"""Synchronize the persistent A-share exchange calendar.

Dry-run is the default. ``--apply`` is required to change the database.
Existing calendar rows are never deleted when acquisition or validation fails.
"""
from __future__ import annotations

import argparse
import json
import uuid
from collections import Counter
from datetime import date, datetime, timedelta

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from analysis.trade_calendar import (
    DEFAULT_EXCHANGE,
    calendar_coverage,
    clear_calendar_cache,
)
from data.config import DATABASE_DSN


SOURCE = "akshare.tool_trade_date_hist_sina"


def fetch_open_dates() -> list[date]:
    import akshare as ak

    frame = ak.tool_trade_date_hist_sina()
    if frame is None or frame.empty or "trade_date" not in frame.columns:
        raise RuntimeError("calendar source returned no trade_date rows")
    values = pd.to_datetime(frame["trade_date"], errors="coerce").dropna()
    return sorted(set(item.date() for item in values.tolist()))


def build_calendar(open_dates, start_date, future_days=400):
    values = sorted(set(open_dates))
    if not values:
        raise RuntimeError("calendar source returned an empty open-date set")
    start = max(start_date, values[0])
    authoritative_end = values[-1]
    generated_end = max(authoritative_end, date.today() + timedelta(days=int(future_days)))
    open_set = set(values)
    rows = []
    current = start
    while current <= generated_end:
        if current <= authoritative_end:
            status = "open" if current in open_set else "closed"
        else:
            status = "unknown"
        rows.append((current, status))
        current += timedelta(days=1)
    return rows, authoritative_end


def validate_calendar(rows, authoritative_end):
    issues = []
    if not rows:
        return {"status": "fail", "issues": ["no_generated_rows"]}
    seen = set()
    yearly = Counter()
    weekend_open = []
    for calendar_date, status in rows:
        if calendar_date in seen:
            issues.append(f"duplicate_date:{calendar_date}")
        seen.add(calendar_date)
        if status == "open":
            yearly[calendar_date.year] += 1
            if calendar_date.weekday() >= 5:
                weekend_open.append(calendar_date.isoformat())
    if weekend_open:
        issues.append(f"weekend_open:{','.join(weekend_open[:10])}")
    current_year = date.today().year
    for year, count in sorted(yearly.items()):
        if year < current_year and date(year, 12, 31) <= authoritative_end:
            if count < 230 or count > 255:
                issues.append(f"implausible_open_day_count:{year}:{count}")
    explicit_today = any(
        day == date.today() and status in {"open", "closed"}
        for day, status in rows
    )
    if not explicit_today:
        issues.append("today_not_authoritative")
    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "authoritative_end": authoritative_end.isoformat(),
        "generated_start": rows[0][0].isoformat(),
        "generated_end": rows[-1][0].isoformat(),
        "generated_rows": len(rows),
        "open_days": sum(1 for _, status in rows if status == "open"),
        "closed_days": sum(1 for _, status in rows if status == "closed"),
        "unknown_days": sum(1 for _, status in rows if status == "unknown"),
        "yearly_open_days": dict(sorted(yearly.items())),
    }


def _needs_sync(min_future_days=30):
    try:
        coverage = calendar_coverage()
    except Exception:
        return True
    authoritative_max = coverage.get("authoritative_max_date")
    if coverage.get("status") != "ok" or not authoritative_max:
        return True
    required = (date.today() + timedelta(days=int(min_future_days))).strftime("%Y%m%d")
    return authoritative_max < required


def sync_calendar(start_year=2010, future_days=400, apply=False, ensure=False):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    if ensure and not _needs_sync():
        return {
            "status": "current",
            "mode": "ensure",
            "coverage": calendar_coverage(),
        }

    started_at = datetime.now()
    run_id = str(uuid.uuid4())
    open_dates = fetch_open_dates()
    rows, authoritative_end = build_calendar(
        open_dates,
        date(int(start_year), 1, 1),
        future_days=future_days,
    )
    validation = validate_calendar(rows, authoritative_end)
    result = {
        "status": validation["status"],
        "mode": "apply" if apply else "dry_run",
        "run_id": run_id,
        "source": SOURCE,
        "validation": validation,
    }
    if validation["status"] != "pass" or not apply:
        return result

    conn = psycopg2.connect(DATABASE_DSN)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO exchange_calendar_sync_run (
                run_id, source, range_start, range_end,
                fetched_open_days, generated_days, status,
                validation_json, started_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'running', %s::jsonb, %s)
            """,
            (
                run_id,
                SOURCE,
                rows[0][0],
                rows[-1][0],
                len(open_dates),
                len(rows),
                json.dumps(validation, ensure_ascii=False),
                started_at,
            ),
        )
        execute_values(
            cur,
            """
            INSERT INTO exchange_calendar (
                exchange, calendar_date, market_status,
                source, source_version, synced_at
            ) VALUES %s
            ON CONFLICT (exchange, calendar_date)
            DO UPDATE SET
                market_status = EXCLUDED.market_status,
                source = EXCLUDED.source,
                source_version = EXCLUDED.source_version,
                synced_at = NOW()
            """,
            [
                (
                    DEFAULT_EXCHANGE,
                    calendar_date,
                    status,
                    SOURCE,
                    authoritative_end.isoformat(),
                    datetime.now(),
                )
                for calendar_date, status in rows
            ],
            page_size=1000,
        )
        cur.execute(
            """
            UPDATE exchange_calendar_sync_run
            SET status = 'success', finished_at = NOW()
            WHERE run_id = %s
            """,
            (run_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    clear_calendar_cache()
    result["status"] = "success"
    return result


def main():
    parser = argparse.ArgumentParser(description="Synchronize A-share exchange calendar")
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--future-days", type=int, default=400)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--ensure", action="store_true", default=False)
    args = parser.parse_args()
    result = sync_calendar(
        start_year=args.start_year,
        future_days=args.future_days,
        apply=args.apply,
        ensure=args.ensure,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result.get("status") not in {"pass", "success", "current"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
