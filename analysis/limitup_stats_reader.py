"""
Read daily limit-up ecology aggregate stats for reports.
"""
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

from data.config import DATABASE_DSN


def _normalize_trade_date(trade_date: str) -> str:
    text = str(trade_date or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return datetime.fromisoformat(text[:10]).date().isoformat()


def load_limitup_daily_stats(trade_date: str) -> dict:
    """
    Load aggregated limit-up ecology stats for trade_date.

    Missing table/row is a report WARN-level condition, not a hard failure.
    """
    if not DATABASE_DSN:
        return {"status": "missing", "reason": "DATABASE_DSN 未配置"}

    try:
        sql_date = _normalize_trade_date(trade_date)
    except Exception:
        return {"status": "missing", "reason": f"交易日期格式无效: {trade_date}"}

    try:
        conn = psycopg2.connect(DATABASE_DSN)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
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
            FROM limitup_daily_stats
            WHERE trade_date = %s
            """,
            (sql_date,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        return {"status": "missing", "reason": f"涨停生态日表不可用: {e}"}

    if not row:
        return {"status": "missing", "reason": "limitup_daily_stats 未生成"}

    result = dict(row)
    result["status"] = "ok"
    result["trade_date"] = str(result.get("trade_date"))
    if result.get("generated_at") is not None:
        result["generated_at"] = result["generated_at"].isoformat()
    return result
