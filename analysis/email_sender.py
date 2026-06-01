"""
邮件推送模块
优先读取 daily_summary JSON，降级解析 Markdown，通过 SMTP 发送
"""
import json
import smtplib
import logging
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from data.config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    EMAIL_TO,
)

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily"


def find_latest_summary():
    """查找最新 daily_summary JSON"""
    files = sorted(REPORTS_DIR.glob("daily_summary_*.json"))
    if not files:
        return None
    return files[-1]


def find_latest_trade_plan():
    """查找最新 trade_plan JSON"""
    files = sorted(REPORTS_DIR.glob("trade_plan_*.json"))
    if not files:
        return None
    return files[-1]


def find_latest_file(pattern):
    """按 glob 模式查找最新文件"""
    files = sorted(REPORTS_DIR.glob(pattern))
    if not files:
        return None
    return files[-1]


def build_trade_plan_section(tp):
    """从 trade_plan JSON 组装邮件摘要"""
    r = tp.get("market_restrictions", {})
    s = tp.get("summary", {})
    parts = ["## 明日交易计划"]
    if not r.get("allow_real_trade", True):
        parts.append("**当前仅适合模拟观察，不建议实盘买入。**")
    parts.append(f"- 实盘：{'允许' if r.get('allow_real_trade') else '禁止'} | 仓位上限：{r.get('max_position_pct',0)}成")
    parts.append(f"- 候选低吸：{s.get('候选低吸',0)} | 只观察：{s.get('只观察',0)} | 条件不满足：{s.get('交易条件不满足',0)} | 高风险回避：{s.get('高风险回避',0)} | 过滤：{s.get('不可交易过滤',0)}")
    for reason in r.get("reasons", []):
        parts.append(f"  - {reason}")
    return "\n".join(parts)


def find_latest_report(pro=False):
    files = sorted(REPORTS_DIR.glob("daily_report_*.md"))

    if pro:
        files = [f for f in files if "_pro" in f.name]
    else:
        files = [f for f in files if "_pro" not in f.name]

    if not files:
        return None

    return files[-1]


def parse_report_sections(report_text):
    sections = {}
    current_title = None
    current_lines = []

    for line in report_text.split("\n"):
        if line.startswith("## "):
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_title is not None:
        sections[current_title] = "\n".join(current_lines).strip()

    return sections


def extract_date(report_text):
    for line in report_text.split("\n"):
        if "日期：" in line:
            return line.split("日期：")[-1].replace("**", "").strip()
    return ""


def build_email_body(sections, beginner_path=None, pro_path=None):
    parts = []

    def add_section(title, max_lines=20):
        content = sections.get(title, "")
        if not content:
            return
        lines = [l for l in content.split("\n") if l.strip()]
        parts.append(f"## {title}\n")
        parts.append("\n".join(lines[:max_lines]))
        parts.append("\n")

    add_section("今日市场一句话结论", 10)
    add_section("市场情绪", 15)
    add_section("今日主线判断", 25)
    add_section("今日风险方向", 15)
    add_section("今日观察池", 40)
    add_section("明日策略", 20)
    add_section("数据质量检查", 15)
    add_section("免责声明", 8)

    parts.append("\n---\n")
    if beginner_path:
        parts.append(f"小白版报告路径：{beginner_path}")
    if pro_path:
        parts.append(f"专业版报告路径：{pro_path}")

    return "\n\n".join(parts)


def attach_file(msg, file_path):
    if not file_path or not Path(file_path).exists():
        return

    path = Path(file_path)

    with open(path, "rb") as f:
        part = MIMEApplication(f.read(), Name=path.name)

    part["Content-Disposition"] = f'attachment; filename="{path.name}"'
    msg.attach(part)


def send_email(subject, body, attachments=None):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD or not EMAIL_TO:
        print("[邮件] SMTP 配置不完整，跳过邮件推送")
        return

    recipients = [x.strip() for x in EMAIL_TO.split(",") if x.strip()]
    if not recipients:
        print("[邮件] 收件人列表为空，跳过推送")
        return

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    for file_path in attachments or []:
        attach_file(msg, file_path)

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipients, msg.as_string())

        print("[邮件] 推送成功")

    except Exception as e:
        logger.exception(f"邮件推送失败：{e}")
        print(f"[邮件] 推送失败：{e}")


def build_email_body_from_json(summary, beginner_path=None, pro_path=None):
    """从 JSON 摘要组装邮件正文"""
    parts = []

    # 优先从 report_context 读取（兼容旧 summary）
    ctx = summary.get("report_context", {}) or {}
    m = ctx.get("market", {}) or summary.get("market", {})
    s = ctx.get("sentiment", {}) or summary.get("sentiment", {})

    if m:
        parts.append("## 今日市场一句话结论\n")
        parts.append(m.get("summary", ""))
        parts.append("\n")

    if s:
        parts.append("## 市场状态\n")
        parts.append(f"- 市场综合评分：{m.get('score', '-')} / 100，状态：{m.get('status', '-')}")
        parts.append(f"- 短线情绪周期评分：{s.get('score', '-')} / 100，阶段：{s.get('stage', '-')}")
        parts.append("\n")

    themes = summary.get("themes", [])
    if themes:
        parts.append("## 今日主线判断\n")
        for i, t in enumerate(themes):
            parts.append(f"**{i+1}. {t.get('name')}（{t.get('level')}，评分 {t.get('score')}）**")
            for r in t.get("reasons", [])[:3]:
                parts.append(f"  - {r}")
            parts.append("")
    else:
        parts.append("## 今日主线判断\n")
        parts.append("今日主线不明确\n")

    risk = summary.get("risk_directions", [])
    if risk:
        parts.append("## 今日风险方向\n")
        for r in risk:
            parts.append(f"- {r}")
        parts.append("")

    watchlists = summary.get("watchlists", {})
    if watchlists:
        parts.append("## 今日观察池精选\n")
        for pool_name, stocks in watchlists.items():
            if not stocks:
                continue
            parts.append(f"**{pool_name}**")
            for st in stocks:
                parts.append(f"- {st['name']}（{st['code']}）涨幅 {st.get('pct_chg','-')}% | 风险：{st.get('risk_level','-')} | 信号：{st.get('action_signal','-')}")
            parts.append("")

    q = summary.get("quality", {})
    if q:
        parts.append("## 数据质量\n")
        parts.append(f"可信度：{q.get('confidence_score')} / 100")
        for issue in q.get("issues", [])[:3]:
            parts.append(f"- {issue}")
        parts.append("")

    parts.append("\n---\n")
    parts.append("本报告仅用于数据复盘和学习，不构成任何投资建议。")
    parts.append("")

    if beginner_path:
        parts.append(f"小白版报告：{beginner_path}")
    if pro_path:
        parts.append(f"专业版报告：{pro_path}")

    return "\n".join(parts)


