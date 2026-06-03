"""
Evaluation 调度检查（只读，不执行，不写库）
  python -m analysis.evaluation_scheduler_check
  python -m analysis.evaluation_scheduler_check --as-of 20260529
  python -m analysis.evaluation_scheduler_check --signal-date 20260528 --as-of 20260529
  python -m analysis.evaluation_scheduler_check --json
"""
import argparse
import json
import sys
from datetime import datetime

import psycopg2

from data.config import DATABASE_DSN
from analysis.data_fetcher import is_trade_day


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


def infer_signal_date(cur, as_of_date):
    """从 stock_signal 取小于 as_of_date 的最大 trade_date"""
    sql_date = f"{as_of_date[:4]}-{as_of_date[4:6]}-{as_of_date[6:8]}"
    cur.execute(
        "SELECT MAX(trade_date) FROM stock_signal WHERE trade_date < %s",
        (sql_date,),
    )
    row = cur.fetchone()
    if row and row[0]:
        td = row[0]
        return td.strftime("%Y%m%d") if hasattr(td, "strftime") else str(td).replace("-", "")[:8]
    return None


def check_stock_signal(cur, signal_date):
    sql_date = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}"
    cur.execute("SELECT COUNT(*) FROM stock_signal WHERE trade_date = %s", (sql_date,))
    return cur.fetchone()[0]


def check_existing_evaluation(cur, signal_date, as_of_date):
    if not table_exists(cur, "watchlist_evaluation_summary"):
        return -1  # 表不存在
    cur.execute(
        "SELECT COUNT(*) FROM watchlist_evaluation_summary "
        "WHERE eval_mode = 'daily' AND signal_date = %s AND as_of_date = %s",
        (signal_date, as_of_date),
    )
    return cur.fetchone()[0]


def check_price_cache(cur, signal_date, as_of_date):
    """检查 signal 股票中已有 as_of 行情的比例"""
    if not table_exists(cur, "stock_hist_kline"):
        return 0, 0, 0

    sql_signal = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}"
    sql_asof = f"{as_of_date[:4]}-{as_of_date[4:6]}-{as_of_date[6:8]}"

    cur.execute("SELECT COUNT(DISTINCT code) FROM stock_signal WHERE trade_date = %s", (sql_signal,))
    signal_count = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(DISTINCT s.code) FROM stock_signal s "
        "JOIN stock_hist_kline h ON s.code = h.code "
        "WHERE s.trade_date = %s AND h.trade_date = %s",
        (sql_signal, sql_asof),
    )
    cached_count = cur.fetchone()[0]

    coverage = cached_count / signal_count if signal_count > 0 else 0
    return signal_count, cached_count, coverage


