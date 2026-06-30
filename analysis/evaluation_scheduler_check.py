"""
Evaluation scheduler check.

This module decides whether the formal watchlist evaluation can run for an
as-of date. It also asks the K-line coverage guard to maximize coverage before
returning READY/DEFER.

Examples:
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
from analysis.ensure_signal_kline_coverage import ensure_signal_kline_coverage


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


def _sql_date(yyyymmdd):
    s = str(yyyymmdd).replace("-", "")[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def infer_signal_date(cur, as_of_date):
    sql_date = _sql_date(as_of_date)
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
    cur.execute("SELECT COUNT(*) FROM stock_signal WHERE trade_date = %s", (_sql_date(signal_date),))
    return cur.fetchone()[0]


def check_existing_evaluation(cur, signal_date, as_of_date):
    if not table_exists(cur, "watchlist_evaluation_summary"):
        return -1
    cur.execute(
        """
        SELECT COUNT(*)
        FROM watchlist_evaluation_summary
        WHERE eval_mode = 'daily' AND signal_date = %s AND as_of_date = %s
        """,
        (signal_date, as_of_date),
    )
    return cur.fetchone()[0]


def _status_message(defer_reason):
    msg_map = {
        "upstream_kline_lag": "今日 T+1 复盘因上游 K 线延迟暂缓，部分股票历史行情未更新到评价日。",
        "observer_pool_price_not_ready": "今日 T+1 复盘因观察池价格覆盖不足暂缓。",
        "no_signal_pool": "未找到昨日观察池，今日 T+1 复盘暂缓。",
    }
    return msg_map.get(defer_reason, "今日 T+1 复盘暂缓。")


def build_scheduler_result(args):
    as_of_date = args.as_of if args.as_of else datetime.now().strftime("%Y%m%d")
    signal_date = args.signal_date
    warnings = []

    if not DATABASE_DSN:
        return {"status": "error", "message": "DATABASE_DSN 未配置"}

    try:
        conn = get_db_conn()
    except Exception as exc:
        return {"status": "error", "message": f"数据库连接失败: {exc}"}

    try:
        cur = conn.cursor()

        trade_day_ok = is_trade_day(as_of_date)
        if not trade_day_ok:
            return {
                "status": "skip",
                "reason": f"{as_of_date} 非交易日",
                "as_of_date": as_of_date,
                "signal_date": signal_date or "",
                "is_trade_day": False,
            }

        if not table_exists(cur, "stock_signal"):
            return {"status": "error", "reason": "stock_signal 表不存在"}

        if not signal_date:
            signal_date = infer_signal_date(cur, as_of_date)
            if not signal_date:
                return {
                    "status": "skip",
                    "reason": f"无法推断 signal_date(as_of={as_of_date})",
                    "as_of_date": as_of_date,
                    "signal_date": "",
                    "is_trade_day": True,
                }

        signal_count = check_stock_signal(cur, signal_date)
        if signal_count == 0:
            return {
                "status": "skip",
                "reason": f"{signal_date} 无 stock_signal 数据",
                "as_of_date": as_of_date,
                "signal_date": signal_date,
                "is_trade_day": True,
                "signal_count": 0,
            }

        existing_count = check_existing_evaluation(cur, signal_date, as_of_date)
        summary_table_exists = existing_count >= 0
        if existing_count < 0:
            warnings.append("watchlist_evaluation_summary 表不存在，请先运行 python -m analysis.init_db")
        elif existing_count > 0:
            warnings.append(f"已存在 {existing_count} 条 daily evaluation 记录，重复运行将触发 upsert 覆盖")
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

    coverage_result = ensure_signal_kline_coverage(
        signal_date,
        as_of_date,
        time_budget=args.time_budget,
        deep=args.deep,
        min_coverage=0.80,
    )

    sig_cnt = coverage_result.get("signal_count", signal_count)
    covered_cnt = coverage_result.get("covered_count", 0)
    cache_cov = coverage_result.get("coverage", 0)
    missing_codes = coverage_result.get("missing_codes", [])
    upstream_lag_codes = coverage_result.get("upstream_lag_codes", [])
    upstream_lag_note = ""
    if upstream_lag_codes:
        upstream_lag_note = f"上游 K 线数据延迟（{len(upstream_lag_codes)} 只股票最新数据早于评价日）。"

    defer_evaluation = cache_cov < 0.8 and sig_cnt > 0
    recommended = []
    if not defer_evaluation:
        recommended = [
            f"python -m analysis.watchlist_evaluation --mode daily --signal-date {signal_date} --as-of {as_of_date} --save-db",
            "python -m analysis.evaluation_query --latest",
        ]

    defer_reason = ""
    status = "ready"
    if coverage_result.get("status") == "skip":
        status = "skip"
        defer_reason = "no_signal_pool"
    elif defer_evaluation:
        status = "defer"
        defer_reason = "upstream_kline_lag" if upstream_lag_codes else "observer_pool_price_not_ready"
        warnings.append(f"观察池价格覆盖率 {cache_cov:.1%}，低于 80%，暂缓 evaluation")
    elif warnings:
        status = "warning"

    warnings.extend(coverage_result.get("warnings", []))

    return {
        "status": status,
        "signal_date": signal_date,
        "as_of_date": as_of_date,
        "is_trade_day": True,
        "signal_count": sig_cnt,
        "stock_signal_rows": signal_count,
        "existing_evaluation": existing_count > 0,
        "summary_table_exists": summary_table_exists,
        "price_cache_coverage": cache_cov,
        "coverage_scope": "signal_pool",
        "price_cache_cached": covered_cnt,
        "price_cache_signal_total": sig_cnt,
        "missing_codes": missing_codes[:20],
        "attempted_fill": coverage_result.get("attempted_fill", 0),
        "fill_success": coverage_result.get("fill_success", 0),
        "upstream_lag_codes": upstream_lag_codes[:20],
        "upstream_lag_note": upstream_lag_note,
        "suspended_or_no_trade_codes": coverage_result.get("suspended_or_no_trade_codes", [])[:20],
        "defer_reason": defer_reason,
        "coverage_level": coverage_result.get("coverage_level", "defer"),
        "quality_weight": coverage_result.get("quality_weight", 0),
        "reason_counts": coverage_result.get("reason_counts", {}),
        "strategy_coverage": coverage_result.get("strategy_coverage", []),
        "risk_coverage": coverage_result.get("risk_coverage", []),
        "layer_coverage": coverage_result.get("layer_coverage", []),
        "elapsed_seconds": coverage_result.get("elapsed_seconds"),
        "warnings": warnings,
        "message": _status_message(defer_reason) if defer_reason else "",
        "recommended_commands": recommended,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluation 调度检查")
    parser.add_argument("--as-of", type=str, default=None, help="评价基准日 YYYYMMDD（默认今天）")
    parser.add_argument("--signal-date", type=str, default=None, help="信号日期 YYYYMMDD")
    parser.add_argument("--json", action="store_true", default=False, dest="json_output", help="JSON 输出")
    parser.add_argument("--time-budget", type=int, default=300, help="补齐 K 线最多耗时秒数")
    parser.add_argument("--deep", action="store_true", default=False, help="使用更深的历史 K 线补齐轮次")
    args = parser.parse_args()

    result = build_scheduler_result(args)

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("status") == "error":
            sys.exit(1)
        return

    print("=== Evaluation Scheduler Check ===\n")
    print(f"  as_of_date:    {result.get('as_of_date')}")
    print(f"  signal_date:   {result.get('signal_date')}")
    print(f"  交易日检查:    {'OK' if result.get('is_trade_day') else 'FAIL'}")
    print(f"  stock_signal:  {result.get('signal_count', 0)} 条")
    print(f"  已有评价记录:  {'是' if result.get('existing_evaluation') else '否'}")
    print(
        f"  观察池行情:    {result.get('price_cache_cached', 0)}/"
        f"{result.get('price_cache_signal_total', 0)} = {result.get('price_cache_coverage', 0):.1%}"
    )
    print(f"  质量层级:      {result.get('coverage_level')} weight={result.get('quality_weight')}")
    print(
        f"  补齐结果:      {result.get('fill_success', 0)}/"
        f"{result.get('attempted_fill', 0)}"
    )
    print(f"\n  状态: {result.get('status', '').upper()}")
    if result.get("warnings"):
        print("  原因:")
        for warning in result["warnings"]:
            print(f"    - {warning}")

    print("\n  建议命令:")
    for cmd in result.get("recommended_commands", []):
        print(f"  {cmd}")

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
