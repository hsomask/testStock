"""
回归检查脚本
运行：python -m analysis.report_regression_check --date YYYYMMDD
检查日报系统的文件日期一致性、旧词、pipeline、权限过滤等
"""
import argparse
import json
import re
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily"

FROM_DISPLAY = {"20260528": "2026-05-28"}


def _ymd_to_display(date_str):
    s = str(date_str).replace("-", "").strip()[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _check_file_date(trade_date):
    """检查关键文件是否存在并带正确日期"""
    key_files = [
        "daily_report_{}.md",
        "daily_report_{}_pro.md",
        "daily_summary_{}.json",
        "trade_plan_{}.md",
        "trade_plan_{}.json",
        "board_trend_summary_{}.json",
        "board_mapping_quality_{}.json",
        "pipeline_check_{}.json",
    ]
    missing = []
    ok = []
    for pattern in key_files:
        fname = pattern.format(trade_date)
        if (REPORTS_DIR / fname).exists():
            ok.append(fname)
        else:
            missing.append(fname)

    if missing:
        return "failed", missing
    return "ok", []


def _check_old_terms(trade_date):
    """检查日报中是否出现旧词"""
    old_terms = ["市场情绪评分"]
    found = []
    for suffix in [".md", "_pro.md"]:
        text = _read_text(REPORTS_DIR / f"daily_report_{trade_date}{suffix}")
        for term in old_terms:
            if term in text:
                found.append(f"{suffix}: 发现旧词「{term}」")

    if found:
        return "failed", found
    return "ok", []


def _check_pipeline_critical(trade_date):
    """检查 pipeline_check JSON 是否有 critical_missing"""
    path = REPORTS_DIR / f"pipeline_check_{trade_date}.json"
    if not path.exists():
        return "failed", ["pipeline_check JSON 不存在"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cm = data.get("critical_missing", [])
        if isinstance(cm, bool):
            cm = data.get("missing_files", []) if cm else []
        if isinstance(cm, list) and cm:
            return "failed", cm
        return "ok", []
    except Exception as e:
        return "failed", [f"pipeline_check JSON 读取失败: {e}"]


def _check_board_mapping_date(trade_date):
    """检查 board_mapping_quality JSON actual_board_date"""
    path = REPORTS_DIR / f"board_mapping_quality_{trade_date}.json"
    if not path.exists():
        return "failed", ["board_mapping_quality JSON 不存在"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        actual = data.get("actual_board_date", "")
        expected = _ymd_to_display(trade_date)
        if actual == expected:
            return "ok", []
        if actual is None:
            return "failed", [f"actual_board_date 为 null (期望 {expected})"]
        return "failed", [f"actual_board_date={actual} (期望 {expected})"]
    except Exception as e:
        return "failed", [f"board_mapping_quality JSON 读取失败: {e}"]


def _check_trend_summary_missing(trade_date):
    """趋势摘要缺失时检查日报是否有提示"""
    trend_path = REPORTS_DIR / f"board_trend_summary_{trade_date}.json"
    if trend_path.exists():
        return "ok", []

    hints = ["趋势摘要", "未生成", "board_trend_summary", "暂缺"]
    found = False
    for suffix in [".md", "_pro.md"]:
        text = _read_text(REPORTS_DIR / f"daily_report_{trade_date}{suffix}")
        if any(h in text for h in hints):
            found = True
            break

    if not found:
        return "warning", ["board_trend_summary 缺失且日报无提示"]
    return "ok", []


def _check_duplicate_layer(trade_date):
    """检查日报中是否有 Ⅱ/Ⅲ 重复层级"""
    pairs = [("白酒Ⅱ", "白酒Ⅲ"), ("证券Ⅱ", "证券Ⅲ"), ("体育Ⅱ", "体育Ⅲ"),
             ("保险Ⅱ", "保险Ⅲ"), ("电子化学品Ⅱ", "电子化学品Ⅲ")]
    found = []
    for suffix in [".md", "_pro.md"]:
        text = _read_text(REPORTS_DIR / f"daily_report_{trade_date}{suffix}")
        for a, b in pairs:
            if a in text and b in text:
                found.append(f"{suffix}: {a} 和 {b} 同时出现")

    if found:
        return "warning", found
    return "ok", []


def _check_permission_filter(trade_date):
    """检查小白版可观察/谨慎池是否出现不可买市场"""
    import os
    allow_cyb = os.getenv("ALLOW_CHINEXT", "false").lower() == "true"
    allow_star = os.getenv("ALLOW_STAR", "false").lower() == "true"
    allow_bse = os.getenv("ALLOW_BSE", "false").lower() == "true"

    if allow_cyb and allow_star and allow_bse:
        return "ok", []

    forbidden = set()
    if not allow_cyb:
        forbidden.update(["300", "301"])
    if not allow_star:
        forbidden.add("688")
    if not allow_bse:
        forbidden.add("920")

    text = _read_text(REPORTS_DIR / f"daily_report_{trade_date}.md")

    # 找到可观察/谨慎池区域（分层标题之间）
    obs_start = text.find("### 可观察池")
    caution_start = text.find("### 谨慎观察池")
    high_risk_start = text.find("### 高风险复盘池")

    if obs_start == -1:
        return "ok", []

    # 只检查可观察+谨慎区域（在高风险之前）
    check_text = text[obs_start:high_risk_start] if high_risk_start > obs_start else text[obs_start:]

    found = []
    code_pattern = re.compile(r"\b(\d{6})\b")
    for m in code_pattern.finditer(check_text):
        code = m.group(1)
        for prefix in forbidden:
            if code.startswith(prefix):
                found.append(f"{code}: 不可买市场({prefix})")

    if found:
        return "failed", found[:10]
    return "ok", []


def _check_high_risk_duplicate(trade_date):
    """检查高风险票是否在可观察/谨慎池重复出现"""
    text = _read_text(REPORTS_DIR / f"daily_report_{trade_date}.md")

    obs_start = text.find("### 可观察池")
    high_risk_start = text.find("### 高风险复盘池")

    if obs_start == -1 or high_risk_start == -1:
        return "ok", []

    obs_text = text[obs_start:high_risk_start]
    high_text = text[high_risk_start:]

    code_pattern = re.compile(r"\b(\d{6})\b")
    obs_codes = set(m.group(1) for m in code_pattern.finditer(obs_text))
    high_codes = set(m.group(1) for m in code_pattern.finditer(high_text))

    dupes = obs_codes & high_codes
    if dupes:
        return "failed", [f"{c}: 同时出现在可观察和高风险池" for c in dupes]
    return "ok", []


def _check_summary_context(trade_date):
    """检查 daily_summary 中是否有 report_context"""
    path = REPORTS_DIR / f"daily_summary_{trade_date}.json"
    if not path.exists():
        return "warning", ["daily_summary JSON 不存在"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ctx = data.get("report_context") or {}
        missing = [k for k in ["market", "sentiment", "quality"] if not ctx.get(k)]
        if missing:
            return "warning", [f"report_context 缺少: {', '.join(missing)}"]
        return "ok", []
    except Exception as e:
        return "warning", [str(e)]


CHECK_FUNCTIONS = {
    "file_date": _check_file_date,
    "old_terms": _check_old_terms,
    "pipeline_critical": _check_pipeline_critical,
    "board_mapping_date": _check_board_mapping_date,
    "trend_summary_missing": _check_trend_summary_missing,
    "duplicate_layer": _check_duplicate_layer,
    "permission_filter": _check_permission_filter,
    "high_risk_duplicate": _check_high_risk_duplicate,
    "summary_context": _check_summary_context,
}


def run(trade_date):
    results = {}
    errors = []
    warnings = []

    for name, fn in CHECK_FUNCTIONS.items():
        status, details = fn(trade_date)
        results[name] = {"status": status, "details": details}
        if status == "failed":
            errors.append(name)
        elif status == "warning":
            warnings.append(name)

    overall = "failed" if errors else ("warning" if warnings else "ok")

    output = {
        "trade_date": trade_date,
        "status": overall,
        "errors": errors,
        "warnings": warnings,
        "checks": results,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"report_regression_check_{trade_date}.json"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    error_count = len(errors)
    warn_count = len(warnings)
    print(f"回归检查完成：{overall}（{error_count} errors / {warn_count} warnings）")
    print(f"JSON: {json_path}")


def main():
    parser = argparse.ArgumentParser(description="日报回归检查")
    parser.add_argument("--date", type=str, required=True, help="日期 YYYYMMDD")
    args = parser.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
