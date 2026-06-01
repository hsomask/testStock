"""
观察池有效性评估（唯一评价入口）
  # range 模式（默认）
  python -m analysis.watchlist_evaluation --start 20260501 --end 20260531
  python -m analysis.watchlist_evaluation --mode range --days 30
  python -m analysis.watchlist_evaluation --start 20260501 --end 20260531 --as-of 20260603

  # daily 模式
  python -m analysis.watchlist_evaluation --mode daily --signal-date 20260528 --as-of 20260529
"""
import argparse
import json
import logging
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

from data.config import DATABASE_DSN, REPORT_DIR
from analysis.data_fetcher import get_stock_history

logger = logging.getLogger(__name__)

LAYER_FALLBACK_FIELDS = ["watchlist_layer", "action_signal", "signal_type"]

REASON_LABELS = {
    "not_mature_1d": "入选时间太近，尚无 1 个后续交易日",
    "not_mature_3d": "入选时间太近，尚无 3 个后续交易日",
    "insufficient_future_days_for_3d": "有部分后续数据但不足 3 个交易日",
    "price_fetch_failed": "历史行情获取失败",
    "missing_entry_close": "入选日收盘价缺失",
    "invalid_code": "股票代码无效",
    "invalid_close_price": "入选日收盘价异常",
    "entry_date_not_found": "行情数据中找不到入选日期",
}


def get_db_conn():
    if not DATABASE_DSN:
        return None
    return psycopg2.connect(DATABASE_DSN)


def table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return cur.fetchone()[0]


def resolve_layer(signal):
    for field in LAYER_FALLBACK_FIELDS:
        val = signal.get(field)
        if val and str(val).strip():
            return str(val).strip()
    return "unknown"


def build_signal_key(signal):
    """统一 signal_key：优先 id，否则 trade_date+code+strategy"""
    sid = signal.get("id")
    if sid is not None:
        return str(sid)
    code = str(signal.get("code", "")).strip()
    td = signal.get("trade_date", "")
    strategy = str(signal.get("strategy", "")).strip()
    return f"{td}_{code}_{strategy}"


def fetch_signals(conn, start_date, end_date):
    """range 模式：读取区间内所有 stock_signal"""
    cur = conn.cursor()
    if not table_exists(cur, "stock_signal"):
        print("[ERROR] stock_signal 表不存在")
        cur.close()
        return []

    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'stock_signal' ORDER BY ordinal_position"
    )
    existing_cols = {row[0] for row in cur.fetchall()}

    desired = [
        "id", "trade_date", "code", "name", "strategy", "risk_level",
        "action_signal", "signal_type", "watchlist_layer", "close_price",
    ]
    select_cols = [c for c in desired if c in existing_cols]

    sql_start = start_date[:4] + "-" + start_date[4:6] + "-" + start_date[6:8]
    sql_end = end_date[:4] + "-" + end_date[4:6] + "-" + end_date[6:8]

    col_str = ", ".join(f'"{c}"' for c in select_cols)
    cur.execute(
        f"SELECT {col_str} FROM stock_signal WHERE trade_date >= %s AND trade_date <= %s ORDER BY trade_date, code",
        (sql_start, sql_end),
    )

    rows = cur.fetchall()
    signals = []
    for row in rows:
        d = dict(zip(select_cols, row))
        td = d.get("trade_date")
        if hasattr(td, "strftime"):
            d["trade_date"] = td.strftime("%Y%m%d")
        else:
            d["trade_date"] = str(td).replace("-", "")[:8]
        signals.append(d)

    cur.close()
    return signals


