"""
板块名称标准化模块
将东方财富/申万等层级名称统一到同花顺常用口径
"""
import re
from datetime import datetime

from analysis.board_alias_config import BOARD_ALIAS

# 自动规则：去除结尾罗马数字层级 Ⅱ/Ⅲ/II/III/Ⅳ/IV
_ROMAN_SUFFIX = re.compile(r"[ 　]*(Ⅱ|Ⅲ|Ⅳ|II|III|IV)$")
# 疑似重复但未合并的概念后缀
_CONCEPT_SUFFIX = re.compile(r"概念$")

KEY_BOARDS = [
    "半导体", "先进封装", "存储芯片", "国产芯片", "集成电路封测",
    "通信技术", "5G", "机器人", "液冷服务器", "算力",
    "贵金属", "黄金",
]


def explain_alias(raw_name):
    """返回 alias 解释"""
    if not raw_name:
        return {"raw_name": raw_name, "display_name": raw_name, "method": "empty"}

    if raw_name in BOARD_ALIAS:
        return {"raw_name": raw_name, "display_name": BOARD_ALIAS[raw_name], "method": "manual"}

    cleaned = _ROMAN_SUFFIX.sub("", str(raw_name).strip()).strip()
    if cleaned != raw_name:
        return {"raw_name": raw_name, "display_name": cleaned, "method": "roman_suffix"}

    return {"raw_name": raw_name, "display_name": raw_name, "method": "unchanged"}


def normalize_board_name(raw_name):
    """标准化板块名称"""
    return explain_alias(raw_name)["display_name"]


def build_alias_map(board_names):
    """批量建立 name → display_name 映射"""
    alias_map = {}
    for name in board_names:
        alias_map[name] = normalize_board_name(name)
    return alias_map


def generate_alias_report(df, trade_date):
    """生成板块名称归一报告"""
    import pandas as pd

    date_display = trade_date[:4] + "-" + trade_date[4:6] + "-" + trade_date[6:]
    lines = [f"# 板块名称归一报告 | {date_display}", ""]

    # 取最新一天数据
    latest = df[df["trade_date"] == df["trade_date"].max()] if "trade_date" in df.columns else df
    raw_names = sorted(latest["board_name"].dropna().unique())
    explained = [explain_alias(n) for n in raw_names]

    manual = [e for e in explained if e["method"] == "manual"]
    suffix = [e for e in explained if e["method"] == "roman_suffix"]
    unchanged = [e for e in explained if e["method"] == "unchanged"]
    display_names = set(e["display_name"] for e in explained)

    # 总体统计
    lines.append("## 一、总体统计")
    lines.append(f"- 原始板块数：{len(raw_names)}")
    lines.append(f"- 归一后板块数：{len(display_names)}")
    lines.append(f"- 合并减少：{len(raw_names) - len(display_names)}")
    lines.append(f"- 手工 alias：{len(manual)}")
    lines.append(f"- 自动去层级：{len(suffix)}")
    lines.append(f"- 未变化：{len(unchanged)}")
    lines.append("")

    # 手工 alias
    if manual:
        lines.append("## 二、手工 alias 生效列表")
        lines.append("| 原始名称 | 展示名称 |")
        lines.append("|---|---|")
        for e in manual:
            lines.append(f"| {e['raw_name']} | {e['display_name']} |")
        lines.append("")

    # 自动去层级
    if suffix:
        lines.append("## 三、自动去层级列表")
        lines.append("| 原始名称 | 展示名称 |")
        lines.append("|---|---|")
        for e in suffix:
            lines.append(f"| {e['raw_name']} | {e['display_name']} |")
        lines.append("")

    # 已合并板块
    merged = {}
    for e in explained:
        d = e["display_name"]
        if d not in merged:
            merged[d] = []
        merged[d].append(e["raw_name"])
    multi = {k: v for k, v in merged.items() if len(v) > 1}
    if multi:
        lines.append("## 四、发生合并的板块")
        lines.append("| 展示名称 | 原始名称列表 | 合并数量 |")
        lines.append("|---|---|---:|")
        for d, raws in sorted(multi.items(), key=lambda x: -len(x[1])):
            lines.append(f"| {d} | {'、'.join(raws)} | {len(raws)} |")
        lines.append("")

    # 疑似重复但未合并
    suspicious = _find_suspicious_duplicates(raw_names)
    if suspicious:
        lines.append("## 五、疑似重复但未合并")
        lines.append("| 板块A | 板块B | 原因 |")
        lines.append("|---|---|---|")
        for a, b, reason in suspicious:
            lines.append(f"| {a} | {b} | {reason} |")
        lines.append("")

    # 风险提示
    lines.append("## 六、风险提示")
    lines.append("- 如果某些概念被过度合并，需要从 BOARD_ALIAS 中移除；")
    lines.append("- 当前只是名称归一，不代表成分股完全等同于同花顺真实口径；")
    lines.append("- 半导体/半导体概念、国产芯片/存储芯片/先进封装 等概念不自动合并。")
    lines.append("")

    # 保存
    from pathlib import Path
    out_dir = Path(__file__).resolve().parents[1] / "reports" / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"board_alias_report_{trade_date}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Alias 报告已保存：{path}")


