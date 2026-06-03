"""
观察池评价结果查询（只读）
  python -m analysis.evaluation_query --latest
  python -m analysis.evaluation_query --mode daily --days 10
  python -m analysis.evaluation_query --mode range --days 30
  python -m analysis.evaluation_query --days 10 --output-md
"""
import argparse
import json
import sys
from datetime import datetime

import psycopg2

from data.config import DATABASE_DSN, REPORT_DIR


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


def fetch_summaries(cur, mode, days, latest_only=False):
    """查询 watchlist_evaluation_summary"""
    limit = "LIMIT 1" if latest_only else f"LIMIT {days * 2}"
    cur.execute(
        f"SELECT generated_at, eval_mode, signal_date, as_of_date, eval_start_date, eval_end_date, "
        f"total_signals, evaluated_1d, coverage_1d, evaluated_3d, coverage_3d, "
        f"confidence_level, conclusion_level, layer_inversion_warning, risk_warning, "
        f"price_fetch_failed, diagnostics_json, summary_json "
        f"FROM watchlist_evaluation_summary "
        f"WHERE eval_mode = %s "
        f"ORDER BY generated_at DESC {limit}",
        (mode,),
    )
    rows = cur.fetchall()
    summaries = []
    for row in rows:
        d = dict(zip([
            "generated_at", "eval_mode", "signal_date", "as_of_date",
            "eval_start_date", "eval_end_date",
            "total_signals", "evaluated_1d", "coverage_1d", "evaluated_3d", "coverage_3d",
            "confidence_level", "conclusion_level", "layer_inversion_warning", "risk_warning",
            "price_fetch_failed", "diagnostics_json", "summary_json",
        ], row))
        # Parse diagnostics_json
        diag = {}
        if d["diagnostics_json"]:
            try:
                diag = json.loads(d["diagnostics_json"]) if isinstance(d["diagnostics_json"], str) else d["diagnostics_json"]
            except (json.JSONDecodeError, TypeError):
                pass
        d["_diag"] = diag
        summaries.append(d)
    return summaries


def _yn(val):
    return "YES" if val else "no"


def _pct(val):
    if val is None:
        return "N/A"
    return f"{float(val) * 100:.1f}%"


def print_table(summaries):
    """终端表格"""
    header = f"{'time':<16} {'mode':<6} {'signal':<10} {'as_of':<10} {'total':>5} {'1d':>4} {'1dcov':>7} {'3d':>4} {'3dcov':>7} {'inv':>4} {'risk':>5} {'fail':>5} {'conclusion':<16}"
    print(header)
    print("-" * len(header))
    for s in summaries:
        ts = str(s["generated_at"])[:16] if s["generated_at"] else "N/A"
        print(
            f"{ts:<16} {s['eval_mode']:<6} {(s['signal_date'] or s['eval_start_date'] or '')[:10]:<10} "
            f"{(s['as_of_date'] or '')[:10]:<10} {s['total_signals'] or 0:>5} {s['evaluated_1d'] or 0:>4} "
            f"{_pct(s['coverage_1d']):>7} {s['evaluated_3d'] or 0:>4} {_pct(s['coverage_3d']):>7} "
            f"{_yn(s['layer_inversion_warning']):>4} {_yn(s['risk_warning']):>5} "
            f"{s['price_fetch_failed'] or 0:>5} {(s['conclusion_level'] or ''):<16}"
        )


def print_trend(summaries):
    """趋势摘要"""
    if not summaries:
        print("\n[无数据]")
        return

    daily_count = sum(1 for s in summaries if s["eval_mode"] == "daily")
    range_count = sum(1 for s in summaries if s["eval_mode"] == "range")
    inv_count = sum(1 for s in summaries if s["layer_inversion_warning"])
    risk_count = sum(1 for s in summaries if s["risk_warning"])
    cov1d_vals = [float(s["coverage_1d"]) for s in summaries if s["coverage_1d"] is not None]
    cov3d_vals = [float(s["coverage_3d"]) for s in summaries if s["coverage_3d"] is not None]
    fail_total = sum(s["price_fetch_failed"] or 0 for s in summaries)
    avg_cov1d = sum(cov1d_vals) / len(cov1d_vals) if cov1d_vals else 0

    # 连续倒挂检查
    daily_records = [s for s in summaries if s["eval_mode"] == "daily"]
    daily_records.sort(key=lambda s: str(s["generated_at"] or ""), reverse=True)
    consecutive_inv = 0
    for s in daily_records:
        if s["layer_inversion_warning"]:
            consecutive_inv += 1
        else:
            break
    consecutive_risk = 0
    for s in daily_records:
        if s["risk_warning"]:
            consecutive_risk += 1
        else:
            break

    # 弱/强策略提取
    weak_all = []
    strong_all = []
    for s in summaries:
        diag = s.get("_diag", {})
        sd = diag.get("strategy_diagnostics", {})
        for entry in sd.get("underperforming_strategies", []):
            if entry["strategy"] not in weak_all:
                weak_all.append(entry["strategy"])
        for entry in sd.get("outperforming_strategies", []):
            if entry["strategy"] not in strong_all:
                strong_all.append(entry["strategy"])

    print(f"\n{'='*50}")
    print("趋势摘要")
    print(f"{'='*50}")
    print(f"  记录数: {len(summaries)} (daily {daily_count}, range {range_count})")
    print(f"  分层倒挂次数: {inv_count}")
    print(f"  风险警告次数: {risk_count}")
    print(f"  平均 coverage_1d: {_pct(avg_cov1d)}")
    print(f"  平均 coverage_3d: {_pct(sum(cov3d_vals) / len(cov3d_vals)) if cov3d_vals else 0}")
    print(f"  price_fetch_failed 总数: {fail_total}")

    if weak_all:
        print(f"  弱表现策略: {', '.join(weak_all)}")
    if strong_all:
        print(f"  强表现策略: {', '.join(strong_all)}")

    if consecutive_inv >= 3:
        print(f"\n  [WARN] 连续 {consecutive_inv} 天分层倒挂，需重点观察，但不建议自动调参。")
    if consecutive_risk >= 3:
        print(f"  [WARN] 连续 {consecutive_risk} 天高风险提示未兑现，需后续复盘风险分层逻辑。")
    if avg_cov1d < 0.8:
        print(f"  [WARN] 1 日覆盖率 {_pct(avg_cov1d)} 不足 80%，评价数据仍不稳定。")


