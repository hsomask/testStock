"""
流程验收脚本
运行：python -m analysis.validate_pipeline [--date YYYYMMDD]
检查 DB、表、指定日期文件、job_run_log 是否完整
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg2

from data.config import DATABASE_DSN

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily"


def _resolve_date(args_date):
    """解析日期：优先 --date → 最新 summary → 今天"""
    if args_date:
        return args_date
    files = sorted(REPORTS_DIR.glob("daily_summary_*.json"))
    if files:
        name = files[-1].stem  # daily_summary_20260522
        return name.replace("daily_summary_", "")
    return datetime.now().strftime("%Y%m%d")

REQUIRED_TABLES = [
    "stock_board_map",
    "board_amount_ratio",
    "data_quality_log",
    "stock_signal",
    "job_run_log",
    "signal_performance",
]

results = []
has_fail = False


def ok(msg):
    results.append(("OK", msg))
    print(f"  [OK] {msg}")


def warn(msg):
    results.append(("WARN", msg))
    print(f"  [WARN] {msg}")


def fail(msg):
    global has_fail
    has_fail = True
    results.append(("FAIL", msg))
    print(f"  [FAIL] {msg}")


def main():
    parser = argparse.ArgumentParser(description="流程验收检查")
    parser.add_argument("--date", type=str, default=None,
                        help="验收日期 YYYYMMDD，默认取最新 summary 日期或今天")
    args = parser.parse_args()
    trade_date = _resolve_date(args.date)

    print(f"=== 流程验收检查（{trade_date}）===\n")

    # 1. DATABASE_DSN
    print("1. 数据库配置")
    if DATABASE_DSN:
        ok("DATABASE_DSN 已配置")
    else:
        fail("DATABASE_DSN 未配置")
        return

    # 2. DB 连接
    print("\n2. 数据库连接")
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_DSN)
        ok("数据库连接成功")
    except Exception as e:
        fail(f"数据库连接失败：{e}")
        return

    cur = conn.cursor()

    # 3. 必要表
    print("\n3. 必要表检查")
    for table in REQUIRED_TABLES:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)",
            (table,)
        )
        if cur.fetchone()[0]:
            ok(f"{table} 存在")
        else:
            fail(f"{table} 不存在")

    # 4. stock_board_map 数据
    print("\n4. stock_board_map")
    cur.execute("SELECT COUNT(*) FROM stock_board_map")
    count = cur.fetchone()[0]
    if count > 0:
        ok(f"stock_board_map 有 {count} 条记录")
    else:
        warn("stock_board_map 为空，请运行 stock_board_mapper")

    # 5. 今日 data_quality_log
    print("\n5. 今日 data_quality_log")
    cur.execute("SELECT COUNT(*) FROM data_quality_log WHERE trade_date=%s", (trade_date,))
    if cur.fetchone()[0] > 0:
        ok("今日 data_quality_log 有记录")
    else:
        fail("今日 data_quality_log 无记录")

    # 6. 今日 stock_signal
    print("\n6. 今日 stock_signal")
    cur.execute("SELECT COUNT(*) FROM stock_signal WHERE trade_date=%s", (trade_date,))
    ss_count = cur.fetchone()[0]
    if ss_count > 0:
        ok(f"stock_signal 今日有 {ss_count} 条")
    else:
        fail("今日 stock_signal 无记录")

    # 7. signal_performance（近 10 日）
    print("\n7. signal_performance")
    from datetime import timedelta
    td = datetime.strptime(trade_date, "%Y%m%d")
    ten_days_ago = (td - timedelta(days=10)).strftime("%Y%m%d")
    cur.execute(
        "SELECT COUNT(*) FROM signal_performance WHERE trade_date>=%s AND trade_date<=%s",
        (ten_days_ago, trade_date)
    )
    sp_count = cur.fetchone()[0]
    if sp_count > 0:
        ok(f"signal_performance 近10日有 {sp_count} 条")
    else:
        warn("signal_performance 近10日暂无数据，可能需要等待 T+1")

    # 8. 指定日期文件
    print("\n8. 今日文件检查")
    files_to_check = [
        ("daily_summary", "daily_summary_{}.json"),
        ("trade_plan", "trade_plan_{}.json"),
        ("小白版报告", "daily_report_{}.md"),
        ("专业版报告", "daily_report_{}_pro.md"),
    ]
    for label, pattern in files_to_check:
        path = REPORTS_DIR / pattern.format(trade_date)
        if path.exists():
            ok(f"{label} 存在")
        else:
            fail(f"{label} 不存在")

    # 9. job_run_log 最近状态
    print("\n9. 最近 job_run_log")
    cur.execute(
        "SELECT job_name, status, duration_seconds FROM job_run_log "
        "WHERE trade_date=%s ORDER BY started_at DESC LIMIT 5",
        (trade_date,)
    )
    jobs = cur.fetchall()
    if jobs:
        for job_name, status, duration in jobs:
            dur_str = f"{duration:.0f}s" if duration else "-"
            if status == "success":
                ok(f"{job_name}: {status} ({dur_str})")
            else:
                fail(f"{job_name}: {status} ({dur_str})")
    else:
        warn("今日无 job_run_log 记录")

    cur.close()
    conn.close()

    # 汇总
    ok_count = sum(1 for r in results if r[0] == "OK")
    warn_count = sum(1 for r in results if r[0] == "WARN")
    fail_count = sum(1 for r in results if r[0] == "FAIL")

    print(f"\n=== 验收完成：{ok_count} OK / {warn_count} WARN / {fail_count} FAIL ===\n")

    if has_fail:
        print("存在 FAIL 项，请修复后重新验收。")
        sys.exit(1)
    else:
        print("所有检查通过。")


if __name__ == "__main__":
    main()
