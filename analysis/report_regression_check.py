"""
日报内容回归检查：检查旧 bug 是否复发。
运行：python -m analysis.report_regression_check --date 20260609
"""
import argparse
import re
import sys
from pathlib import Path

from data.config import REPORT_DIR

NON_INDUSTRIAL_TERMS = [
    "沪股通", "深股通", "陆股通", "北向资金",
    "融资融券", "转融券",
    "MSCI中国", "富时罗素", "标普道琼斯",
    "基金重仓", "证金持股", "社保重仓",
    "百元股", "低价股", "高价股", "破净股",
    "上证380", "上证180", "上证50",
    "深证100R", "深成500",
    "沪深300", "中证500", "中证1000",
    "大盘股", "中盘股", "小盘股",
    "大盘价值", "东方财富热股",
    "昨日高振幅", "昨日涨停", "昨日连板",
]

SNAPSHOT_FORBIDDEN = [
    "次日胜率", "平均次日收益", "正式胜率", "正式平均收益",
]


def load_report(date_str):
    path = REPORT_DIR / "daily" / f"daily_report_{date_str}.md"
    if not path.exists():
        print(f"[ERROR] 日报不存在: {path}")
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def extract_section(text, start_marker, end_marker="---"):
    idx = text.find(start_marker)
    if idx < 0:
        return ""
    end = text.find(end_marker, idx + len(start_marker))
    if end < 0:
        end = len(text)
    return text[idx:end]


def check_a_non_industrial(text):
    """A: 非产业标签不得误入产业主线"""
    failures = []
    industrial_zones = []
    for marker in ["产业概念 3日流入", "产业概念 3日流出",
                   "有效主线 / 观察主线", "退潮方向",
                   "## 10. 机会观察"]:
        industrial_zones.append(extract_section(text, marker))
    combined = "\n".join(industrial_zones)

    for term in NON_INDUSTRIAL_TERMS:
        if term in combined:
            failures.append(f"非产业标签 '{term}' 出现在产业主线区域")
    return failures


def check_b_duplicated(text):
    """B: 观察池重复"""
    failures = []
    wl_start = text.find("## 11. 观察池")
    if wl_start < 0:
        return ["观察池模块不存在"]
    wl_end = text.find("## 12.", wl_start)
    if wl_end < 0:
        wl_end = len(text)
    wl_text = text[wl_start:wl_end]

    for marker in ["候选低吸", "只观察", "交易条件不满足", "高风险回避", "不可交易过滤"]:
        sec = extract_section(wl_text, marker, "\n### ")
        names = re.findall(r"^\|\s*([^\s|]+(?:\s*[^\s|]+)*?)\s*\|", sec, re.MULTILINE)
        stocks = [n for n in names if n not in ("股票", "------", "策略来源")]
        seen = set()
        for name in stocks:
            if name in seen:
                failures.append(f"观察池 {marker} 中 '{name}' 重复出现")
            seen.add(name)
    return failures


def check_c_excluded_exclusivity(text):
    """C: 不可交易过滤互斥"""
    failures = []
    # 先截取观察池区域
    wl_start = text.find("## 11. 观察池")
    wl_end = text.find("## 12.", wl_start) if wl_start >= 0 else -1
    if wl_start < 0:
        return []
    wl_text = text[wl_start:wl_end] if wl_end > 0 else text[wl_start:]

    excl_sec = extract_section(wl_text, "不可交易过滤", "\n### ")
    if not excl_sec:
        return []
    excl_names = set(re.findall(r"^\|\s*([^\s|]+(?:\s*[^\s|]+)*?)\s*\|", excl_sec, re.MULTILINE))
    excl_names.discard("股票")
    excl_names.discard("------")

    for marker in ["候选低吸", "只观察", "交易条件不满足", "高风险回避"]:
        sec = extract_section(wl_text, marker, "\n### ")
        sec_names = set(re.findall(r"^\|\s*([^\s|]+(?:\s*[^\s|]+)*?)\s*\|", sec, re.MULTILINE))
        sec_names.discard("股票")
        sec_names.discard("------")
        overlap = excl_names & sec_names
        for name in overlap:
            if name:
                failures.append(f"不可交易过滤中的 '{name}' 仍出现在 {marker}")
    return failures


def check_d_t1_exists(text):
    """D: T+1 模块存在"""
    t1_start = text.find("## 1. 昨日观察池兑现复盘（T+1）")
    if t1_start < 0:
        return ["T+1 模块不存在"]
    t1_end = text.find("## 2.", t1_start)
    if t1_end < 0:
        t1_end = len(text)
    t1_text = text[t1_start:t1_end]
    if len(t1_text.strip()) < 50:
        return ["T+1 模块为空"]
    return []


def check_e_snapshot_no_official_rate(text):
    """E: 快照复盘不展示正式胜率"""
    t1_sec = extract_section(text, "## 1. 昨日观察池兑现复盘（T+1）", "## 2.")
    if "快照复盘" not in t1_sec and "降级" not in t1_sec:
        return []
    failures = []
    for term in SNAPSHOT_FORBIDDEN:
        if term in t1_sec:
            failures.append(f"快照复盘展示了 '{term}'")
    return failures


def check_f_attachment_whitelist():
    """F: 邮件附件白名单"""
    email_path = Path(__file__).resolve().parent / "email_sender.py"
    if not email_path.exists():
        return ["email_sender.py 不存在"]
    content = email_path.read_text(encoding="utf-8")
    failures = []
    forbidden = ["trade_plan_", "daily_summary_", "board_trend_report_",
                 "board_alias_", "board_mapping_quality_", "pipeline_check_"]
    lines = content.split("\n")
    in_attach_block = False
    for line in lines:
        if "attachments" in line and ("=" in line or ".append" in line):
            in_attach_block = True
        if in_attach_block:
            for fw in forbidden:
                if fw in line and "attachments.append" in line:
                    failures.append(f"邮件附件中包含禁止项: {fw}")
    return failures


def main():
    parser = argparse.ArgumentParser(description="日报内容回归检查")
    parser.add_argument("--date", type=str, required=True, help="检查日期 YYYYMMDD")
    args = parser.parse_args()

    text = load_report(args.date)

    all_failures = []
    checks = [
        ("非产业标签误入产业主线", lambda: check_a_non_industrial(text)),
        ("观察池重复股票", lambda: check_b_duplicated(text)),
        ("不可交易过滤互斥", lambda: check_c_excluded_exclusivity(text)),
        ("T+1 模块存在且合法", lambda: check_d_t1_exists(text)),
        ("快照复盘不展示正式胜率", lambda: check_e_snapshot_no_official_rate(text)),
        ("邮件附件白名单", check_f_attachment_whitelist),
    ]

    for name, check_fn in checks:
        failures = check_fn()
        if failures:
            for f in failures:
                print(f"[FAIL] {f}")
                all_failures.append(f)
        else:
            print(f"[PASS] {name}")

    if all_failures:
        print(f"\nREGRESSION FAIL: {len(all_failures)} issues")
        sys.exit(1)
    else:
        print("\nREGRESSION PASS")


if __name__ == "__main__":
    main()
