"""
流程文件完整性检查
运行：python -m analysis.pipeline_check --date 20260528
"""
import argparse
import json
from pathlib import Path

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

    if critical_list:
        status = "critical"
    elif non_critical_list:
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
            *(f"非关键缺失: {f}" for f in non_critical_list)
        ] if w],
        "generated_at": f"{trade_date}",
    }
    json_path = REPORTS_DIR / f"pipeline_check_{trade_date}.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== {len(ok_files)} OK / {len(missing_files)} MISSING === (JSON: {json_path})")


if __name__ == "__main__":
    main()
