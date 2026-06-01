"""
数据库数据可信性审计：扫描非交易日污染
运行：python -m analysis.db_data_audit --date 20260531
      python -m analysis.db_data_audit --days 30
"""
import argparse
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2

from data.config import DATABASE_DSN, REPORT_DIR
from analysis.data_fetcher import is_trade_day

logger = logging.getLogger(__name__)

AUDIT_TABLES = [
    "stock_signal",
    "board_amount_ratio",
    "pipeline_job_log",
    "signal_tracker",
    "signal_performance",
    "backtest_result",
]


def get_db_conn():
    if not DATABASE_DSN:
        return None
    return psycopg2.connect(DATABASE_DSN)


def table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return cur.fetchone()[0]


def has_trade_date_column(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = 'trade_date')",
        (table_name,),
    )
    return cur.fetchone()[0]


def collect_audit_data(conn, date_list):
    """扫描所有审计表，返回按日期分组的异常数据"""
    cur = conn.cursor()
    checked_tables = []
    skipped_tables = []
    invalid_dates = {}  # {date_str: {is_trade_day: bool, tables: {table: {rows, issue}}}}
    cleanup_candidates = []

    for table_name in AUDIT_TABLES:
        if not table_exists(cur, table_name):
            skipped_tables.append({"table": table_name, "reason": "table not found"})
            logger.info(f"跳过 {table_name}：表不存在")
            continue

        if not has_trade_date_column(cur, table_name):
            skipped_tables.append({"table": table_name, "reason": "no trade_date column"})
            logger.info(f"跳过 {table_name}：无 trade_date 字段")
            continue

        checked_tables.append(table_name)

        # 查询每个日期的行数
        cur.execute(
            f'SELECT trade_date::text, COUNT(*) FROM "{table_name}" GROUP BY trade_date ORDER BY trade_date DESC'
        )
        rows = cur.fetchall()

        for trade_date, count in rows:
            # 统一日期格式 YYYYMMDD（数据库可能返回 YYYY-MM-DD）
            date_str = str(trade_date).replace("-", "")[:8]

            # 按日期范围过滤
            if date_list and date_str not in date_list:
                continue

            is_trade = is_trade_day(date_str)

            if not is_trade:
                if date_str not in invalid_dates:
                    invalid_dates[date_str] = {"is_trade_day": False, "tables": {}}

                invalid_dates[date_str]["tables"][table_name] = {
                    "rows": count,
                    "issue": "非交易日存在数据",
                }

                cleanup_candidates.append({
                    "table": table_name,
                    "trade_date": date_str,
                    "rows": count,
                })

    cur.close()
    return checked_tables, skipped_tables, invalid_dates, cleanup_candidates


def generate_date_list(date_str, days):
    """生成待检查的日期列表"""
    if date_str:
        return {date_str}
    if days:
        dates = set()
        for i in range(days):
            d = datetime.now() - timedelta(days=i)
            dates.add(d.strftime("%Y%m%d"))
        return dates
    return set()


def main():
    parser = argparse.ArgumentParser(description="数据库数据可信性审计")
    parser.add_argument("--date", type=str, default=None, help="检查指定日期 YYYYMMDD")
    parser.add_argument("--days", type=int, default=None, help="检查最近 N 天")
    args = parser.parse_args()

    date_list = generate_date_list(args.date, args.days)
    if not date_list:
        # 默认最近 30 天
        date_list = generate_date_list(None, 30)

    print(f"=== 数据库可信性审计 ===")
    print(f"检查范围: {len(date_list)} 天")
    print(f"检查表: {', '.join(AUDIT_TABLES)}\n")

    if not DATABASE_DSN:
        print("[ERROR] DATABASE_DSN 未配置，无法连接数据库")
        return

    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"[ERROR] 数据库连接失败: {e}")
        return

    try:
        checked, skipped, invalid_dates, cleanup_candidates = collect_audit_data(conn, date_list)
    except Exception as e:
        print(f"[ERROR] 审计过程出错: {e}")
        conn.close()
        return
    finally:
        conn.close()

    # ── 输出摘要 ──
    print(f"已检查表: {len(checked)} — {', '.join(checked) if checked else '(无)'}")
    for s in skipped:
        print(f"  跳过: {s['table']} ({s['reason']})")

    print(f"\n异常日期数: {len(invalid_dates)}")
    for date_str in sorted(invalid_dates.keys()):
        info = invalid_dates[date_str]
        print(f"\n  {date_str} (非交易日):")
        for tbl, detail in info["tables"].items():
            print(f"    [{tbl}] {detail['rows']} 行 — {detail['issue']}")

    if not invalid_dates:
        print("  无异常数据 OK")

    print(f"\n清理候选: {len(cleanup_candidates)} 条")

    # ── 确定状态 ──
    if not checked:
        status = "warning"
    elif invalid_dates:
        status = "failed"
    else:
        status = "ok"

    # ── 写 JSON ──
    report = {
        "status": status,
        "checked_tables": checked,
        "skipped_tables": skipped,
        "invalid_dates": invalid_dates,
        "cleanup_candidates": cleanup_candidates,
    }
    daily_dir = REPORT_DIR / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    json_path = daily_dir / "db_data_audit.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON 已生成: {json_path}")


if __name__ == "__main__":
    main()
