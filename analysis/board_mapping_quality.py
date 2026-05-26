"""
板块映射质量校验
运行：python -m analysis.board_mapping_quality [--date YYYYMMDD]
"""
import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

from data.config import DATABASE_DSN
from analysis.board_alias import normalize_board_name, explain_alias, KEY_BOARDS

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily"


def _get_conn():
    if not DATABASE_DSN:
        return None
    try:
        return psycopg2.connect(DATABASE_DSN)
    except Exception as e:
        print(f"[错误] 数据库连接失败：{e}")
        return None


def _count_dist(df, col):
    """安全计数组/和"""
    return df.groupby(col).size().to_dict() if not df.empty else {}


def run(trade_date=None):
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y%m%d")
    date_display = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

    conn = _get_conn()
    if conn is None:
        return

    # 读取 stock_board_map
    map_df = pd.read_sql("SELECT code, name, board_type, board_name FROM stock_board_map", conn)
    if map_df.empty:
        print("[警告] stock_board_map 为空")
        conn.close()
        return

    # 读取最新 board_amount_ratio
    ba_df = pd.read_sql(
        "SELECT * FROM board_amount_ratio WHERE trade_date=%s",
        conn, params=(date_display,)
    )
    if ba_df.empty:
        ba_df = pd.read_sql(
            "SELECT * FROM board_amount_ratio WHERE trade_date=(SELECT MAX(trade_date) FROM board_amount_ratio)",
            conn
        )

    conn.close()

    map_df["display_name"] = map_df["board_name"].apply(normalize_board_name)

    lines = [f"# 板块映射质量报告 | {date_display}", ""]

    # ── 一、基本统计 ──
    lines.append("## 一、基本统计")
    for bt in ["行业", "概念"]:
        sub = map_df[map_df["board_type"] == bt]
        raw = sub["board_name"].nunique()
        norm = sub["display_name"].nunique()
        stocks = sub["code"].nunique()
        lines.append(f"- {bt}：原始 {raw} 个 → 归一 {norm} 个，覆盖 {stocks} 只股票（{len(sub)} 条映射）")
    lines.append("")

    # ── 二、成分股异常 ──
    lines.append("## 二、成分股异常板块")
    board_counts = map_df.groupby(["board_type", "display_name"]).size().reset_index(name="count")

    too_few = board_counts[board_counts["count"] <= 2]
    too_many = board_counts[board_counts["count"] >= 300]

    if not too_few.empty:
        lines.append("### 成分股过少（≤2只）")
        lines.append("| 板块 | 类型 | 成分股数 |")
        lines.append("|---|---|---:|")
        for _, r in too_few.head(20).iterrows():
            lines.append(f"| {r['display_name']} | {r['board_type']} | {r['count']} |")
        lines.append(f"> 共 {len(too_few)} 个，可能是细分板块或映射不完整。")
        lines.append("")

    if not too_many.empty:
        lines.append("### 成分股过多（≥300只）")
        lines.append("| 板块 | 类型 | 成分股数 |")
        lines.append("|---|---|---:|")
        for _, r in too_many.head(20).iterrows():
            lines.append(f"| {r['display_name']} | {r['board_type']} | {r['count']} |")
        lines.append(f"> 共 {len(too_many)} 个，可能是宽基概念或映射过泛。")
        lines.append("")

    # ── 三、映射过多个股 ──
    lines.append("## 三、映射过多个股 TOP20")
    code_counts = map_df.groupby(["code", "name"]).size().reset_index(name="board_count")
    over_mapped = code_counts[code_counts["board_count"] >= 30].sort_values("board_count", ascending=False)
    if not over_mapped.empty:
        lines.append("| 股票 | 代码 | 映射板块数 |")
        lines.append("|---|---|---:|")
        for _, r in over_mapped.head(20).iterrows():
            lines.append(f"| {r['name']} | {r['code']} | {r['board_count']} |")
    else:
        lines.append("无映射过多个股")
    lines.append("")

    # ── 四、重点板块核查 ──
    lines.append("## 四、重点板块映射核查")
    lines.append("| 板块 | 是否存在 | 成分股数 | 今日成交占比 |")
    lines.append("|---|---|---:|---:|")
    ba_latest = ba_df.dropna(subset=["amount_ratio"]) if not ba_df.empty else pd.DataFrame()
    for kb in KEY_BOARDS:
        exists = kb in board_counts["display_name"].values
        cnt = int(board_counts[board_counts["display_name"] == kb]["count"].values[0]) if exists else 0
        ar_row = ba_latest[ba_latest["board_name"] == kb] if not ba_latest.empty else pd.DataFrame()
        ar = f"{ar_row['amount_ratio'].values[0]*100:.2f}%" if len(ar_row) > 0 and pd.notna(ar_row['amount_ratio'].values[0]) else "-"
        lines.append(f"| {kb} | {'是' if exists else '否'} | {cnt} | {ar} |")
    lines.append("")

    # ── JSON 输出 ──
    quality_json = {
        "trade_date": trade_date,
        "industry_raw": int(map_df[map_df["board_type"] == "行业"]["board_name"].nunique()),
        "industry_norm": int(map_df[map_df["board_type"] == "行业"]["display_name"].nunique()),
        "concept_raw": int(map_df[map_df["board_type"] == "概念"]["board_name"].nunique()),
        "concept_norm": int(map_df[map_df["board_type"] == "概念"]["display_name"].nunique()),
        "total_mapping": len(map_df),
        "too_few_boards": len(too_few),
        "too_many_boards": len(too_many),
        "over_mapped_stocks": len(over_mapped),
        "key_boards_check": {kb: kb in board_counts["display_name"].values for kb in KEY_BOARDS},
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / f"board_mapping_quality_{trade_date}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"映射质量报告已保存：{md_path}")

    json_path = REPORTS_DIR / f"board_mapping_quality_{trade_date}.json"
    json_path.write_text(json.dumps(quality_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"映射质量 JSON 已保存：{json_path}")

    # 同步生成 alias 报告
    if not ba_df.empty:
        from analysis.board_alias import generate_alias_report
        generate_alias_report(ba_df, trade_date)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None, help="日期 YYYYMMDD")
    args = parser.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