def fetch_signals_for_date(conn, signal_date):
    """daily 模式：仅读取指定日期的 stock_signal"""
    cur = conn.cursor()
    if not table_exists(cur, "stock_signal"):
        print("[ERROR] stock_signal 表不存在")
        cur.close()
        return []

    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'stock_signal' ORDER BY ordinal_position"
    )
    existing_cols = {row[0] for row in cur.fetchall()}

    desired = [
        "id", "trade_date", "code", "name", "strategy", "risk_level",
        "action_signal", "signal_type", "watchlist_layer", "close_price",
    ]
    select_cols = [c for c in desired if c in existing_cols]

    sql_date = signal_date[:4] + "-" + signal_date[4:6] + "-" + signal_date[6:8]
    col_str = ", ".join(f'"{c}"' for c in select_cols)
    cur.execute(
        f"SELECT {col_str} FROM stock_signal WHERE trade_date = %s ORDER BY code",
        (sql_date,),
    )

    rows = cur.fetchall()
    signals = []
    for row in rows:
        d = dict(zip(select_cols, row))
        td = d.get("trade_date")
        if hasattr(td, "strftime"):
            d["trade_date"] = td.strftime("%Y%m%d")
        else:
            d["trade_date"] = str(td).replace("-", "")[:8]
        signals.append(d)

    cur.close()
    return signals


def compute_verification_tag(next_1d_return, max_3d_drawdown, layer):
    """根据次日表现和分层判断信号验证标签"""
    if next_1d_return is None:
        return "insufficient"

    r1 = next_1d_return
    dd3 = max_3d_drawdown

    if layer in ("观察",):
        if r1 > 0:
            tag = "hit"
        elif dd3 is not None and dd3 < -0.04:
            tag = "hit"
        else:
            tag = "miss"
    elif layer in ("谨慎", "谨慎观望"):
        if abs(r1) <= 0.03 and (dd3 is None or dd3 >= -0.04):
            tag = "neutral"
        elif r1 > 0.03:
            tag = "miss"
        else:
            tag = "hit"
    elif layer in ("回避", "高", "高风险"):
        if r1 < 0 or (dd3 is not None and dd3 < -0.03):
            tag = "hit"
        elif r1 > 0.03 and (dd3 is None or dd3 >= -0.03):
            tag = "miss"
        else:
            tag = "neutral"
    else:
        if r1 > 0:
            tag = "hit"
        elif r1 < 0:
            tag = "miss"
        else:
            tag = "neutral"
    return tag


