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
from analysis.utils import to_date_display, to_ymd
from analysis.board_alias import normalize_board_name, explain_alias, KEY_BOARDS
from analysis.board_alias_config import LOW_VALUE_BOARDS, KEY_BOARD_ALIASES

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
    date_display = to_date_display(trade_date)

    conn = _get_conn()
    if conn is None:
        return

    # 读取 stock_board_map
    map_df = pd.read_sql("SELECT code, name, board_type, board_name FROM stock_board_map", conn)
    if map_df.empty:
        print("[警告] stock_board_map 为空")
        conn.close()
        return

    # 读取指定日期 board_amount_ratio（不 fallback）
    requested_date = date_display
    ba_df = pd.read_sql(
        "SELECT * FROM board_amount_ratio WHERE trade_date=%s",
        conn, params=(date_display,)
    )
    actual_board_date = date_display if not ba_df.empty else None

    conn.close()

    map_df["display_name"] = map_df["board_name"].apply(normalize_board_name)

    lines = [f"# 板块映射质量报告 | {date_display}", ""]

    if actual_board_date != requested_date:
        lines.append(f"> 注意：指定日期无 board_amount_ratio 数据，已使用最近可用日期：{actual_board_date}。")
        lines.append("")

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

    # ── 四、已合并板块 ──
    lines.append("## 四、已合并板块")
    merged = {}
    for name in map_df["board_name"].dropna().unique():
        d = normalize_board_name(name)
        if d not in merged:
            merged[d] = []
        merged[d].append(str(name))
    multi = {k: v for k, v in merged.items() if len(v) > 1}
    if multi:
        lines.append("| 展示名称 | 原始名称列表 | 合并数量 |")
        lines.append("|---|---|---:|")
        for d, raws in sorted(multi.items(), key=lambda x: -len(x[1])):
            lines.append(f"| {d} | {'、'.join(raws)} | {len(raws)} |")
    else:
        lines.append("无合并板块")
    lines.append("")

    # ── 五、疑似重复但未合并 ──
    from analysis.board_alias import _find_suspicious_duplicates
    raw_names = sorted(map_df["board_name"].dropna().unique())
    suspicious = _find_suspicious_duplicates(raw_names)
    lines.append("## 五、疑似重复但未合并")
    if suspicious:
        lines.append("| 板块A | 板块B | 原因 |")
        lines.append("|---|---|---|")
        for a, b, reason in suspicious[:20]:
            lines.append(f"| {a} | {b} | {reason} |")
        lines.append(f"> 共发现 {len(suspicious)} 对疑似重复，建议人工审查后决定是否加入 BOARD_ALIAS。")
    else:
        lines.append("无疑似重复")
    lines.append("")

    # ── 六、重点板块映射核查 ──
    all_display = set(board_counts["display_name"].values)
    lines.append("## 六、重点板块映射核查")
    lines.append("| 板块 | 是否存在 | 匹配名称 | 成分股数 | 今日成交占比 |")
    lines.append("|---|---|---|---:|---:|")
    ba_latest = ba_df.dropna(subset=["amount_ratio"]) if not ba_df.empty else pd.DataFrame()
    for kb in KEY_BOARDS:
        aliases = KEY_BOARD_ALIASES.get(kb, [kb])
        matched = [a for a in aliases if a in all_display]
        if matched:
            mname = matched[0]
            cnt = int(board_counts[board_counts["display_name"] == mname]["count"].values[0])
            ar_row = ba_latest[ba_latest["board_name"] == mname] if not ba_latest.empty else pd.DataFrame()
            ar = f"{ar_row['amount_ratio'].values[0]*100:.2f}%" if len(ar_row) > 0 and pd.notna(ar_row['amount_ratio'].values[0]) else "-"
            lines.append(f"| {kb} | 是 | {mname} | {cnt} | {ar} |")
        else:
            lines.append(f"| {kb} | 否 | - | 0 | - |")
    lines.append("")

    # ── 七、低价值/宽泛标签板块 ──
    low_val = board_counts[board_counts["display_name"].isin(LOW_VALUE_BOARDS)]
    lines.append("## 七、低价值/宽泛标签板块")
    lines.append("| 板块 | 类型 | 成分股数 | 说明 |")
    lines.append("|---|---|---:|---|")
    for _, r in low_val.iterrows():
        desc = "宽泛概念" if "概念" in r["display_name"] or "指数" in r["display_name"] else "动态标签"
        lines.append(f"| {r['display_name']} | {r['board_type']} | {r['count']} | {desc} |")
    if low_val.empty:
        lines.append("| - | - | - | 无 |")
    lines.append(f"> 共 {len(low_val)} 个，这些板块保留但不作为主线摘要优先项。")
    lines.append("")

    # ── JSON 输出 ──
    key_check = {}
    key_matched = {}
    for kb in KEY_BOARDS:
        aliases = KEY_BOARD_ALIASES.get(kb, [kb])
        matched = [a for a in aliases if a in all_display]
        key_check[kb] = bool(matched)
        key_matched[kb] = matched

    quality_json = {
        "trade_date": trade_date,
        "requested_date": requested_date,
        "actual_board_date": actual_board_date,
        "industry_raw": int(map_df[map_df["board_type"] == "行业"]["board_name"].nunique()),
        "industry_norm": int(map_df[map_df["board_type"] == "行业"]["display_name"].nunique()),
        "concept_raw": int(map_df[map_df["board_type"] == "概念"]["board_name"].nunique()),
        "concept_norm": int(map_df[map_df["board_type"] == "概念"]["display_name"].nunique()),
        "total_mapping": len(map_df),
        "too_few_boards": len(too_few),
        "too_many_boards": len(too_many),
        "over_mapped_stocks": len(over_mapped),
        "key_boards_check": key_check,
        "key_boards_matched": key_matched,
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
