"""
Generate daily limit-up ecology tables.

Usage:
  python -m analysis.limitup_daily_update --date 20260612
"""
import argparse
from datetime import datetime

import pandas as pd
import psycopg2
import akshare as ak
from psycopg2.extras import execute_batch

from analysis.data_fetcher import fetch_stock_spot
from analysis.limitup_metrics import enrich_limitup_flags
from data.config import DATABASE_DSN


def _normalize_trade_date(trade_date: str) -> str:
    text = str(trade_date or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return datetime.fromisoformat(text[:10]).date().isoformat()


def _num_or_none(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _int_or_zero(value):
    try:
        if pd.isna(value):
            return 0
        return int(value)
    except Exception:
        return 0


def _bool_or_none(value):
    try:
        if pd.isna(value):
            return None
        return bool(value)
    except Exception:
        return None


def _load_previous_pool(conn, trade_date):
    cur = conn.cursor()
    expected_prev_date = _previous_trade_date(trade_date)
    cur.execute(
        "SELECT MAX(trade_date) FROM limitup_stock_pool WHERE trade_date < %s",
        (trade_date,),
    )
    row = cur.fetchone()
    prev_date = row[0] if row else None
    if not prev_date or (expected_prev_date and str(prev_date) != expected_prev_date):
        cur.close()
        return None, {}

    cur.execute(
        """
        SELECT code, is_limit_up, consecutive_limit_up_count
        FROM limitup_stock_pool
        WHERE trade_date = %s
        """,
        (prev_date,),
    )
    prev = {
        str(code): {
            "is_limit_up": bool(is_limit_up),
            "consecutive": int(consecutive or 0),
        }
        for code, is_limit_up, consecutive in cur.fetchall()
    }
    cur.close()
    return prev_date, prev


def _previous_trade_date(trade_date):
    try:
        cal = ak.tool_trade_date_hist_sina()
        dates = pd.to_datetime(cal["trade_date"], errors="coerce").dropna().dt.strftime("%Y-%m-%d")
        prev = [d for d in dates.tolist() if d < trade_date]
        return max(prev) if prev else None
    except Exception:
        return None


def _limitup_status(row, consecutive):
    if bool(row.get("is_failed_limit_up")):
        return "炸板"
    if bool(row.get("is_limit_down")):
        return "跌停"
    if not bool(row.get("is_limit_up")):
        return "未涨停"
    if consecutive >= 4:
        return "高标"
    if consecutive >= 2:
        return f"{consecutive}连板"
    return "首板"


def _prepare_pool(stock_df, prev_pool):
    enriched = enrich_limitup_flags(stock_df)
    rows = []
    for _, row in enriched.iterrows():
        code = str(row.get("code", "")).strip()
        prev = prev_pool.get(code, {})
        if bool(row.get("is_limit_up")):
            consecutive = int(prev.get("consecutive", 0)) + 1 if prev.get("is_limit_up") else 1
        else:
            consecutive = 0
        rows.append({
            "code": code,
            "name": row.get("name"),
            "close": row.get("close"),
            "pct_chg": row.get("pct_chg"),
            "high": row.get("high"),
            "low": row.get("low"),
            "pre_close": row.get("pre_close"),
            "limit_ratio": row.get("limit_ratio"),
            "limit_up_price": row.get("limit_up_price"),
            "limit_down_price": row.get("limit_down_price"),
            "is_limit_up": row.get("is_limit_up"),
            "is_limit_down": row.get("is_limit_down"),
            "is_touched_limit_up": row.get("is_touched_limit_up"),
            "is_failed_limit_up": row.get("is_failed_limit_up"),
            "consecutive_limit_up_count": consecutive,
            "limitup_status": _limitup_status(row, consecutive),
            "data_source": row.get("data_source", "stock_df_intraday"),
        })
    return pd.DataFrame(rows)


def _compute_yesterday_performance(pool_df, prev_pool):
    yesterday_codes = {code for code, item in prev_pool.items() if item.get("is_limit_up")}
    if not yesterday_codes:
        return None, None

    scoped = pool_df[pool_df["code"].astype(str).isin(yesterday_codes)]
    pct = pd.to_numeric(scoped.get("pct_chg"), errors="coerce").dropna()
    if pct.empty:
        return None, None
    return float(pct.mean()), float((pct > 0).mean())


def update_limitup_daily(trade_date: str):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN 未配置")

    sql_date = _normalize_trade_date(trade_date)
    stock_df = fetch_stock_spot()

    conn = psycopg2.connect(DATABASE_DSN)
    prev_date, prev_pool = _load_previous_pool(conn, sql_date)
    pool_df = _prepare_pool(stock_df, prev_pool)

    pool_rows = []
    for _, row in pool_df.iterrows():
        pool_rows.append((
            sql_date,
            str(row.get("code", "")),
            None if pd.isna(row.get("name")) else str(row.get("name")),
            _num_or_none(row.get("close")),
            _num_or_none(row.get("pct_chg")),
            _num_or_none(row.get("high")),
            _num_or_none(row.get("low")),
            _num_or_none(row.get("pre_close")),
            _num_or_none(row.get("limit_ratio")),
            _num_or_none(row.get("limit_up_price")),
            _num_or_none(row.get("limit_down_price")),
            _bool_or_none(row.get("is_limit_up")),
            _bool_or_none(row.get("is_limit_down")),
            _bool_or_none(row.get("is_touched_limit_up")),
            _bool_or_none(row.get("is_failed_limit_up")),
            _int_or_zero(row.get("consecutive_limit_up_count")),
            row.get("limitup_status"),
            row.get("data_source") or "stock_df_intraday",
        ))

    cur = conn.cursor()
    execute_batch(cur, """
        INSERT INTO limitup_stock_pool (
            trade_date, code, name, close, pct_chg, high, low, pre_close,
            limit_ratio, limit_up_price, limit_down_price,
            is_limit_up, is_limit_down, is_touched_limit_up, is_failed_limit_up,
            consecutive_limit_up_count, limitup_status, data_source, generated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, CURRENT_TIMESTAMP
        )
        ON CONFLICT (trade_date, code)
        DO UPDATE SET
            name = EXCLUDED.name,
            close = EXCLUDED.close,
            pct_chg = EXCLUDED.pct_chg,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            pre_close = EXCLUDED.pre_close,
            limit_ratio = EXCLUDED.limit_ratio,
            limit_up_price = EXCLUDED.limit_up_price,
            limit_down_price = EXCLUDED.limit_down_price,
            is_limit_up = EXCLUDED.is_limit_up,
            is_limit_down = EXCLUDED.is_limit_down,
            is_touched_limit_up = EXCLUDED.is_touched_limit_up,
            is_failed_limit_up = EXCLUDED.is_failed_limit_up,
            consecutive_limit_up_count = EXCLUDED.consecutive_limit_up_count,
            limitup_status = EXCLUDED.limitup_status,
            data_source = EXCLUDED.data_source,
            generated_at = CURRENT_TIMESTAMP
    """, pool_rows, page_size=500)

    touched = int(pool_df["is_touched_limit_up"].sum())
    failed = int(pool_df["is_failed_limit_up"].sum())
    failed_rate = failed / touched if touched else 0.0
    avg_return, win_rate = _compute_yesterday_performance(pool_df, prev_pool)

    valid_mask = (
        pd.to_numeric(pool_df.get("close"), errors="coerce").notna()
        & pd.to_numeric(pool_df.get("high"), errors="coerce").notna()
        & pd.to_numeric(pool_df.get("pre_close"), errors="coerce").notna()
    )
    coverage_ratio = float(valid_mask.mean()) if len(pool_df) else 0.0

    max_consecutive = int(pool_df["consecutive_limit_up_count"].max()) if len(pool_df) and prev_date else None
    three_board_plus = int((pool_df["consecutive_limit_up_count"] >= 3).sum()) if prev_date else None

    cur.execute("""
        INSERT INTO limitup_daily_stats (
            trade_date,
            limit_up_count,
            limit_down_count,
            touched_limit_up_count,
            failed_limit_up_count,
            failed_limit_up_rate,
            max_consecutive_limit_up,
            three_board_plus_count,
            yesterday_limit_up_avg_return,
            yesterday_limit_up_win_rate,
            data_source,
            coverage_ratio,
            generated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (trade_date)
        DO UPDATE SET
            limit_up_count = EXCLUDED.limit_up_count,
            limit_down_count = EXCLUDED.limit_down_count,
            touched_limit_up_count = EXCLUDED.touched_limit_up_count,
            failed_limit_up_count = EXCLUDED.failed_limit_up_count,
            failed_limit_up_rate = EXCLUDED.failed_limit_up_rate,
            max_consecutive_limit_up = EXCLUDED.max_consecutive_limit_up,
            three_board_plus_count = EXCLUDED.three_board_plus_count,
            yesterday_limit_up_avg_return = EXCLUDED.yesterday_limit_up_avg_return,
            yesterday_limit_up_win_rate = EXCLUDED.yesterday_limit_up_win_rate,
            data_source = EXCLUDED.data_source,
            coverage_ratio = EXCLUDED.coverage_ratio,
            generated_at = CURRENT_TIMESTAMP
    """, (
        sql_date,
        int(pool_df["is_limit_up"].sum()),
        int(pool_df["is_limit_down"].sum()),
        touched,
        failed,
        failed_rate,
        max_consecutive,
        three_board_plus,
        avg_return,
        win_rate,
        "limitup_daily_update",
        coverage_ratio,
    ))

    conn.commit()
    cur.close()
    conn.close()
    return {
        "trade_date": sql_date,
        "stock_count": int(len(pool_df)),
        "previous_trade_date": str(prev_date) if prev_date else None,
        "limit_up_count": int(pool_df["is_limit_up"].sum()),
        "touched_limit_up_count": touched,
        "failed_limit_up_count": failed,
        "failed_limit_up_rate": round(failed_rate, 4),
        "max_consecutive_limit_up": max_consecutive,
        "three_board_plus_count": three_board_plus,
        "coverage_ratio": round(coverage_ratio, 4),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="交易日期 YYYYMMDD 或 YYYY-MM-DD")
    args = parser.parse_args()
    result = update_limitup_daily(args.date)
    print(result)


if __name__ == "__main__":
    main()