def evaluate_signal_performance(signal):
    """
    统一单条信号评价函数（range 和 daily 共用）。
    返回 (metrics_dict, status_dict)

    先用 days=80 走 DB 缓存快速路径；如果缓存无后续交易日数据，
    再用 days=500 触发 API 刷新（绕过 get_stock_history 的
    len(db_dates) >= days-3 缓存命中条件）。
    """
    code = str(signal.get("code", "")).strip()
    trade_date = signal["trade_date"]
    close_price_raw = signal.get("close_price")

    status = {
        "eligible_1d": False,
        "eligible_3d": False,
        "evaluated_1d": False,
        "evaluated_3d": False,
        "missing_reasons": [],
        "price_dates": [],
        "entry_close_found": False,
        "as_of_close_found": False,
    }

    if not code:
        status["missing_reasons"].append("invalid_code")
        return None, status

    try:
        close_price = float(close_price_raw)
    except (TypeError, ValueError):
        status["missing_reasons"].append("missing_entry_close")
        return None, status

    if pd.isna(close_price) or close_price <= 0:
        status["missing_reasons"].append("invalid_close_price")
        return None, status

    try:
        hist = get_stock_history(code, days=80)
    except Exception:
        status["missing_reasons"].append("price_fetch_failed")
        return None, status

    if hist is None or hist.empty or "date" not in hist.columns:
        status["missing_reasons"].append("price_fetch_failed")
        return None, status

    all_dates = hist["date"].astype(str).str.replace("-", "").str[:8]
    status["price_dates"] = sorted(all_dates.unique().tolist())

    if trade_date in set(all_dates):
        status["entry_close_found"] = True

    future_mask = all_dates > trade_date
    future = hist[future_mask].sort_values("date")

    # 如果缓存无后续数据，可能缓存过期，尝试强制 API 刷新一次
    if future.empty:
        try:
            hist = get_stock_history(code, days=500)
            if hist is not None and not hist.empty and "date" in hist.columns:
                all_dates = hist["date"].astype(str).str.replace("-", "").str[:8]
                status["price_dates"] = sorted(all_dates.unique().tolist())
                if trade_date in set(all_dates):
                    status["entry_close_found"] = True
                future_mask = all_dates > trade_date
                future = hist[future_mask].sort_values("date")
        except Exception:
            pass

    if status["price_dates"]:
        status["as_of_close_found"] = True

    future_len = len(future)

    if future_len >= 1:
        status["eligible_1d"] = True
    else:
        if status["entry_close_found"]:
            status["missing_reasons"].append("not_mature_1d")
        else:
            status["missing_reasons"].append("entry_date_not_found")

    if future_len >= 3:
        status["eligible_3d"] = True
    else:
        if future_len >= 1:
            status["missing_reasons"].append("insufficient_future_days_for_3d")
        elif status["entry_close_found"]:
            status["missing_reasons"].append("not_mature_3d")

    if future.empty:
        return None, status

    # 1d
    row_1d = future.iloc[0]
    next_1d_return = None
    try:
        next_1d_return = float(row_1d["close"]) / close_price - 1
        status["evaluated_1d"] = True
    except (TypeError, ValueError):
        pass

    # 3d
    next_3d_return = None
    max_3d_return = None
    max_3d_drawdown = None
    if future_len >= 3:
        window = future.iloc[:3]
        try:
            next_3d_return = float(window.iloc[2]["close"]) / close_price - 1
            status["evaluated_3d"] = True
        except (TypeError, ValueError):
            pass
        try:
            max_high = max(float(x) for x in window["high"] if not pd.isna(x))
            max_3d_return = max_high / close_price - 1
        except (ValueError, TypeError):
            pass
        try:
            min_low = min(float(x) for x in window["low"] if not pd.isna(x))
            max_3d_drawdown = min_low / close_price - 1
        except (ValueError, TypeError):
            pass

    metrics = {
        "entry_close": close_price,
        "next_1d_return": next_1d_return,
        "next_3d_return": next_3d_return,
        "max_3d_return": max_3d_return,
        "max_3d_drawdown": max_3d_drawdown,
    }
    return metrics, status


def safe_mean(values):
    vals = [v for v in values if v is not None and not pd.isna(v)]
    if not vals:
        return None
    return float(np.mean(vals))


def safe_win_rate(values):
    vals = [v for v in values if v is not None and not pd.isna(v)]
    if not vals:
        return None
    return float(sum(1 for v in vals if v > 0) / len(vals))


def aggregate_metrics(records, group_key=None):
    """统一聚合函数（range 和 daily 共用）"""
    if group_key is None:
        groups = {"__all__": records}
    else:
        groups = defaultdict(list)
        for r in records:
            k = str(r.get(group_key, "unknown")).strip() or "unknown"
            groups[k].append(r)

    result = {}
    for group_name, group_records in sorted(groups.items()):
        vals_1d = [r["metrics"]["next_1d_return"] for r in group_records
                   if r.get("metrics") and r["metrics"].get("next_1d_return") is not None]
        vals_3d = [r["metrics"]["next_3d_return"] for r in group_records
                   if r.get("metrics") and r["metrics"].get("next_3d_return") is not None]
        vals_max3d = [r["metrics"]["max_3d_return"] for r in group_records
                      if r.get("metrics") and r["metrics"].get("max_3d_return") is not None]
        vals_dd3d = [r["metrics"]["max_3d_drawdown"] for r in group_records
                     if r.get("metrics") and r["metrics"].get("max_3d_drawdown") is not None]

        metrics = {
            "count": len(group_records),
            "evaluated_1d_count": len(vals_1d),
            "evaluated_3d_count": len(vals_3d),
            "missing_count": sum(1 for r in group_records if r.get("status", {}).get("missing_reasons")),
            "avg_next_1d_return": safe_mean(vals_1d),
            "win_rate_1d": safe_win_rate(vals_1d),
            "avg_next_3d_return": safe_mean(vals_3d),
            "win_rate_3d": safe_win_rate(vals_3d),
            "avg_max_3d_return": safe_mean(vals_max3d),
            "avg_max_3d_drawdown": safe_mean(vals_dd3d),
        }
        result[group_name] = metrics

    return result


