"""
流程文件完整性检查
运行：python -m analysis.pipeline_check --date 20260528
"""
import argparse
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily"

EXPECTED_FILES = [
    "daily_report_{}.md",
    "daily_report_{}_pro.md",
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, required=True, help="日期 YYYYMMDD")
    args = parser.parse_args()
    trade_date = args.date

    ok = 0
    missing = 0
    print(f"=== 流程文件检查（{trade_date}）===\n")

    for pattern in EXPECTED_FILES:
        fname = pattern.format(trade_date)
        path = REPORTS_DIR / fname
        if path.exists():
            print(f"  [OK] {fname}")
            ok += 1
        else:
            print(f"  [MISS] {fname}")
            missing += 1

    print(f"\n=== {ok} OK / {missing} MISSING ===")
    if missing > 0:
        print("\n以下文件未生成，请检查对应模块：")
        for pattern in EXPECTED_FILES:
            fname = pattern.format(trade_date)
            if not (REPORTS_DIR / fname).exists():
                print(f"  - {fname}")


if __name__ == "__main__":
    main()
