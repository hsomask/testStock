"""
Backfill stock_hist_kline limit-up fields from existing OHLCV cache.

Usage:
  python -m analysis.backfill_stock_hist_limit_fields --days 120
  python -m analysis.backfill_stock_hist_limit_fields --days 120 --dry-run
"""
import argparse
from datetime import datetime

import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch

from analysis.limitup_metrics import enrich_limitup_flags
from data.config import DATABASE_DSN


def _num_or_none(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _bool_or_none(value):
    try:
        if pd.isna(value):
            return None
        return bool(value)
    except Exception:
        return None


def _text_or_none(value):
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if value is None:
        return None
    return str(value)


def _connect():
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN 未配置")
    return psycopg2.connect(DATABASE_DSN)


def _cutoff_expr(days):
    return f"CURRENT_DATE - INTERVAL '{int(days)} days'"


def collect_target_codes(conn, days, only_missing=True):
    cur = conn.cursor()
    missing_clause = """
        AND (
            pre_close IS NULL
            OR pct_chg IS NULL
            OR limit_up_price IS NULL
            OR is_limit_up IS NULL
        )
    """ if only_missing else ""
    cur.execute(
        f"""
        SELECT DISTINCT code
        FROM stock_hist_kline
        WHERE trade_date >= {_cutoff_expr(days)}
          {missing_clause}
        ORDER BY code
        """
    )
    codes = [row[0] for row in cur.fetchall()]
    cur.close()
    return codes


def load_hist_for_codes(conn, codes, days):
    if not codes:
        return pd.DataFrame()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            code,
            trade_date AS date,
            name,
            open,
            close,
            high,
            low,
            volume,
            pre_close,
            pct_chg,
            amount,
            turnover
        FROM stock_hist_kline
        WHERE trade_date >= {_cutoff_expr(days + 10)}
          AND code = ANY(%s)
        ORDER BY code, trade_date
        """,
        (codes,),
    )
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    cur.close()
    return pd.DataFrame(rows, columns=columns)


def build_updates(hist_df, days):
    if hist_df.empty:
        return []

    cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=days)
    updates = []
    for _, group in hist_df.groupby("code", sort=False):
        enriched = enrich_limitup_flags(group.sort_values("date"))
        scoped = enriched[pd.to_datetime(enriched["date"], errors="coerce") >= cutoff]
        for _, row in scoped.iterrows():
            updates.append((
                _text_or_none(row.get("name")),
                _num_or_none(row.get("pre_close")),
                _num_or_none(row.get("pct_chg")),
                _num_or_none(row.get("amount")),
                _num_or_none(row.get("turnover")),
                _num_or_none(row.get("limit_ratio")),
                _num_or_none(row.get("limit_up_price")),
                _num_or_none(row.get("limit_down_price")),
                _bool_or_none(row.get("is_limit_up")),
                _bool_or_none(row.get("is_limit_down")),
                _bool_or_none(row.get("is_touched_limit_up")),
                _bool_or_none(row.get("is_failed_limit_up")),
                "stock_hist_backfill",
                str(row.get("code")),
                str(row.get("date"))[:10],
            ))
    return updates


def apply_updates(conn, updates, page_size=1000):
    if not updates:
        return 0
    cur = conn.cursor()
    execute_batch(
        cur,
        """
        UPDATE stock_hist_kline
        SET
            name = COALESCE(%s, name),
            pre_close = %s,
            pct_chg = %s,
            amount = %s,
            turnover = %s,
            limit_ratio = %s,
            limit_up_price = %s,
            limit_down_price = %s,
            is_limit_up = %s,
            is_limit_down = %s,
            is_touched_limit_up = %s,
            is_failed_limit_up = %s,
            data_source = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE code = %s
          AND trade_date = %s
        """,
        updates,
        page_size=page_size,
    )
    cur.close()
    return len(updates)


def count_missing(conn, days):
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(pre_close) AS pre_close_rows,
            COUNT(pct_chg) AS pct_chg_rows,
            COUNT(limit_up_price) AS limit_up_price_rows,
            COUNT(is_limit_up) AS is_limit_up_rows
        FROM stock_hist_kline
        WHERE trade_date >= {_cutoff_expr(days)}
        """
    )
    row = cur.fetchone()
    cur.close()
    return {
        "total_rows": int(row[0] or 0),
        "pre_close_rows": int(row[1] or 0),
        "pct_chg_rows": int(row[2] or 0),
        "limit_up_price_rows": int(row[3] or 0),
        "is_limit_up_rows": int(row[4] or 0),
    }


def backfill(days=120, batch_size=200, dry_run=False, only_missing=True):
    conn = _connect()
    before = count_missing(conn, days)
    codes = collect_target_codes(conn, days, only_missing=only_missing)

    print(f"before={before}")
    print(f"target_codes={len(codes)}, days={days}, batch_size={batch_size}, dry_run={dry_run}")

    total_updates = 0
    try:
        for start in range(0, len(codes), batch_size):
            batch_codes = codes[start:start + batch_size]
            hist_df = load_hist_for_codes(conn, batch_codes, days)
            updates = build_updates(hist_df, days)
            total_updates += len(updates)
            if dry_run:
                print(f"batch {start // batch_size + 1}: codes={len(batch_codes)}, updates={len(updates)}")
                continue
            applied = apply_updates(conn, updates)
            conn.commit()
            print(f"batch {start // batch_size + 1}: codes={len(batch_codes)}, applied={applied}")
    except Exception:
        conn.rollback()
        raise

    after = count_missing(conn, days) if not dry_run else before
    conn.close()
    result = {
        "days": days,
        "target_codes": len(codes),
        "planned_updates": total_updates,
        "dry_run": dry_run,
        "before": before,
        "after": after,
    }
    print(f"result={result}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true", help="回填范围内所有行，而不是只补缺失行")
    args = parser.parse_args()
    backfill(
        days=args.days,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        only_missing=not args.all,
    )


if __name__ == "__main__":
    main()