def _build_table_rows(group_data, include_3d=True):
    """构建分组 Markdown 表格行"""
    header = ["分组", "总数", "有效1d"]
    if include_3d:
        header += ["有效3d"]
    header += ["次日收益", "次日胜率"]
    if include_3d:
        header += ["3日收益", "3日胜率", "3日最高涨幅", "3日下行幅度"]
    sep = "|" + "|".join("------" for _ in header) + "|"

    rows = [sep]
    for gname, m in group_data.items():
        cols = [
            str(gname), str(m["count"]), str(m["evaluated_1d_count"]),
        ]
        if include_3d:
            cols.append(str(m["evaluated_3d_count"]))
        cols += [
            _fmt_pct(m.get("avg_next_1d_return")), _fmt_pct(m.get("win_rate_1d")),
        ]
        if include_3d:
            cols += [
                _fmt_pct(m.get("avg_next_3d_return")), _fmt_pct(m.get("win_rate_3d")),
                _fmt_pct(m.get("avg_max_3d_return")), _fmt_pct(m.get("avg_max_3d_drawdown")),
            ]
        rows.append("| " + " | ".join(cols) + " |")

    return "| " + " | ".join(header) + " |\n" + "\n".join(rows)


def build_range_markdown(result):
    """range 模式 Markdown"""
    s = result["summary"]
    overall = result["overall"].get("__all__", {})
    total = s["total_signals"]
    cov_3d = s.get("coverage_3d", 0)

    lines = [
        "# 观察池有效性评估",
        "",
        "## 1. 评价区间",
        f"  {result['start_date']} ~ {result['end_date']}",
        f"  评价基准日: {result.get('as_of_date', 'N/A')}",
        "",
    ]

    if cov_3d < 0.3:
        lines.append("> **注意：本期多数信号来自近期，3 日表现尚未完全成熟。因此当前 3 日指标样本量较小，不能据此对策略优劣做强结论。**")
        lines.append("")

    lines += [
        "## 2. 数据覆盖率与样本成熟度",
        "",
        f"  - 总信号数: {total}",
        f"  - 1 日可评价: {s['eligible_1d']}",
        f"  - 1 日实际评价: {s['evaluated_1d']}",
        f"  - 覆盖率 (1d): {_fmt_pct(s.get('coverage_1d', 0))}",
        f"  - 3 日可评价: {s['eligible_3d']}",
        f"  - 3 日实际评价: {s['evaluated_3d']}",
        f"  - 覆盖率 (3d): {_fmt_pct(s.get('coverage_3d', 0))}",
        "",
        "### 缺失原因",
        "",
        "| 原因 | 数量 | 说明 |",
        "|---|---:|---|",
    ]
    for reason, count in sorted(s.get("missing_reasons", {}).items(), key=lambda x: -x[1]):
        label = REASON_LABELS.get(reason, reason)
        lines.append(f"| {reason} | {count} | {label} |")

    lines += ["", "## 3. 总体表现"]
    if overall:
        lines += [
            f"  - 平均次日收益 (1d): {_fmt_pct(overall.get('avg_next_1d_return'))} (n={overall.get('evaluated_1d_count', 0)})",
            f"  - 次日胜率: {_fmt_pct(overall.get('win_rate_1d'))}",
            f"  - 平均 3 日收益: {_fmt_pct(overall.get('avg_next_3d_return'))} (n={overall.get('evaluated_3d_count', 0)})",
            f"  - 3 日胜率: {_fmt_pct(overall.get('win_rate_3d'))}",
            f"  - 平均 3 日最高涨幅: {_fmt_pct(overall.get('avg_max_3d_return'))}",
            f"  - 平均 3 日下行幅度: {_fmt_pct(overall.get('avg_max_3d_drawdown'))}",
        ]
    else:
        lines.append("  (无有效数据)")

    for section_title, group_data in [
        ("## 4. 按策略来源分组", result.get("by_strategy", {})),
        ("## 5. 按观察池分层分组", result.get("by_layer", {})),
        ("## 6. 按风险等级分组", result.get("by_risk_level", {})),
    ]:
        lines += ["", section_title, ""]
        if not group_data:
            lines.append("  (无数据)")
            continue
        lines.append(_build_table_rows(group_data, include_3d=True))

    lines += [
        "",
        "## 7. 数据缺失与注意事项",
        "",
        "- 行情来源：get_stock_history 临时获取，评价结果依赖当前行情接口可用性",
        "- price_fetch_failed 会影响覆盖率",
        "- 入选日期距今不足 3 个交易日时，3 日指标标记为缺失",
        "- 本评价只用于复盘观察池表现，不构成实盘交易建议",
        "",
        "## 8. 初步结论",
        "",
    ]
    if cov_3d < 0.3:
        lines.append("样本不足，仅做覆盖率观察，不做策略优劣判断。")
        lines.append("")
    lines += [
        "本报告仅反映历史观察池样本的后验表现；",
        "样本量较小时不做强结论；",
        "不作为实盘买卖依据。",
    ]
    return "\n".join(lines)