def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None, help="日期 YYYYMMDD")
    args = parser.parse_args()

    # 确定发送日期并检查交易日
    from analysis.utils import to_ymd
    from analysis.data_fetcher import get_trade_date, is_trade_day

    if args.date:
        date_str = to_ymd(args.date)
    else:
        date_str = get_trade_date()

    if not is_trade_day(date_str):
        print(f"[邮件] {date_str} 非交易日，跳过邮件推送")
        return

    if args.date:
        beginner_path = REPORTS_DIR / f"daily_report_{date_str}.md"
        pro_path = REPORTS_DIR / f"daily_report_{date_str}_pro.md"
        beginner_path = beginner_path if beginner_path.exists() else None
        pro_path = pro_path if pro_path.exists() else None
    else:
        beginner_path = find_latest_report(pro=False)
        pro_path = find_latest_report(pro=True)

    if args.date:
        summary_path = REPORTS_DIR / f"daily_summary_{date_str}.json"
        summary = summary_path if summary_path.exists() else None
        trade_plan_path = REPORTS_DIR / f"trade_plan_{date_str}.json"
        tp_path = trade_plan_path if trade_plan_path.exists() else None
    else:
        summary = find_latest_summary()
    date_display = "今日"
    subject = "A股每日复盘"

    if summary is not None:
        data = json.loads(summary.read_text(encoding="utf-8"))
        date_str = data.get("trade_date", "")

        # 格式化日期
        if len(date_str) == 8:
            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        subject = f"A股每日复盘 · {date_str}"
        body = build_email_body_from_json(data, beginner_path, pro_path)

        # 交易计划摘要（--date 模式只取当天，否则取最新）
        if args.date:
            tp_path = REPORTS_DIR / f"trade_plan_{date_str}.json"
            tp_path = tp_path if tp_path.exists() else None
        else:
            tp_path = find_latest_trade_plan()
        if tp_path:
            tp = json.loads(tp_path.read_text(encoding="utf-8"))
            tp_section = build_trade_plan_section(tp)
            body = tp_section + "\n\n---\n\n" + body

        print(f"[邮件] 使用 summary JSON：{summary}")
    elif beginner_path is not None:
        # 降级：解析 Markdown
        report_text = beginner_path.read_text(encoding="utf-8")
        sections = parse_report_sections(report_text)
        date_str = extract_date(report_text) or "今日"
        subject = f"A股每日复盘 · {date_str}"
        body = build_email_body(sections, beginner_path, pro_path)
        print(f"[邮件] JSON 不存在，降级解析 Markdown：{beginner_path}")
    else:
        print("[邮件] 未找到任何报告，跳过推送")
        return

    attachments = []
    if beginner_path:
        attachments.append(beginner_path)
    if pro_path:
        attachments.append(pro_path)

    # 附件：当天文件（按 trade_date 精确匹配，不混旧日期）
    date_str = date_str.replace("-", "") if len(date_str) > 8 else date_str
    missing_hint = []
    for fname in [f"board_trend_tracker_{date_str}.xlsx",
                  f"board_mapping_quality_{date_str}.md",
                  f"board_mapping_quality_{date_str}.json",
                  f"board_alias_report_{date_str}.md"]:
        fpath = REPORTS_DIR / fname
        if fpath.exists():
            attachments.append(fpath)
        else:
            missing_hint.append(fname)

    if missing_hint:
        body += "\n\n---\n以下当天文件未生成：\n"
        for f in missing_hint:
            body += f"- {f}\n"

    # 流程检查结果（读取同日期 pipeline_check JSON）
    pipeline_path = REPORTS_DIR / f"pipeline_check_{date_str}.json"
    if pipeline_path.exists():
        try:
            pc = json.loads(pipeline_path.read_text(encoding="utf-8"))
            cm = pc.get("critical_missing", [])
            nm = pc.get("non_critical_missing", [])
            # 兼容旧结构（critical_missing 为 bool）
            if isinstance(cm, bool):
                cm = pc.get("missing_files", []) if cm else []
                nm = []
            if isinstance(nm, bool):
                nm = []
            body += "\n\n---\n流程检查：\n"
            body += f"- 关键缺失：{'无' if not cm else '、'.join(cm)}\n"
            body += f"- 非关键缺失：{'无' if not nm else '、'.join(nm)}\n"
        except Exception:
            body += "\n\n---\n流程检查：pipeline_check JSON 读取失败\n"
    elif not args.date:
        pass  # 非 --date 模式不提示
    else:
        body += "\n\n---\n流程检查：pipeline_check JSON 未生成\n"

    send_email(subject, body, attachments)


if __name__ == "__main__":
    main()
