"""
Evaluation 自检邮件发送（独立模块，不与日报邮件混用）
  python -m analysis.evaluation_email_sender --latest --dry-run
  python -m analysis.evaluation_email_sender --latest
  python -m analysis.evaluation_email_sender --date 20260529 --dry-run
  python -m analysis.evaluation_email_sender --latest --to user@example.com --dry-run
"""
import argparse
import json
import logging
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText

import psycopg2

from data.config import (
    DATABASE_DSN,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    EMAIL_TO,
)
from analysis.data_fetcher import is_trade_day

logger = logging.getLogger(__name__)


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


def fetch_latest_summary(cur):
    """获取最新一条 daily evaluation summary"""
    if not table_exists(cur, "watchlist_evaluation_summary"):
        return None
    cur.execute(
        "SELECT signal_date, as_of_date, total_signals, evaluated_1d, coverage_1d, "
        "evaluated_3d, coverage_3d, price_fetch_failed, "
        "avg_next_1d_return, win_rate_1d, avg_next_3d_return, win_rate_3d, "
        "confidence_level, conclusion_level, layer_inversion_warning, risk_warning, "
        "diagnostics_json, summary_json, generated_at "
        "FROM watchlist_evaluation_summary "
        "WHERE eval_mode = 'daily' "
        "ORDER BY generated_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip([
        "signal_date", "as_of_date", "total_signals", "evaluated_1d", "coverage_1d",
        "evaluated_3d", "coverage_3d", "price_fetch_failed",
        "avg_next_1d_return", "win_rate_1d", "avg_next_3d_return", "win_rate_3d",
        "confidence_level", "conclusion_level", "layer_inversion_warning", "risk_warning",
        "diagnostics_json", "summary_json", "generated_at",
    ], row))