def build_daily_markdown(result):
    """daily 模式 Markdown：T+1 验证报告"""
    s = result["summary"]
    overall = result["overall"].get("__all__", {})
    total = s["total_signals"]

    lines = [
        "# 昨日观察池 T+1 验证报告",
        "",
        "## 1. 验证对象",
        f"  - 信号日期: {result.get('signal_date', 'N/A')}",
        f"  - 验证日期: {result.get('as_of_date', 'N/A')}",
        f"  - 样本数: {total}",
        "",
        "## 2. 总体表现",
    ]
    if overall:
        lines += [
            f"  - 1 日可评价样本数: {s.get('eligible_1d', 0)}",
            f"  - 1 日实际评价样本数: {overall.get('evaluated_1d_count', 0)}",
            f"  - 平均次日收益: {_fmt_pct(overall.get('avg_next_1d_return'))}",
            f"  - 次日胜率: {_fmt_pct(overall.get('win_rate_1d'))}",
            f"  - 平均最大下行幅度 (1d): {_fmt_pct(overall.get('avg_max_3d_drawdown'))}",
        ]
    else:
        lines.append("  (暂无 T+1 数据)")

    # 分层
    for section_title, group_data in [
        ("## 3. 按观察池分层", result.get("by_layer", {})),
        ("## 4. 按策略来源", result.get("by_strategy", {})),
        ("## 5. 按风险等级", result.get("by_risk_level", {})),
    ]:
        lines += ["", section_title, ""]
        if not group_data:
            lines.append("  (无数据)")
            continue
        lines.append(_build_table_rows(group_data, include_3d=False))
        lines.append("")

    # 验证标签分布
    tag_counts = Counter(r.get("verification_tag", "unknown") for r in result.get("details", []))
    if tag_counts:
        lines += [
            "## 6. 验证标签分布",
            "",
            "| 标签 | 数量 | 说明 |",
            "|---|---:|---|",
            f"| hit | {tag_counts.get('hit', 0)} | 信号被市场验证 |",
            f"| miss | {tag_counts.get('miss', 0)} | 信号未被市场验证 |",
            f"| neutral | {tag_counts.get('neutral', 0)} | 中性/符合预期 |",
            f"| insufficient | {tag_counts.get('insufficient', 0)} | 数据不足无法判断 |",
        ]

    lines += [
        "",
        "## 7. 缺失原因",
        "",
        "| 原因 | 数量 | 说明 |",
        "|---|---:|---|",
    ]
    for reason, count in sorted(s.get("missing_reasons", {}).items(), key=lambda x: -x[1]):
        label = REASON_LABELS.get(reason, reason)
        lines.append(f"| {reason} | {count} | {label} |")

    lines += [
        "",
        "## 8. 初步结论",
        "",
    ]
    if total >= 5 and overall.get("evaluated_1d_count", 0) >= 3:
        lines.append(f"本次验证覆盖 {overall.get('evaluated_1d_count', 0)}/{total} 条信号。")
    else:
        lines.append("样本量不足，仅做数据跟踪，不做策略优劣判断。")
    lines += [
        "",
        "> 行情来源：get_stock_history 临时获取。评价结果依赖当前行情接口可用性。",
        "> price_fetch_failed 会影响覆盖率。",
        "> 本报告用于验证昨日观察池表现，不构成实盘买卖建议。",
    ]
    return "\n".join(lines)