def build_markdown(summaries):
    """生成 Markdown 报告"""
    lines = [
        "# 观察池评价结果查询",
        "",
        f"  查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"  记录数: {len(summaries)}",
        "",
        "## 1. 评价记录列表",
        "",
        "| 时间 | 模式 | 信号日 | as_of | 总数 | 1d | 1d覆盖 | 3d | 3d覆盖 | 分层倒挂 | 风险警告 | 结论 |",
        "|------|------|--------|-------|------|----|--------|----|--------|----------|----------|------|",
    ]
    for s in summaries:
        ts = str(s["generated_at"])[:16] if s["generated_at"] else "N/A"
        lines.append(
            f"| {ts} | {s['eval_mode']} | {s.get('signal_date') or s.get('eval_start_date') or ''} "
            f"| {s.get('as_of_date') or ''} | {s['total_signals'] or 0} | {s['evaluated_1d'] or 0} "
            f"| {_pct(s['coverage_1d'])} | {s['evaluated_3d'] or 0} | {_pct(s['coverage_3d'])} "
            f"| {_yn(s['layer_inversion_warning'])} | {_yn(s['risk_warning'])} | {s.get('conclusion_level') or ''} |"
        )

    lines += [
        "",
        "## 2. 覆盖率趋势",
        "",
    ]
    cov_data = [(str(s["generated_at"])[:10], s["coverage_1d"], s["coverage_3d"]) for s in summaries]
    for date, c1, c3 in cov_data:
        lines.append(f"  - {date}: 1d={_pct(c1)}, 3d={_pct(c3)}")

    lines += [
        "",
        "## 3. 分层倒挂与风险警告",
        "",
    ]
    inv_list = [s for s in summaries if s["layer_inversion_warning"]]
    risk_list = [s for s in summaries if s["risk_warning"]]
    lines.append(f"  - 分层倒挂记录: {len(inv_list)} 次")
    lines.append(f"  - 风险警告记录: {len(risk_list)} 次")

    lines += [
        "",
        "## 4. 策略表现提示",
        "",
    ]
    weak_all, strong_all = [], []
    for s in summaries:
        diag = s.get("_diag", {})
        sd = diag.get("strategy_diagnostics", {})
        for entry in sd.get("underperforming_strategies", []):
            if entry["strategy"] not in weak_all:
                weak_all.append(entry["strategy"])
        for entry in sd.get("outperforming_strategies", []):
            if entry["strategy"] not in strong_all:
                strong_all.append(entry["strategy"])
    lines.append(f"  - 弱表现策略: {', '.join(weak_all) if weak_all else '(无)'}")
    lines.append(f"  - 强表现策略: {', '.join(strong_all) if strong_all else '(无)'}")

    lines += [
        "",
        "## 5. 趋势摘要",
        "",
        "> 本查询基于 watchlist_evaluation_summary，只用于复盘评价系统是否稳定，不构成实盘买卖建议。",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="观察池评价结果查询")
    parser.add_argument("--latest", action="store_true", default=False, help="仅最新一条")
    parser.add_argument("--mode", type=str, default="daily", choices=["daily", "range"], help="评价模式")
    parser.add_argument("--days", type=int, default=10, help="查询最近 N 天")
    parser.add_argument("--output-md", action="store_true", default=False, help="输出 Markdown 文件")
    args = parser.parse_args()

    if not DATABASE_DSN:
        print("[ERROR] DATABASE_DSN 未设置")
        sys.exit(1)

    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"[ERROR] 数据库连接失败: {e}")
        sys.exit(1)

    cur = conn.cursor()
    if not table_exists(cur, "watchlist_evaluation_summary"):
        print("[ERROR] watchlist_evaluation_summary 表不存在，请先运行 python -m analysis.init_db")
        cur.close()
        conn.close()
        sys.exit(1)

    summaries = fetch_summaries(cur, args.mode, args.days, latest_only=args.latest)
    cur.close()
    conn.close()

    if not summaries:
        print(f"无 {args.mode} 评价记录")
        return

    print(f"\n{'='*50}")
    print(f"查询: {args.mode} 模式, {'最新 1 条' if args.latest else f'最近 {args.days} 天'}, 共 {len(summaries)} 条")
    print(f"{'='*50}\n")

    print_table(summaries)
    print_trend(summaries)

    if args.output_md:
        md = build_markdown(summaries)
        eval_dir = REPORT_DIR / "evaluation"
        eval_dir.mkdir(parents=True, exist_ok=True)
        md_path = eval_dir / f"evaluation_query_{datetime.now().strftime('%Y%m%d')}.md"
        md_path.write_text(md, encoding="utf-8")
        print(f"\nMarkdown: {md_path}")


if __name__ == "__main__":
    main()