def fetch_summary_by_date(cur, as_of_date):
    """按 as_of_date 查询 daily evaluation summary"""
    if not table_exists(cur, "watchlist_evaluation_summary"):
        return None
    cur.execute(
        "SELECT signal_date, as_of_date, total_signals, evaluated_1d, coverage_1d, "
        "evaluated_3d, coverage_3d, price_fetch_failed, "
        "avg_next_1d_return, win_rate_1d, avg_next_3d_return, win_rate_3d, "
        "confidence_level, conclusion_level, layer_inversion_warning, risk_warning, "
        "diagnostics_json, summary_json, generated_at "
        "FROM watchlist_evaluation_summary "
        "WHERE eval_mode = 'daily' AND as_of_date = %s "
        "ORDER BY generated_at DESC LIMIT 1",
        (as_of_date,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip([
        "signal_date", "as_of_date", "total_signals", "evaluated_1d", "coverage_1d",
        "evaluated_3d", "coverage_3d", "price_fetch_failed",
        "avg_next_1d_return", "win_rate_1d", "avg_next_3d_return", "win_rate_3d",
        "confidence_level", "conclusion_level", "layer_inversion_warning", "risk_warning",
        "diagnostics_json", "summary_json", "generated_at",
    ], row))


def parse_diagnostics(diagnostics_json, summary_json):
    """解析 diagnostics 和 summary JSON"""
    diag = {}
    if diagnostics_json:
        try:
            diag = json.loads(diagnostics_json) if isinstance(diagnostics_json, str) else diagnostics_json
        except (json.JSONDecodeError, TypeError):
            pass

    s = {}
    if summary_json:
        try:
            s = json.loads(summary_json) if isinstance(summary_json, str) else summary_json
        except (json.JSONDecodeError, TypeError):
            pass

    weak = []
    strong = []
    messages = []
    sd = diag.get("strategy_diagnostics", {})
    for entry in sd.get("underperforming_strategies", []):
        weak.append(entry["strategy"])
    for entry in sd.get("outperforming_strategies", []):
        strong.append(entry["strategy"])
    for msg in diag.get("diagnostic_messages", []):
        messages.append(msg)

    missing = s.get("missing_reasons", {})
    return diag, weak, strong, messages, missing


def _pct(val):
    if val is None:
        return "N/A"
    return f"{float(val) * 100:.1f}%"


def _yn(val):
    return "是" if val else "否"


def build_email_body(summary):
    """生成邮件正文"""
    s = summary
    diag, weak, strong, messages, missing = parse_diagnostics(
        s.get("diagnostics_json"), s.get("summary_json")
    )

    lines = [
        "# 观察池兑现与数据可信性检查",
        "",
        f"  检查日期: {s.get('as_of_date', 'N/A')}",
        f"  信号日期: {s.get('signal_date', 'N/A')}",
        f"  评价模式: daily",
        "",
        "## 1. T+1 评价摘要",
        "",
        f"  - 总信号数: {s.get('total_signals', 0)}",
        f"  - 1 日实际评价: {s.get('evaluated_1d', 0)}",
        f"  - 1 日覆盖率: {_pct(s.get('coverage_1d'))}",
        f"  - 平均次日收益: {_pct(s.get('avg_next_1d_return'))}",
        f"  - 次日胜率: {_pct(s.get('win_rate_1d'))}",
        f"  - 3 日实际评价: {s.get('evaluated_3d', 0)}",
        f"  - 3 日覆盖率: {_pct(s.get('coverage_3d'))}",
        "",
        "## 2. 数据质量",
        "",
        f"  - price_fetch_failed: {s.get('price_fetch_failed', 0)}",
        f"  - confidence_level: {s.get('confidence_level', 'N/A')}",
        f"  - conclusion_level: {s.get('conclusion_level', 'N/A')}",
    ]

    if missing:
        lines += ["", "  缺失原因:"]
        for reason, count in sorted(missing.items(), key=lambda x: -x[1]):
            lines.append(f"    {reason}: {count}")

    lines += [
        "",
        "## 3. 诊断结果",
        "",
        f"  - 分层倒挂: {'**是**' if s.get('layer_inversion_warning') else '否'}",
        f"  - 风险提示 warning: {'**是**' if s.get('risk_warning') else '否'}",
        f"  - 弱表现策略: {', '.join(weak) if weak else '(无)'}",
        f"  - 强表现策略: {', '.join(strong) if strong else '(无)'}",
    ]

    if messages:
        lines += [
            "",
            "  诊断消息:",
        ]
        for msg in messages:
            lines.append(f"    - {msg}")

    lines += [
        "",
        "## 4. 建议动作",
        "",
    ]
    cov1d = s.get("coverage_1d") or 0
    if cov1d < 0.8:
        lines.append("  - 行情覆盖不足，优先检查 stock_hist_kline 缓存。")
    if s.get("layer_inversion_warning"):
        lines.append("  - 继续观察分层倒挂，不建议单日调参。")
    if s.get("risk_warning"):
        lines.append("  - 后续进入风险分层复盘。")
    if not messages and cov1d >= 0.8:
        lines.append("  - 仅记录，无需操作。")

    lines += [
        "",
        "> 本邮件是 evaluation 自检邮件，不是日报邮件。",
        "> 本邮件不构成实盘买卖建议。",
    ]
    return "\n".join(lines)


def send_email(to, subject, body, dry_run=False):
    """发送邮件（或不发送，仅打印）"""
    if dry_run:
        print(f"\n{'='*60}")
        print(f"[DRY-RUN] 邮件将发送到: {to}")
        print(f"标题: {subject}")
        print(f"{'='*60}")
        print(body)
        print(f"{'='*60}")
        return

    if not SMTP_HOST or not SMTP_USER:
        print("[ERROR] SMTP 配置缺失，无法发送邮件")
        sys.exit(1)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [to], msg.as_string())
        server.quit()
        print(f"[OK] 邮件已发送至 {to}")
    except Exception as e:
        print(f"[ERROR] 邮件发送失败: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Evaluation 自检邮件发送")
    parser.add_argument("--latest", action="store_true", default=False, help="发送最新 daily evaluation")
    parser.add_argument("--date", type=str, default=None, help="按 as_of_date 查询 YYYYMMDD")
    parser.add_argument("--dry-run", action="store_true", default=False, help="仅打印，不发送")
    parser.add_argument("--to", type=str, default=None, help="覆盖收件人")
    args = parser.parse_args()

    if not args.latest and not args.date:
        print("[ERROR] 需要 --latest 或 --date YYYYMMDD")
        sys.exit(1)

    # ── 非交易日守卫 ──
    if args.date:
        if not is_trade_day(args.date):
            print(f"[SKIP] {args.date} 非交易日，不发送 evaluation 自检邮件")
            return

    # ── 数据库 ──
    if not DATABASE_DSN:
        print("[ERROR] DATABASE_DSN 未配置")
        sys.exit(1)

    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"[ERROR] 数据库连接失败: {e}")
        sys.exit(1)

    cur = conn.cursor()

    if args.latest:
        summary = fetch_latest_summary(cur)
    else:
        summary = fetch_summary_by_date(cur, args.date)

    cur.close()
    conn.close()

    if not summary:
        print("[SKIP] 未找到 evaluation summary 记录")
        return

    # ── 构建邮件 ──
    as_of = summary.get("as_of_date", "")
    subject = f"【A股日报系统自检】观察池兑现与数据可信性检查 - {as_of}"
    body = build_email_body(summary)
    to = args.to if args.to else EMAIL_TO

    if not to and not args.dry_run:
        print("[ERROR] 未指定收件人（EMAIL_TO 为空且未传 --to）")
        sys.exit(1)

    send_email(to or "user@example.com", subject, body, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