def _fmt_pct(val):
    if val is None:
        return "N/A"
    return f"{val * 100:.2f}%"


def resolve_date_range(args):
    end = datetime.now()
    if args.start and args.end:
        return args.start, args.end
    days = args.days if args.days else 30
    start = end - timedelta(days=days)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def evaluate_records(signals):
    """对信号列表逐条评价，返回 records + 汇总计数"""
    records = []
    eligible_1d = 0
    eligible_3d = 0
    evaluated_1d = 0
    evaluated_3d = 0
    missing_reasons = Counter()

    for i, sig in enumerate(signals):
        metrics, status = evaluate_signal_performance(sig)
        layer = resolve_layer(sig)
        strategy = str(sig.get("strategy", "unknown") or "unknown").strip()
        risk = str(sig.get("risk_level", "unknown") or "unknown").strip()

        if status["eligible_1d"]:
            eligible_1d += 1
        if status["eligible_3d"]:
            eligible_3d += 1
        if status["evaluated_1d"]:
            evaluated_1d += 1
        if status["evaluated_3d"]:
            evaluated_3d += 1
        for reason in status.get("missing_reasons", []):
            missing_reasons[reason] += 1

        r1 = metrics["next_1d_return"] if metrics else None
        dd3 = metrics["max_3d_drawdown"] if metrics else None
        vtag = compute_verification_tag(r1, dd3, layer)

        record = {
            "signal_key": build_signal_key(sig),
            "trade_date": sig["trade_date"],
            "code": str(sig.get("code", "")),
            "name": str(sig.get("name", "")),
            "strategy": strategy,
            "watchlist_layer": layer,
            "risk_level": risk,
            "entry_close": metrics["entry_close"] if metrics else None,
            "metrics": metrics,
            "status": status,
            "verification_tag": vtag,
            "debug": {
                "entry_close_found": status["entry_close_found"],
                "as_of_close_found": status["as_of_close_found"],
                "price_dates_count": len(status.get("price_dates", [])),
                "price_dates_last": status["price_dates"][-1] if status.get("price_dates") else None,
            } if not metrics else None,
        }
        records.append(record)

        if (i + 1) % 50 == 0:
            print(f"  进度: {i + 1}/{len(signals)} (1d {evaluated_1d}, 3d {evaluated_3d})")

    return records, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons


def build_summary(total, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons):
    coverage_1d = evaluated_1d / total if total > 0 else 0
    coverage_3d = evaluated_3d / total if total > 0 else 0
    return {
        "total_signals": total,
        "eligible_1d": eligible_1d,
        "evaluated_1d": evaluated_1d,
        "coverage_1d": coverage_1d,
        "eligible_3d": eligible_3d,
        "evaluated_3d": evaluated_3d,
        "coverage_3d": coverage_3d,
        "missing_price_data": total - evaluated_1d,
        "missing_reasons": dict(missing_reasons),
    }


