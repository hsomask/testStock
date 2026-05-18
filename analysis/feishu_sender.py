"""
飞书推送模块
读取最新生成的报告，组装飞书交互卡片并推送
"""
import json
import time
import hmac
import hashlib
import base64
import logging
from pathlib import Path

import requests

from data.config import FEISHU_WEBHOOK, FEISHU_SECRET

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily"


def find_latest_report():
    """找到最新的 beginner 报告"""
    files = sorted(REPORTS_DIR.glob("daily_report_*.md"))
    # 排除 pro 版
    files = [f for f in files if "_pro" not in f.name]
    if not files:
        return None
    return files[-1]


def parse_report_sections(report_text):
    """解析报告，按 ## 标题拆分为 section"""
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


def extract_date_from_report(report_text):
    """从报告第一段提取日期"""
    for line in report_text.split("\n"):
        if "日期：" in line:
            return line.split("日期：")[-1].replace("**", "").strip()
    return ""


def build_card(sections):
    """组装飞书交互卡片"""
    date_str = extract_date_from_report(
        "\n".join(sections.get(k, "") for k in sections)
    ) or "—"

    header = {
        "title": {"tag": "plain_text", "content": f"A股每日复盘 · 小白友好版 | {date_str}"},
        "template": "blue",
    }

    elements = []

    # 1. 今日市场一句话结论
    one_line = sections.get("今日市场一句话结论", "")
    if one_line:
        elements.append({"tag": "markdown", "content": f"**今日市场一句话结论**\n\n{one_line.strip()}"})
        elements.append({"tag": "hr"})

    # 2. 市场情绪
    sentiment = sections.get("市场情绪", "")
    if sentiment:
        # 提取关键行
        lines = [l for l in sentiment.split("\n") if l.strip() and not l.strip().startswith("#")]
        elements.append({"tag": "markdown", "content": "**市场情绪**\n\n" + "\n".join(lines[:15])})
        elements.append({"tag": "hr"})

    # 3. 今日主线判断
    themes = sections.get("今日主线判断", "")
    if themes:
        lines = [l for l in themes.split("\n") if l.strip()]
        content = "\n".join(lines[:20])
        elements.append({"tag": "markdown", "content": "**今日主线判断**\n\n" + content})
        elements.append({"tag": "hr"})

    # 4. 今日风险方向
    risk = sections.get("今日风险方向", "")
    if risk:
        lines = [l for l in risk.split("\n") if l.strip() and not l.strip().startswith("#")]
        elements.append({"tag": "markdown", "content": "**今日风险方向**\n\n" + "\n".join(lines[:10])})
        elements.append({"tag": "hr"})

    # 5. 今日观察池（每个池 Top 2）
    obs = sections.get("今日观察池", "")
    if obs:
        pool_parts = []
        current_pool = None
        stock_count = 0
        for line in obs.split("\n"):
            stripped = line.strip()
            if stripped.startswith("### "):
                current_pool = stripped[4:]
                stock_count = 0
                pool_parts.append(f"\n**{current_pool}**")
            elif stripped.startswith("**") and stock_count < 2 and current_pool:
                stock_count += 1
                # 提取股票名、代码和关键信息
                pool_parts.append(stripped)
                # 继续收集后续行直到空行
        if pool_parts:
            elements.append({"tag": "markdown", "content": "**今日观察池精选**\n" + "\n".join(pool_parts[:40])})
            elements.append({"tag": "hr"})

    # 6. 明日策略
    strategy = sections.get("明日策略", "")
    if strategy:
        lines = [l for l in strategy.split("\n") if l.strip()]
        elements.append({"tag": "markdown", "content": "**明日策略**\n\n" + "\n".join(lines[:15])})
        elements.append({"tag": "hr"})

    # 7. 数据质量
    quality = sections.get("数据质量检查", "")
    if quality:
        lines = [l for l in quality.split("\n") if l.strip() and not l.strip().startswith("#")]
        elements.append({"tag": "markdown", "content": "**数据质量**\n\n" + "\n".join(lines[:10])})
        elements.append({"tag": "hr"})

    # 8. 免责声明
    disclaimer = sections.get("免责声明", "")
    if disclaimer:
        disc_lines = [l for l in disclaimer.split("\n") if l.strip() and not l.strip().startswith("#")]
        elements.append({"tag": "markdown", "content": "\n".join(disc_lines[:5])})

    # 截断超长卡片（飞书卡片总共约 30KB 限制）
    if len(elements) > 30:
        elements = elements[:30]

    card = {
        "msg_type": "interactive",
        "card": {
            "header": header,
            "elements": elements,
        },
    }

    return card


def send_feishu(card):
    """发送飞书消息"""
    if not FEISHU_WEBHOOK:
        print("[飞书] FEISHU_WEBHOOK 未设置，跳过推送")
        return

    url = FEISHU_WEBHOOK.strip()

    body = {
        "timestamp": str(int(time.time())),
        "msg_type": "interactive",
        "card": card["card"],
    }

    # 签名校验（如果配置了 FEISHU_SECRET）
    if FEISHU_SECRET:
        secret = FEISHU_SECRET.strip()
        sign = _gen_sign(body["timestamp"], secret)
        body["sign"] = sign

    try:
        resp = requests.post(url, json=body, timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            print("[飞书] 消息推送成功")
        else:
            print(f"[飞书] 推送失败，status_code={resp.status_code}，response={resp.text}")
    except Exception as e:
        print(f"[飞书] 推送异常：{e}")


def _gen_sign(timestamp, secret):
    """生成飞书签名"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    sign = base64.b64encode(hmac_code.digest()).decode("utf-8")
    return sign


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    report_path = find_latest_report()
    if not report_path:
        print("[飞书] 未找到最新报告文件，跳过推送")
        return

    print(f"[飞书] 读取报告：{report_path}")
    report_text = report_path.read_text(encoding="utf-8")

    sections = parse_report_sections(report_text)

    card = build_card(sections)

    send_feishu(card)


if __name__ == "__main__":
    main()
