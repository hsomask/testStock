"""
流程文件完整性检查
运行：python -m analysis.pipeline_check --date 20260528
"""
import argparse
import json
from pathlib import Path

import psycopg2

from data.config import DATABASE_DSN

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily"

EXPECTED_FILES = [
    "daily_report_{}.md",
    "daily_summary_{}.json",
    "trade_plan_{}.md",
    "trade_plan_{}.json",
    "board_trend_report_{}.md",
    "board_trend_tracker_{}.xlsx",
    "board_trend_summary_{}.json",
    "board_mapping_quality_{}.md",
    "board_mapping_quality_{}.json",
    "board_alias_report_{}.md",
]

CRITICAL = [
    "daily_report_{}.md",
    "daily_summary_{}.json",
    "trade_plan_{}.md",
    "trade_plan_{}.json",
    "board_trend_summary_{}.json",
    "board_mapping_quality_{}.json",
]

STOCK_HIST_LIMIT_COLUMNS = [
    "name", "pre_close", "pct_chg", "amount", "turnover",
    "limit_ratio", "limit_up_price", "limit_down_price",
    "is_limit_up", "is_limit_down", "is_touched_limit_up",
    "is_failed_limit_up", "data_source", "updated_at",
]


def _sql_date(trade_date):
    return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"


def check_limitup_database(trade_date):
    checks = []
    if not DATABASE_DSN:
        return [{
            "name": "涨停生态数据库检查",
            "status": "WARN",
            "message": "DATABASE_DSN 未配置，跳过数据库检查",
        }]

    try:
        conn = psycopg2.connect(DATABASE_DSN)
        cur = conn.cursor()
    except Exception as e:
        return [{
            "name": "涨停生态数据库检查",
            "status": "WARN",
            "message": f"数据库连接失败: {e}",
        }]

    try:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'stock_hist_kline'
              AND column_name = ANY(%s)
            """,
            (STOCK_HIST_LIMIT_COLUMNS,),
        )
        found = {row[0] for row in cur.fetchall()}
        missing = sorted(set(STOCK_HIST_LIMIT_COLUMNS) - found)
        checks.append({
            "name": "stock_hist_kline 涨停字段",
            "status": "FAIL" if missing else "PASS",
            "message": "缺少字段: " + ", ".join(missing) if missing else "字段完整",
        })

        table_exists = {}
        for table in ["limitup_stock_pool", "limitup_daily_stats"]:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)",
                (table,),
            )
            exists = bool(cur.fetchone()[0])
            table_exists[table] = exists
            checks.append({
                "name": f"{table} 表存在",
                "status": "PASS" if exists else "WARN",
                "message": "已创建" if exists else "未创建，可运行 python -m analysis.init_db",
            })

        if table_exists.get("limitup_daily_stats"):
            cur.execute(
                "SELECT COUNT(*) FROM limitup_daily_stats WHERE trade_date=%s",
                (_sql_date(trade_date),),
            )
            stats_count = int(cur.fetchone()[0])
            checks.append({
                "name": "当日 limitup_daily_stats",
                "status": "PASS" if stats_count > 0 else "WARN",
                "message": "已生成" if stats_count > 0 else "未生成，日报应显示未生成状态",
            })

        cur.execute(
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(limit_up_price) AS limit_price_rows,
                COUNT(is_limit_up) AS limit_flag_rows
            FROM stock_hist_kline
            WHERE trade_date >= CURRENT_DATE - INTERVAL '120 days'
            """
        )
        total_rows, limit_price_rows, limit_flag_rows = cur.fetchone()
        coverage = min(
            (limit_price_rows or 0) / max(total_rows or 0, 1),
            (limit_flag_rows or 0) / max(total_rows or 0, 1),
        )
        checks.append({
            "name": "stock_hist_kline 历史字段回填覆盖率",
            "status": "PASS" if coverage >= 0.8 else "WARN",
            "message": (
                f"最近120天覆盖率 {coverage:.1%}"
                if coverage >= 0.8
                else f"最近120天覆盖率 {coverage:.1%}，可运行 python -m analysis.backfill_stock_hist_limit_fields --days 120"
            ),
        })
    except Exception as e:
        checks.append({
            "name": "涨停生态数据库检查",
            "status": "WARN",
            "message": f"检查失败: {e}",
        })
    finally:
        cur.close()
        conn.close()

    return checks


def check_limitup_report_content(trade_date):
    path = REPORTS_DIR / f"daily_report_{trade_date}.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    checks = []
    hardcoded_failed = "| 炸板率 | N/A | 数据不足 |" in text
    checks.append({
        "name": "日报炸板率硬编码 N/A",
        "status": "FAIL" if hardcoded_failed else "PASS",
        "message": "仍存在 | 炸板率 | N/A | 数据不足 |" if hardcoded_failed else "未发现硬编码炸板率 N/A",
    })
    for label in ["连板高度", "3板以上数量"]:
        has_clear_state = (
            f"| {label} | 未生成 |" in text
            or f"| {label} | N/A |" not in text
        )
        checks.append({
            "name": f"日报{label}状态",
            "status": "PASS" if has_clear_state else "WARN",
            "message": "已有明确状态" if has_clear_state else "仍为 N/A，建议重新生成日报",
        })
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, required=True, help="日期 YYYYMMDD")
    args = parser.parse_args()
    trade_date = args.date

    ok_files = []
    missing_files = []
    critical_missing = False
    print(f"=== 流程文件检查（{trade_date}）===\n")

    for pattern in EXPECTED_FILES:
        fname = pattern.format(trade_date)
        path = REPORTS_DIR / fname
        if path.exists():
            print(f"  [OK] {fname}")
            ok_files.append(fname)
        else:
            print(f"  [MISS] {fname}")
            missing_files.append(fname)
            if fname in [p.format(trade_date) for p in CRITICAL]:
                critical_missing = True

    critical_list = [f for f in missing_files if f in [p.format(trade_date) for p in CRITICAL]]
    non_critical_list = [f for f in missing_files if f not in [p.format(trade_date) for p in CRITICAL]]

    extra_checks = []
    extra_checks.extend(check_limitup_database(trade_date))
    extra_checks.extend(check_limitup_report_content(trade_date))
    for check in extra_checks:
        status_label = check["status"]
        print(f"  [{status_label}] {check['name']}: {check['message']}")

    has_extra_fail = any(check["status"] == "FAIL" for check in extra_checks)
    if critical_list or has_extra_fail:
        status = "critical"
    elif non_critical_list or any(check["status"] == "WARN" for check in extra_checks):
        status = "warning"
    else:
        status = "ok"

    result = {
        "trade_date": trade_date,
        "status": status,
        "ok_files": ok_files,
        "missing_files": missing_files,
        "critical_missing": critical_list,
        "non_critical_missing": non_critical_list,
        "has_critical_missing": bool(critical_list),
        "warnings": [w for w in [
            f"关键缺失: {len(critical_list)}" if critical_list else "",
            *(f"非关键缺失: {f}" for f in non_critical_list),
            *(f"{c['name']}: {c['message']}" for c in extra_checks if c["status"] == "WARN"),
        ] if w],
        "extra_checks": extra_checks,
        "generated_at": f"{trade_date}",
    }
    json_path = REPORTS_DIR / f"pipeline_check_{trade_date}.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== {len(ok_files)} OK / {len(missing_files)} MISSING === (JSON: {json_path})")


if __name__ == "__main__":
    main()