def build_result(records, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons, extra=None):
    """构建统一结果结构"""
    total = len(records)
    summary = build_summary(total, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons)
    overall = aggregate_metrics(records, group_key=None)
    by_strategy = aggregate_metrics(records, group_key="strategy")
    by_layer = aggregate_metrics(records, group_key="watchlist_layer")
    by_risk = aggregate_metrics(records, group_key="risk_level")

    result = {
        "status": "ok",
        "summary": summary,
        "overall": overall,
        "by_strategy": by_strategy,
        "by_layer": by_layer,
        "by_risk_level": by_risk,
        "details": records,
    }
    if extra:
        result.update(extra)
    return result


def main():
    parser = argparse.ArgumentParser(description="观察池有效性评估（唯一评价入口）")
    parser.add_argument("--mode", type=str, default="range", choices=["range", "daily"],
                        help="评价模式（默认 range）")
    parser.add_argument("--start", type=str, default=None, help="range: 起始日期 YYYYMMDD")
    parser.add_argument("--end", type=str, default=None, help="range: 结束日期 YYYYMMDD")
    parser.add_argument("--days", type=int, default=None, help="range: 最近 N 天")
    parser.add_argument("--signal-date", type=str, default=None, help="daily: 信号日期 YYYYMMDD")
    parser.add_argument("--as-of", type=str, default=None, help="评价基准日 YYYYMMDD（默认今天）")
    args = parser.parse_args()

    as_of_date = args.as_of if args.as_of else datetime.now().strftime("%Y%m%d")

    if not DATABASE_DSN:
        print("[ERROR] DATABASE_DSN 未配置")
        sys.exit(1)

    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"[ERROR] 数据库连接失败: {e}")
        sys.exit(1)

    eval_dir = REPORT_DIR / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "daily":
        # ── daily 模式 ──
        if not args.signal_date:
            print("[ERROR] daily 模式需要 --signal-date")
            conn.close()
            sys.exit(1)

        print(f"=== 观察池 T+1 验证（daily）===")
        print(f"信号日期: {args.signal_date}")
        print(f"验证日期: {as_of_date}\n")

        signals = fetch_signals_for_date(conn, args.signal_date)
        conn.close()

        if not signals:
            print(f"日期 {args.signal_date} 无信号数据")
            return

        print(f"读取信号: {len(signals)} 条")
        records, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons = evaluate_records(signals)
        total = len(signals)
        print(f"评价完成: 总 {total}, 1d {evaluated_1d}, 3d {evaluated_3d}")

        extra = {
            "signal_date": args.signal_date,
            "as_of_date": as_of_date,
            "mode": "daily",
        }
        result = build_result(records, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons, extra)
        markdown = build_daily_markdown(result)

        suffix = f"{args.signal_date}_{as_of_date}"
        json_path = eval_dir / f"daily_watchlist_evaluation_{suffix}.json"
        md_path = eval_dir / f"daily_watchlist_evaluation_{suffix}.md"

    else:
        # ── range 模式（默认） ──
        start_date, end_date = resolve_date_range(args)

        print(f"=== 观察池有效性评估（range）===")
        print(f"评价区间: {start_date} ~ {end_date}")
        print(f"基准日:   {as_of_date}\n")

        signals = fetch_signals(conn, start_date, end_date)
        conn.close()

        if not signals:
            print("评价区间内无信号数据")
            return

        print(f"读取信号: {len(signals)} 条")
        records, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons = evaluate_records(signals)
        total = len(signals)
        print(f"评价完成: 总 {total}, 1d {evaluated_1d}, 3d {evaluated_3d}")

        extra = {
            "start_date": start_date,
            "end_date": end_date,
            "as_of_date": as_of_date,
            "mode": "range",
        }
        result = build_result(records, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons, extra)
        markdown = build_range_markdown(result)

        suffix = f"{start_date}_{end_date}"
        json_path = eval_dir / f"watchlist_evaluation_{suffix}.json"
        md_path = eval_dir / f"watchlist_evaluation_{suffix}.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")

    print(f"\nJSON: {json_path}")
    print(f"MD:   {md_path}")


if __name__ == "__main__":
    main()