def _find_suspicious_duplicates(names):
    """识别疑似重复但未合并的板块"""
    suspicious = []
    for a in names:
        for b in names:
            if a >= b:
                continue
            # 概念后缀：A 和 A概念
            a_no_concept = _CONCEPT_SUFFIX.sub("", a).strip()
            b_no_concept = _CONCEPT_SUFFIX.sub("", b).strip()
            if a_no_concept == b_no_concept:
                suspicious.append((a, b, "概念后缀重复"))
                continue
            # 包含关系
            if a in b or b in a:
                suspicious.append((a, b, "名称包含"))
                continue
    return suspicious[:30]


def aggregate_by_display_name(df):
    """
    按 (trade_date, display_name) 聚合板块数据
    每天同名的 Ⅱ/Ⅲ 层级板块合并
    """
    import pandas as pd
    import numpy as np

    if df is None or df.empty:
        return df

    df = df.copy()
    if "trade_date" not in df.columns:
        return df

    df["display_name"] = df["board_name"].apply(normalize_board_name)

    # 不需要聚合
    if len(df) == len(df["display_name"].unique()):
        return df

    # 按 (trade_date, board_type, display_name) 分组聚合
    import numpy as np

    results = []
    for (td, bt, dname), group in df.groupby(["trade_date", "board_type", "display_name"], sort=False):
        row = {"trade_date": td, "board_type": bt, "board_name": dname}

        row["amount"] = group["amount"].sum() if "amount" in group.columns else None
        row["amount_ratio"] = group["amount_ratio"].sum() if "amount_ratio" in group.columns else None
        row["up_count"] = int(group["up_count"].sum()) if "up_count" in group.columns else 0
        row["down_count"] = int(group["down_count"].sum()) if "down_count" in group.columns else 0
        row["board_code"] = group["board_code"].iloc[0] if "board_code" in group.columns else ""

        # pct_chg 按 amount 加权平均
        if "pct_chg" in group.columns and "amount" in group.columns:
            v = group[group["amount"].notna() & group["pct_chg"].notna()]
            total_amt = v["amount"].sum()
            row["pct_chg"] = (v["pct_chg"] * v["amount"]).sum() / total_amt if total_amt > 0 else group["pct_chg"].mean()
        elif "pct_chg" in group.columns:
            row["pct_chg"] = group["pct_chg"].mean()

        # turnover 按 amount 加权
        if "turnover" in group.columns and "amount" in group.columns:
            v = group[group["amount"].notna() & group["turnover"].notna()]
            total_amt = v["amount"].sum()
            row["turnover"] = (v["turnover"] * v["amount"]).sum() / total_amt if total_amt > 0 else group["turnover"].mean()
        elif "turnover" in group.columns:
            row["turnover"] = group["turnover"].mean()

        # leader 取涨幅最大的
        if "leader_pct_chg" in group.columns:
            valid = group[group["leader_pct_chg"].notna()]
            if not valid.empty:
                best = valid.loc[valid["leader_pct_chg"].idxmax()]
                row["leader_name"] = best.get("leader_name", "")
                row["leader_pct_chg"] = best["leader_pct_chg"]
            else:
                row["leader_name"] = group["leader_name"].iloc[0] if "leader_name" in group.columns else ""
                row["leader_pct_chg"] = None

        results.append(row)

    return pd.DataFrame(results)