def main():
    parser = argparse.ArgumentParser(description="Evaluation 调度检查（只读）")
    parser.add_argument("--as-of", type=str, default=None, help="评价基准日 YYYYMMDD（默认今天）")
    parser.add_argument("--signal-date", type=str, default=None, help="信号日期 YYYYMMDD")
    parser.add_argument("--json", action="store_true", default=False, dest="json_output", help="JSON 输出")
    args = parser.parse_args()

    as_of_date = args.as_of if args.as_of else datetime.now().strftime("%Y%m%d")
    signal_date = args.signal_date
    warnings = []

    if not DATABASE_DSN:
        result = {"status": "error", "message": "DATABASE_DSN 未配置"}
        if args.json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("[ERROR] DATABASE_DSN 未配置")
        sys.exit(1)

    try:
        conn = get_db_conn()
    except Exception as e:
        result = {"status": "error", "message": f"数据库连接失败: {e}"}
        if args.json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"[ERROR] 数据库连接失败: {e}")
        sys.exit(1)

    cur = conn.cursor()

    # ── 交易日检查 ──
    trade_day_ok = is_trade_day(as_of_date)
    if not trade_day_ok:
        result = {"status": "skip", "reason": f"{as_of_date} 非交易日"}
        if args.json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"[SKIP] {as_of_date} 非交易日，不建议运行 evaluation")
        cur.close()
        conn.close()
        return

    # ── signal_date 推断 ──
    if not signal_date:
        if not table_exists(cur, "stock_signal"):
            result = {"status": "error", "reason": "stock_signal 表不存在"}
            if args.json_output:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("[ERROR] stock_signal 表不存在，无法推断 signal_date")
            cur.close()
            conn.close()
            sys.exit(1)

        signal_date = infer_signal_date(cur, as_of_date)
        if not signal_date:
            result = {"status": "skip", "reason": f"无法推断 signal_date（as_of={as_of_date}）"}
            if args.json_output:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"[SKIP] 无法推断 signal_date，as_of={as_of_date} 之前无 stock_signal 数据")
            cur.close()
            conn.close()
            return

    # ── stock_signal 检查 ──
    if not table_exists(cur, "stock_signal"):
        result = {"status": "error", "reason": "stock_signal 表不存在"}
        if args.json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("[ERROR] stock_signal 表不存在，无法检查")
        cur.close()
        conn.close()
        sys.exit(1)

    signal_count = check_stock_signal(cur, signal_date)
    if signal_count == 0:
        result = {"status": "skip", "reason": f"{signal_date} 无 stock_signal 数据"}
        if args.json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"[SKIP] {signal_date} 无 stock_signal 数据，不建议运行 evaluation")
        cur.close()
        conn.close()
        return

    # ── 已有 evaluation 检查 ──
    existing_count = check_existing_evaluation(cur, signal_date, as_of_date)
    summary_table_exists = existing_count >= 0
    if existing_count < 0:
        warnings.append("watchlist_evaluation_summary 表不存在，请先运行 python -m analysis.init_db")
    elif existing_count > 0:
        warnings.append(f"已存在 {existing_count} 条 daily evaluation 记录，重复运行将触发 upsert 覆盖")

    # ── 行情缓存覆盖率 ──
    sig_cnt, cached_cnt, cache_cov = check_price_cache(cur, signal_date, as_of_date)
    defer_evaluation = (cache_cov < 0.8 and sig_cnt > 0)

    cur.close()
    conn.close()

    # ── 推荐命令 ──
    if defer_evaluation:
        recommended = []
    else:
        recommended = [
            f"python -m analysis.watchlist_evaluation --mode daily --signal-date {signal_date} --as-of {as_of_date} --save-db",
            "python -m analysis.evaluation_query --latest",
        ]

    # ── 状态判定 ──
    if signal_count == 0 or not trade_day_ok:
        status = "skip"
    elif defer_evaluation:
        status = "defer"
        warnings.append(f"as_of 行情缓存覆盖率 {cache_cov:.1%}，低于 80%，暂缓 evaluation")
    elif warnings:
        status = "warning"
    else:
        status = "ready"

    # ── 输出 ──
    if args.json_output:
        output = {
            "status": status,
            "signal_date": signal_date,
            "as_of_date": as_of_date,
            "is_trade_day": trade_day_ok,
            "signal_count": signal_count,
            "existing_evaluation": existing_count > 0,
            "summary_table_exists": summary_table_exists,
            "price_cache_coverage": cache_cov,
            "price_cache_cached": cached_cnt,
            "price_cache_signal_total": sig_cnt,
            "warnings": warnings,
            "recommended_commands": recommended,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print("=== Evaluation Scheduler Check ===\n")
        print(f"  as_of_date:    {as_of_date}")
        print(f"  signal_date:   {signal_date}")
        print(f"  交易日检查:    {'OK' if trade_day_ok else 'FAIL'}")
        print(f"  stock_signal:  {signal_count} 条")
        print(f"  已有评价记录:  {'是' if existing_count > 0 else '否'}")
        if sig_cnt > 0:
            print(f"  行情缓存覆盖:  {cached_cnt}/{sig_cnt} = {cache_cov:.1%}")
        else:
            print(f"  行情缓存覆盖:  N/A（无信号或 hist_kline 表不存在）")

        print(f"\n  状态: {status.upper()}")
        if warnings:
            print("  原因:")
            for w in warnings:
                print(f"    - {w}")

        print(f"\n  建议命令:")
        for cmd in recommended:
            print(f"  {cmd}")


if __name__ == "__main__":
    main()
