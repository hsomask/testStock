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
from analysis.data_fetcher import is_trade_day, get_stock_history


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


def check_signal_pool_coverage(cur, signal_date, as_of_date, try_fill=True):
    """
    按观察池股票（stock_signal.code）检查行情覆盖率。
    如果覆盖率不足且 try_fill=True，尝试 get_stock_history 补齐缺失 K 线。
    返回 (signal_count, covered_count, coverage, missing_codes, scope)
    """
    sql_signal = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}"
    sql_asof = f"{as_of_date[:4]}-{as_of_date[4:6]}-{as_of_date[6:8]}"

    if not table_exists(cur, "stock_signal"):
        return 0, 0, 0, [], "no_signal_table"

    # 获取观察池股票列表
    cur.execute("SELECT DISTINCT code FROM stock_signal WHERE trade_date = %s", (sql_signal,))
    signal_codes = [row[0] for row in cur.fetchall()]
    signal_count = len(signal_codes)

    if signal_count == 0:
        return 0, 0, 0, [], "no_signal_pool"

    # 检查每只股票是否有 signal_date 和 as_of_date 的 K 线
    covered = 0
    missing_codes = []

    for code in signal_codes:
        cur.execute(
            "SELECT COUNT(*) FROM stock_hist_kline WHERE code = %s AND trade_date IN (%s, %s)",
            (code, sql_signal, sql_asof),
        )
        days_found = cur.fetchone()[0]
        if days_found >= 2:
            covered += 1
        else:
            missing_codes.append(code)

    coverage = covered / signal_count if signal_count > 0 else 0

    # 如果覆盖不足，尝试补齐缺失股票的 K 线
    if try_fill and coverage < 0.8 and missing_codes:
        import sys as _sys
        print(f"  观察池行情覆盖率 {coverage:.1%}，尝试补齐 {len(missing_codes)} 只缺失股票...", file=_sys.stderr)
        filled = 0
        for code in missing_codes:
            try:
                # 先用 80 天走缓存，不够再用 500 天绕过缓存
                hist = get_stock_history(code, days=80)
                if hist is not None and not hist.empty:
                    dates = hist["date"].astype(str).str[:10]
                    last_date = dates.max()
                    if last_date < sql_asof:
                        hist = get_stock_history(code, days=500)
                if hist is not None and not hist.empty:
                    filled += 1
            except Exception:
                pass
        print(f"  补齐完成：{filled}/{len(missing_codes)}", file=_sys.stderr)

        # 重新计算覆盖率
        covered2 = 0
        missing2 = []
        for code in signal_codes:
            cur.execute(
                "SELECT COUNT(*) FROM stock_hist_kline WHERE code = %s AND trade_date IN (%s, %s)",
                (code, sql_signal, sql_asof),
            )
            if cur.fetchone()[0] >= 2:
                covered2 += 1
            else:
                missing2.append(code)
        covered = covered2
        missing_codes = missing2
        coverage = covered / signal_count if signal_count > 0 else 0

    return signal_count, covered, coverage, missing_codes, "signal_pool"


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

    # ── 观察池行情覆盖率 ──
    sig_cnt, covered_cnt, cache_cov, missing_codes, cov_scope = check_signal_pool_coverage(
        cur, signal_date, as_of_date, try_fill=True
    )
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
    elif cov_scope == "no_signal_pool":
        status = "defer"
        warnings.append("未找到昨日观察池，T+1 复盘暂缓")
    elif defer_evaluation:
        status = "defer"
        warnings.append(f"观察池价格覆盖率 {cache_cov:.1%}，低于 80%，暂缓 evaluation")
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
            "coverage_scope": cov_scope,
            "price_cache_cached": covered_cnt,
            "price_cache_signal_total": sig_cnt,
            "missing_codes": missing_codes[:10],
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
            print(f"  观察池行情:    {covered_cnt}/{sig_cnt} = {cache_cov:.1%}（范围: {cov_scope}）")
        else:
            print(f"  观察池行情:    N/A（无信号数据）")

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
