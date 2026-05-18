"""
邮件推送模块
读取最新生成的日报，通过 SMTP 发送到指定邮箱
"""
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

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    for file_path in attachments or []:
        attach_file(msg, file_path)

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())

        print("[邮件] 推送成功")

    except Exception as e:
        logger.exception(f"邮件推送失败：{e}")
        print(f"[邮件] 推送失败：{e}")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    beginner_path = find_latest_report(pro=False)
    pro_path = find_latest_report(pro=True)

    if not beginner_path:
        print("[邮件] 未找到小白版报告，跳过推送")
        return

    report_text = beginner_path.read_text(encoding="utf-8")
    sections = parse_report_sections(report_text)
    date_str = extract_date(report_text) or "今日"

    subject = f"A股每日复盘 · {date_str}"
    body = build_email_body(sections, beginner_path, pro_path)

    attachments = [beginner_path]
    if pro_path:
        attachments.append(pro_path)

    send_email(subject, body, attachments)


if __name__ == "__main__":
    main()
