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
import uuid
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

from data.config import DATABASE_DSN, REPORT_DIR
from analysis.data_fetcher import get_stock_history
from analysis.evaluation_time import EVALUATION_SCHEMA_VERSION, resolve_evaluation_horizons
from analysis.limitup_metrics import is_near_limit_up
from analysis.signal_identity import ensure_signal_id

# ── 进程内行情缓存：同一只股票同一次运行只调一次 API ──
_HIST_CACHE = {}


def _cached_get_history(code, days=80):
    """带缓存的 get_stock_history，同一 code+days 在一次运行中只获取一次。
    用更大 days 获取的数据会覆盖小 days 的缓存。
    """
    cache_key = f"{code}"
    existing = _HIST_CACHE.get(cache_key)
    if existing is not None:
        existing_days = existing[0]
        existing_hist = existing[1]
        # 已有缓存且请求的 days 不大于缓存时直接返回
        if days <= existing_days:
            return existing_hist
        # 请求更大 days，但已有 500 天缓存则不再重复获取
        if existing_days >= 500 and days <= 500:
            return existing_hist
    hist = get_stock_history(code, days=days)
    _HIST_CACHE[cache_key] = (days, hist)
    return hist


def _cache_update(code, hist):
    """手动用 days=500 结果覆盖缓存"""
    _HIST_CACHE[str(code)] = (500, hist)


def prime_history_cache_from_db(conn, codes):
    """Prime evaluation history without API calls or cache writes."""
    normalized = sorted({str(code or "").strip() for code in codes if str(code or "").strip()})
    if not normalized:
        return 0
    cur = conn.cursor()
    cur.execute(
        """
        SELECT code, trade_date, close, high, low
        FROM stock_hist_kline
        WHERE code = ANY(%s)
        ORDER BY code, trade_date
        """,
        (normalized,),
    )
    rows = cur.fetchall()
    cur.close()
    grouped = defaultdict(list)
    for code, trade_date, close, high, low in rows:
        grouped[str(code)].append({
            "date": trade_date,
            "close": close,
            "high": high,
            "low": low,
        })
    for code in normalized:
        _cache_update(code, pd.DataFrame(grouped.get(code, [])))
    return len(grouped)

logger = logging.getLogger(__name__)

LAYER_FALLBACK_FIELDS = [
    "final_decision_layer",
    "watchlist_layer",
    "action_signal",
    "signal_type",
]

REASON_LABELS = {
    "not_mature_1d": "入选时间太近，尚无 1 个后续交易日",
    "not_mature_3d": "入选时间太近，尚无 3 个后续交易日",
    "insufficient_future_days_for_3d": "有部分后续数据但不足 3 个交易日",
    "price_fetch_failed": "历史行情获取失败",
    "missing_entry_close": "入选日收盘价缺失",
    "invalid_code": "股票代码无效",
    "invalid_close_price": "入选日收盘价异常",
    "entry_date_not_found": "行情数据中找不到入选日期",
    "missing_t1_price": "T+1目标交易日缺少该股票价格（可能停牌或数据缺失）",
    "missing_t3_window_price": "T+1至T+3精确交易日窗口价格不完整",
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
    """Legacy persistence key; stable cross-table identity uses signal_id."""
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
        "id", "signal_id", "decision_id", "source_run_id",
        "final_decision_layer",
        "trade_date", "code", "name", "strategy", "risk_level",
        "action_signal", "signal_type", "watchlist_layer", "close_price",
        "pct_chg", "volume_ratio", "turnover", "ma5", "ma10", "ma20",
        "pct_5d", "pct_20d", "hot_board_hits", "entry_reasons", "risk_reasons",
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
        "id", "signal_id", "decision_id", "source_run_id",
        "final_decision_layer",
        "trade_date", "code", "name", "strategy", "risk_level",
        "action_signal", "signal_type", "watchlist_layer", "close_price",
        "pct_chg", "volume_ratio", "turnover", "ma5", "ma10", "ma20",
        "pct_5d", "pct_20d", "hot_board_hits", "entry_reasons", "risk_reasons",
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


def compute_verification_tag(next_1d_return, layer):
    """T+1 verification uses T+1 facts only and is immutable after first write."""
    if next_1d_return is None:
        return "insufficient"

    r1 = next_1d_return

    if layer in ("观察",):
        if r1 > 0:
            tag = "hit"
        else:
            tag = "miss"
    elif layer in ("谨慎", "谨慎观望"):
        if abs(r1) <= 0.03:
            tag = "neutral"
        elif r1 > 0.03:
            tag = "miss"
        else:
            tag = "hit"
    elif layer in ("回避", "高", "高风险"):
        if r1 < 0:
            tag = "hit"
        elif r1 > 0.03:
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


def compute_t3_verification_tag(next_3d_return, max_3d_drawdown, layer):
    """Independent T+3 verification; never overwrites the T+1 tag."""
    if next_3d_return is None:
        return "insufficient"
    if layer in ("回避", "高", "高风险", "谨慎", "谨慎观望"):
        if next_3d_return < 0 or (max_3d_drawdown is not None and max_3d_drawdown <= -0.05):
            return "hit"
        return "miss" if next_3d_return > 0.03 else "neutral"
    if next_3d_return > 0:
        return "hit"
    return "miss" if next_3d_return < 0 else "neutral"


def _safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def compute_feedback(signal, metrics, status):
    """Build an immutable feedback label using T+1 facts only."""
    if not metrics:
        reasons = status.get("missing_reasons", []) if status else []
        return {
            "feedback_label": "data_insufficient",
            "feedback_score": None,
            "attribution_tags": ["data_insufficient"] + list(reasons[:3]),
            "attribution_text": "K线覆盖不足，暂不评价强弱。",
        }

    r1 = metrics.get("next_1d_return")
    if r1 is None:
        label = "data_insufficient"
    elif r1 >= 0.03:
        label = "strong_follow"
    elif r1 >= 0:
        label = "walk_strong"
    elif r1 <= -0.03:
        label = "failed"
    else:
        label = "weak"

    score = 50.0
    if r1 is not None:
        score += r1 * 500
    feedback_score = round(max(0, min(100, score)), 1)

    tags = []
    pct_chg = _safe_float(signal.get("pct_chg"))
    pct_5d = _safe_float(signal.get("pct_5d"))
    pct_20d = _safe_float(signal.get("pct_20d"))
    volume_ratio = _safe_float(signal.get("volume_ratio"))
    next_close = _safe_float(metrics.get("next_1d_close"))
    entry_reasons = str(signal.get("entry_reasons") or signal.get("entry_reason") or "")
    risk_reasons = str(signal.get("risk_reasons") or "")
    strategy = str(signal.get("strategy") or "")

    if pct_chg is not None and is_near_limit_up(
        pct_chg,
        signal.get("code", ""),
        signal.get("name", ""),
    ):
        tags.append("gap_or_chase_risk")
    elif pct_chg is not None and pct_chg >= 7:
        tags.append("high_intraday_position")

    if volume_ratio is not None and volume_ratio >= 6:
        tags.append("volume_overheat")
    elif volume_ratio is not None and volume_ratio < 0.8:
        tags.append("weak_volume")

    if pct_5d is not None and pct_5d >= 20:
        tags.append("short_term_extended")
    if pct_20d is not None and pct_20d >= 50:
        tags.append("swing_position_extended")

    if "策略反馈降级" in entry_reasons or "策略反馈偏弱" in entry_reasons:
        tags.append("strategy_recently_weak")
    if "非今日主线" in entry_reasons or "非今日主线" in risk_reasons:
        tags.append("non_mainline_no_support")
    if "纠偏降级" in entry_reasons:
        tags.append("correction_downgraded")
    if strategy in ("N字异动", "一次起爆", "二次起爆") and label in ("weak", "failed"):
        tags.append("short_pattern_failed")

    if next_close is not None:
        broken = []
        for ma_name in ("ma5", "ma10", "ma20"):
            ma_val = _safe_float(signal.get(ma_name))
            if ma_val is not None and ma_val > 0 and next_close < ma_val:
                broken.append(ma_name.upper())
        if broken:
            tags.append("ma_breakdown:" + "/".join(broken))

    if label in ("weak", "failed") and not tags:
        tags.append("weak_follow_without_clear_context")
    if label in ("strong_follow", "walk_strong") and not tags:
        tags.append("pattern_confirmed")

    tag_text = {
        "gap_or_chase_risk": "信号日涨幅接近涨停，次日追高风险较高",
        "high_intraday_position": "信号日涨幅偏高，适合降低追高权重",
        "volume_overheat": "信号日量比过高，可能存在短线高潮",
        "weak_volume": "信号日量能不足，承接确认偏弱",
        "short_term_extended": "5日涨幅偏大，短线位置偏高",
        "swing_position_extended": "20日涨幅偏大，波段位置偏高",
        "strategy_recently_weak": "策略近期反馈偏弱，继续作为降级因子",
        "non_mainline_no_support": "非今日主线，次日承接不足",
        "correction_downgraded": "信号已被纠偏降级，后续继续验证降级是否有效",
        "short_pattern_failed": "短线形态策略次日未兑现，需分市场环境继续观察",
        "weak_follow_without_clear_context": "次日走弱，现有字段未定位到单一原因",
        "pattern_confirmed": "次日反馈验证了信号有效性",
    }

    readable = []
    for tag in tags:
        base = tag.split(":", 1)[0]
        if base == "ma_breakdown":
            readable.append("T+1跌破关键均线：" + tag.split(":", 1)[1])
        else:
            readable.append(tag_text.get(tag, tag))

    return {
        "feedback_label": label,
        "feedback_score": feedback_score,
        "attribution_tags": tags,
        "attribution_text": "；".join(readable[:5]),
    }


def compute_t3_feedback(metrics, status):
    """Build T+3-only feedback without consulting or changing T+1 fields."""
    if not metrics or metrics.get("next_3d_return") is None:
        return {
            "feedback_label_3d": "data_insufficient",
            "feedback_score_3d": None,
            "attribution_tags_3d": ["data_insufficient"],
            "attribution_text_3d": "T+3尚未成熟或三日价格不完整。",
        }
    r3 = float(metrics["next_3d_return"])
    max3 = metrics.get("max_3d_return")
    dd3 = metrics.get("max_3d_drawdown")
    if r3 >= 0.05 or (max3 is not None and max3 >= 0.08):
        label = "strong_3d"
    elif r3 > 0:
        label = "positive_3d"
    elif r3 <= -0.05 or (dd3 is not None and dd3 <= -0.08):
        label = "failed_3d"
    else:
        label = "weak_3d"
    score = 50 + r3 * 350
    if max3 is not None:
        score += float(max3) * 80
    if dd3 is not None:
        score += float(dd3) * 100
    return {
        "feedback_label_3d": label,
        "feedback_score_3d": round(max(0, min(100, score)), 1),
        "attribution_tags_3d": [label],
        "attribution_text_3d": f"T+3收益{r3:.2%}，三日内最高/最低表现独立评价。",
    }


def evaluate_signal_performance(signal, as_of_date=None, horizon="full", calendar=None):
    """
    统一单条信号评价函数（range 和 daily 共用）。
    返回 (metrics_dict, status_dict)

    T+1/T+3 use exact exchange trading dates. A suspended stock therefore has
    missing horizon data instead of silently shifting to its next available bar.
    ``horizon='t1'`` prevents a daily T+1 run from computing any T+3 fields.
    """
    code = str(signal.get("code", "")).strip()
    trade_date = signal["trade_date"]
    as_of_date = as_of_date or datetime.now().strftime("%Y%m%d")
    time_model = resolve_evaluation_horizons(trade_date, as_of_date, calendar=calendar)
    close_price_raw = signal.get("close_price")

    status = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "target_1d_date": time_model["t1_date"],
        "target_3d_date": time_model["t3_date"],
        "eligible_1d": time_model["t1_mature"],
        "eligible_3d": horizon in ("t3", "full") and time_model["t3_mature"],
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
        hist = _cached_get_history(code, days=80)
    except Exception:
        status["missing_reasons"].append("price_fetch_failed")
        return None, status

    if hist is None or hist.empty or "date" not in hist.columns:
        status["missing_reasons"].append("price_fetch_failed")
        return None, status

    hist = hist.copy()
    hist["_evaluation_date"] = hist["date"].astype(str).str.replace("-", "").str[:8]
    all_dates = hist["_evaluation_date"]
    status["price_dates"] = sorted(all_dates.unique().tolist())

    if trade_date in set(all_dates):
        status["entry_close_found"] = True

    target_dates = [
        value for value in (
            time_model["t1_date"],
            time_model["t2_date"],
            time_model["t3_date"],
        )
        if value and value <= time_model["run_as_of_date"]
    ]
    future = hist[hist["_evaluation_date"].isin(target_dates)].sort_values("_evaluation_date")

    required_dates = (
        [time_model["t1_date"]] if horizon == "t1" and time_model["t1_mature"]
        else target_dates
    )
    found_dates = set(future["_evaluation_date"].tolist())
    if any(value and value not in found_dates for value in required_dates):
        try:
            hist = _cached_get_history(code, days=500)
            if hist is not None and not hist.empty and "date" in hist.columns:
                hist = hist.copy()
                hist["_evaluation_date"] = hist["date"].astype(str).str.replace("-", "").str[:8]
                all_dates = hist["_evaluation_date"]
                status["price_dates"] = sorted(all_dates.unique().tolist())
                if trade_date in set(all_dates):
                    status["entry_close_found"] = True
                future = hist[hist["_evaluation_date"].isin(target_dates)].sort_values("_evaluation_date")
                _cache_update(code, hist)
        except Exception:
            pass

    found_dates = set(future["_evaluation_date"].tolist()) if not future.empty else set()
    status["as_of_close_found"] = time_model["run_as_of_date"] in set(status["price_dates"])
    if not status["entry_close_found"]:
        status["missing_reasons"].append("entry_date_not_found")
    if not time_model["t1_mature"]:
        status["missing_reasons"].append("not_mature_1d")
    elif time_model["t1_date"] not in found_dates:
        status["missing_reasons"].append("missing_t1_price")
    if horizon in ("t3", "full"):
        if not time_model["t3_mature"]:
            status["missing_reasons"].append("not_mature_3d")
        elif any(value not in found_dates for value in target_dates[:3]):
            status["missing_reasons"].append("missing_t3_window_price")

    # 1d
    next_1d_return = None
    next_1d_close = None
    t1_rows = future[future["_evaluation_date"] == time_model["t1_date"]]
    if time_model["t1_mature"] and not t1_rows.empty:
        try:
            next_1d_close = float(t1_rows.iloc[0]["close"])
            next_1d_return = next_1d_close / close_price - 1
            status["evaluated_1d"] = True
        except (TypeError, ValueError):
            pass

    # 3d
    next_3d_return = None
    max_3d_return = None
    max_3d_drawdown = None
    exact_window = future[future["_evaluation_date"].isin(target_dates[:3])]
    exact_window = exact_window.sort_values("_evaluation_date")
    if (
        horizon in ("t3", "full")
        and time_model["t3_mature"]
        and len(exact_window) == 3
        and set(exact_window["_evaluation_date"]) == set(target_dates[:3])
    ):
        window = exact_window
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
        "next_1d_close": next_1d_close,
        "next_1d_return": next_1d_return,
        "next_3d_return": next_3d_return,
        "max_3d_return": max_3d_return,
        "max_3d_drawdown": max_3d_drawdown,
        "target_1d_date": time_model["t1_date"],
        "target_3d_date": time_model["t3_date"],
    }
    return (metrics if status["evaluated_1d"] or status["evaluated_3d"] else None), status


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


def compute_diagnostics(summary, overall, by_layer, by_strategy, by_risk, records, mode):
    """生成评价诊断"""
    s = summary
    o = overall.get("__all__", {})
    total = s["total_signals"]
    evaluated_1d = s["evaluated_1d"]
    evaluated_3d = s["evaluated_3d"]
    cov_1d = s["coverage_1d"]
    cov_3d = s["coverage_3d"]
    messages = []

    # ── confidence_level ──
    if evaluated_1d < 20 or cov_1d < 0.3:
        confidence_level = "insufficient_data"
    elif mode == "daily":
        confidence_level = "daily_observation"
    elif evaluated_3d >= 100 and cov_3d >= 0.6:
        confidence_level = "actionable_review"
    elif evaluated_3d >= 30 and cov_3d >= 0.3:
        confidence_level = "preliminary_pattern"
    else:
        confidence_level = "insufficient_data"

    conclusion_map = {
        "insufficient_data": "observe_only",
        "daily_observation": "observe_only",
        "preliminary_pattern": "preliminary",
        "actionable_review": "review_required",
    }
    conclusion_level = conclusion_map.get(confidence_level, "observe_only")

    # ── data_quality ──
    data_quality = {
        "coverage_1d": cov_1d,
        "coverage_3d": cov_3d,
        "evaluated_1d": evaluated_1d,
        "evaluated_3d": evaluated_3d,
        "price_fetch_failed": s.get("missing_reasons", {}).get("price_fetch_failed", 0),
        "missing_reasons": s.get("missing_reasons", {}),
    }
    if cov_1d < 0.8:
        messages.append("1 日覆盖率不足，T+1 结果不稳定。")
    if data_quality["price_fetch_failed"] > 0:
        messages.append("仍有行情获取失败样本，需关注数据源稳定性。")

    # ── layer_diagnostics ──
    def _match_layer(key, candidates):
        for c in candidates:
            if c in key:
                return True
        return False

    watch_groups = [k for k in by_layer if _match_layer(k, ["观察", "可观察"])]
    caution_groups = [k for k in by_layer if _match_layer(k, ["谨慎"])]
    high_risk_groups = [k for k in by_layer if _match_layer(k, ["回避", "高", "高风险"])]

    watch_data = by_layer.get(watch_groups[0], {}) if watch_groups else {}
    high_risk_data = by_layer.get(high_risk_groups[0], {}) if high_risk_groups else {}
    # fallback: if no 回避/高风险 layer, try 高 from by_risk
    if not high_risk_data:
        risk_high_keys = [k for k in by_risk if k in ("高", "高风险", "回避")]
        high_risk_data = by_risk.get(risk_high_keys[0], {}) if risk_high_keys else {}

    layer_diagnostics = {
        "layer_inversion_warning": False,
        "message": "",
        "details": {},
    }

    if watch_data and high_risk_data:
        w_ret = watch_data.get("avg_next_1d_return")
        h_ret = high_risk_data.get("avg_next_1d_return")
        w_wr = watch_data.get("win_rate_1d")
        h_wr = high_risk_data.get("win_rate_1d")
        w_cnt = watch_data.get("evaluated_1d_count", 0)
        h_cnt = high_risk_data.get("evaluated_1d_count", 0)

        layer_diagnostics["details"] = {
            "watch_avg_return": w_ret, "watch_win_rate": w_wr, "watch_count": w_cnt,
            "high_risk_avg_return": h_ret, "high_risk_win_rate": h_wr, "high_risk_count": h_cnt,
        }

        if w_cnt >= 5 and h_cnt >= 5 and h_ret is not None and w_ret is not None:
            if h_ret > w_ret + 0.01 and (h_wr or 0) > (w_wr or 0):
                layer_diagnostics["layer_inversion_warning"] = True
                layer_diagnostics["message"] = (
                    "出现分层倒挂：高风险/回避层 T+1 表现优于观察层。"
                    "当前仅作单日/区间观察，不建议单次结果直接调参。"
                )
                messages.append(layer_diagnostics["message"])
            else:
                layer_diagnostics["message"] = "分层表现符合预期。"
        else:
            layer_diagnostics["message"] = "分层样本不足，暂不判断分层有效性。"
    else:
        layer_diagnostics["message"] = "分层数据缺失，无法判断。"

    # ── risk_diagnostics ──
    risk_diagnostics = {"high_risk_hit_rate": None, "risk_warning": False, "message": ""}
    if high_risk_data and high_risk_data.get("evaluated_1d_count", 0) >= 5:
        hr_records = [r for r in records
                      if r.get("watchlist_layer") in high_risk_groups
                      or r.get("risk_level") in ("高", "高风险", "回避")]
        if hr_records:
            down_count = sum(1 for r in hr_records
                           if r.get("metrics") and r["metrics"].get("next_1d_return") is not None
                           and r["metrics"]["next_1d_return"] < 0)
            risk_diagnostics["high_risk_hit_rate"] = down_count / high_risk_data["evaluated_1d_count"]

            if risk_diagnostics["high_risk_hit_rate"] < 0.4 and (high_risk_data.get("avg_next_1d_return") or 0) > 0:
                risk_diagnostics["risk_warning"] = True
                risk_diagnostics["message"] = "高风险提示当日未明显兑现，需连续观察是否过度保守。"
                messages.append(risk_diagnostics["message"])
            else:
                risk_diagnostics["message"] = "高风险提示有效性正常。"
    else:
        risk_diagnostics["message"] = "高风险样本不足，暂不评估风险提示有效性。"

    # ── strategy_diagnostics ──
    strategy_diag = {
        "underperforming_strategies": [],
        "outperforming_strategies": [],
        "warnings": [],
    }
    overall_ret = o.get("avg_next_1d_return")
    if overall_ret is not None:
        for sname, sdata in by_strategy.items():
            s_ret = sdata.get("avg_next_1d_return")
            s_cnt = sdata.get("evaluated_1d_count", 0)
            if s_cnt >= 10 and s_ret is not None:
                if s_ret < overall_ret - 0.015:
                    entry = {
                        "strategy": sname,
                        "evaluated_1d_count": s_cnt,
                        "avg_next_1d_return": s_ret,
                        "overall_avg_next_1d_return": overall_ret,
                        "message": f"{sname} 当日表现弱于整体，需连续观察。",
                    }
                    strategy_diag["underperforming_strategies"].append(entry)
                    strategy_diag["warnings"].append(entry["message"])
                    messages.append(entry["message"])
                elif s_ret > overall_ret + 0.015:
                    strategy_diag["outperforming_strategies"].append({
                        "strategy": sname,
                        "evaluated_1d_count": s_cnt,
                        "avg_next_1d_return": s_ret,
                        "overall_avg_next_1d_return": overall_ret,
                        "message": f"{sname} 当日表现优于整体，仅作观察，不作为策略调整依据。",
                    })

    return {
        "confidence_level": confidence_level,
        "conclusion_level": conclusion_level,
        "data_quality": data_quality,
        "layer_diagnostics": layer_diagnostics,
        "risk_diagnostics": risk_diagnostics,
        "strategy_diagnostics": strategy_diag,
        "diagnostic_messages": messages,
    }


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

    # ── 评价诊断 ──
    diag = result.get("diagnostics", {})
    lines += _build_diagnostics_md(diag, summary=s)

    lines += [
        "",
        "## 9. 初步结论",
        "",
    ]
    lines += _build_conclusion(diag, cov_3d)
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

    # ── 评价诊断 ──
    diag = result.get("diagnostics", {})
    lines += _build_diagnostics_md(diag, summary=s)

    lines += [
        "",
        "## 9. 初步结论",
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


def _build_diagnostics_md(diag, summary=None):
    """构建评价诊断 Markdown 章节"""
    if not diag:
        return []

    lines = [
        "",
        "## 7. 评价诊断",
        "",
        "### 7.1 数据质量",
        f"  - 1 日覆盖率: {_fmt_pct(diag.get('data_quality', {}).get('coverage_1d'))}",
        f"  - 3 日覆盖率: {_fmt_pct(diag.get('data_quality', {}).get('coverage_3d'))}",
        f"  - 行情缺失数量: {diag.get('data_quality', {}).get('price_fetch_failed', 0)}",
        f"  - 置信等级: {diag.get('confidence_level', 'N/A')}",
        "",
        "### 7.2 分层有效性",
    ]

    ld = diag.get("layer_diagnostics", {})
    lines.append(f"  - 是否出现分层倒挂: {'**是**' if ld.get('layer_inversion_warning') else '否'}")
    lines.append(f"  - 诊断说明: {ld.get('message', 'N/A')}")

    lines += [
        "",
        "### 7.3 高风险提示有效性",
    ]
    rd = diag.get("risk_diagnostics", {})
    lines.append(f"  - 高风险提示命中率: {_fmt_pct(rd.get('high_risk_hit_rate'))}")
    lines.append(f"  - 诊断说明: {rd.get('message', 'N/A')}")

    lines += [
        "",
        "### 7.4 策略表现异常",
    ]
    sd = diag.get("strategy_diagnostics", {})
    under = sd.get("underperforming_strategies", [])
    over = sd.get("outperforming_strategies", [])

    if under:
        weak_names = ", ".join(s["strategy"] for s in under)
        lines.append(f"  - 弱表现策略: {weak_names}")
    else:
        lines.append("  - 弱表现策略: (无)")

    if over:
        strong_names = ", ".join(s["strategy"] for s in over)
        lines.append(f"  - 强表现策略: {strong_names}")
    else:
        lines.append("  - 强表现策略: (无)")

    if sd.get("warnings"):
        lines.append("  - 说明: 单日结果不作为策略调整依据。")

    # 缺失原因表
    if summary:
        missing = summary.get("missing_reasons", {})
        if missing:
            lines += [
                "",
                "## 8. 数据缺失与注意事项",
                "",
                "| 原因 | 数量 | 说明 |",
                "|---|---:|---|",
            ]
            for reason, count in sorted(missing.items(), key=lambda x: -x[1]):
                label = REASON_LABELS.get(reason, reason)
                lines.append(f"| {reason} | {count} | {label} |")

    lines += [
        "",
        "- 行情来源：get_stock_history 临时获取，评价结果依赖当前行情接口可用性",
        "- price_fetch_failed 会影响覆盖率",
        "- 入选日期距今不足 3 个交易日时，3 日指标标记为缺失",
        "- 本评价只用于复盘观察池表现，不构成实盘交易建议",
    ]

    return lines


def _build_conclusion(diag, cov_3d):
    """根据 diagnostics 生成结论"""
    conf = diag.get("confidence_level", "insufficient_data")
    ldiag = diag.get("layer_diagnostics", {})

    if conf == "insufficient_data":
        lines = ["样本覆盖不足，仅做数据跟踪，不做策略优劣判断。"]
    elif conf == "daily_observation":
        lines = ["本次 T+1 验证覆盖率较高，可用于单日复盘观察。但单日结果不作为策略调整依据。"]
        if ldiag.get("layer_inversion_warning"):
            lines.append("本次出现分层倒挂现象，需连续观察是否为偶发市场风格切换。")
    elif conf == "preliminary_pattern":
        lines = ["样本已具备初步观察价值，可用于形成策略复盘线索，但仍不建议直接自动调参。"]
    elif conf == "actionable_review":
        lines = ["样本覆盖度和数量较高，可进入人工策略复盘阶段。"]
    else:
        lines = ["本报告仅反映历史观察池样本的后验表现。", "样本量较小时不做强结论。"]

    lines += [
        "",
        "本报告仅反映历史观察池样本的后验表现；",
        "样本量较小时不做强结论；",
        "不作为实盘买卖依据。",
    ]
    return lines


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


def evaluate_records(signals, as_of_date=None, horizon="full", calendar=None):
    """对信号列表逐条评价，返回 records + 汇总计数"""
    records = []
    eligible_1d = 0
    eligible_3d = 0
    evaluated_1d = 0
    evaluated_3d = 0
    missing_reasons = Counter()

    for i, sig in enumerate(signals):
        metrics, status = evaluate_signal_performance(
            sig,
            as_of_date=as_of_date,
            horizon=horizon,
            calendar=calendar,
        )
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
        r3 = metrics["next_3d_return"] if metrics else None
        dd3 = metrics["max_3d_drawdown"] if metrics else None
        vtag = compute_verification_tag(r1, layer)
        vtag3 = compute_t3_verification_tag(r3, dd3, layer) if horizon in ("t3", "full") else None
        feedback = compute_feedback(sig, metrics, status)
        feedback3 = (
            compute_t3_feedback(metrics, status)
            if horizon in ("t3", "full")
            else {
                "feedback_label_3d": None,
                "feedback_score_3d": None,
                "attribution_tags_3d": None,
                "attribution_text_3d": None,
            }
        )

        record = {
            "signal_key": build_signal_key(sig),
            "signal_id": ensure_signal_id(sig),
            "decision_id": sig.get("decision_id"),
            "source_run_id": sig.get("source_run_id"),
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
            "verification_tag_3d": vtag3,
            "feedback_label": feedback["feedback_label"],
            "feedback_score": feedback["feedback_score"],
            "attribution_tags": feedback["attribution_tags"],
            "attribution_text": feedback["attribution_text"],
            **feedback3,
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
    summary["distinct_stock_count"] = len({
        str(record.get("code", "")).strip()
        for record in records if str(record.get("code", "")).strip()
    })
    overall = aggregate_metrics(records, group_key=None)
    by_strategy = aggregate_metrics(records, group_key="strategy")
    by_layer = aggregate_metrics(records, group_key="watchlist_layer")
    by_risk = aggregate_metrics(records, group_key="risk_level")
    mode = extra.get("mode", "range") if extra else "range"
    diagnostics = compute_diagnostics(summary, overall, by_layer, by_strategy, by_risk, records, mode)

    result = {
        "status": "ok",
        "summary": summary,
        "overall": overall,
        "by_strategy": by_strategy,
        "by_layer": by_layer,
        "by_risk_level": by_risk,
        "diagnostics": diagnostics,
        "details": records,
    }
    if extra:
        result.update(extra)
    return result


def save_evaluation_to_db(result):
    """将评价结果写入 evaluation 专用表（upsert）"""
    if not DATABASE_DSN:
        print("[WARN] DATABASE_DSN 未配置，跳过落库")
        return

    try:
        conn = psycopg2.connect(DATABASE_DSN)
    except Exception as e:
        print(f"[WARN] 数据库连接失败，跳过落库: {e}")
        return

    summary = result["summary"]
    overall = result["overall"].get("__all__", {})
    diag = result.get("diagnostics", {})
    mode = result.get("mode", "range")
    start_date = result.get("start_date") or ""
    end_date = result.get("end_date") or ""
    signal_date = result.get("signal_date") or ""
    as_of_date = result.get("as_of_date", "") or ""
    schema_version = result.get("evaluation_schema_version")
    evaluation_phase = result.get("evaluation_phase")
    run_as_of_date = result.get("run_as_of_date") or as_of_date
    target_1d_date = result.get("target_1d_date")
    target_3d_date = result.get("target_3d_date")
    evaluation_run_id = result.get("run_id")

    try:
        cur = conn.cursor()

        # ── summary ──
        cur.execute("""
            INSERT INTO watchlist_evaluation_summary (
                eval_mode, eval_start_date, eval_end_date, signal_date, as_of_date,
                total_signals, eligible_1d, evaluated_1d, eligible_3d, evaluated_3d,
                coverage_1d, coverage_3d, price_fetch_failed,
                avg_next_1d_return, win_rate_1d, avg_next_3d_return, win_rate_3d,
                avg_max_3d_return, avg_max_3d_drawdown,
                confidence_level, conclusion_level,
                layer_inversion_warning, risk_warning,
                diagnostics_json, summary_json,
                evaluation_schema_version, evaluation_phase, run_as_of_date,
                target_1d_date, target_3d_date, t1_frozen_at,
                evaluation_run_id
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, CASE WHEN %s = 't1' THEN NOW() ELSE NULL END,
                %s
            )
            ON CONFLICT (eval_mode, eval_start_date, eval_end_date, signal_date, as_of_date)
            DO UPDATE SET
                total_signals = EXCLUDED.total_signals,
                eligible_1d = EXCLUDED.eligible_1d,
                evaluated_1d = EXCLUDED.evaluated_1d,
                eligible_3d = CASE
                    WHEN watchlist_evaluation_summary.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                    THEN EXCLUDED.eligible_3d
                    WHEN EXCLUDED.evaluation_phase = 't1'
                    THEN watchlist_evaluation_summary.eligible_3d ELSE EXCLUDED.eligible_3d END,
                evaluated_3d = CASE
                    WHEN watchlist_evaluation_summary.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                    THEN EXCLUDED.evaluated_3d
                    WHEN EXCLUDED.evaluation_phase = 't1'
                    THEN watchlist_evaluation_summary.evaluated_3d ELSE EXCLUDED.evaluated_3d END,
                coverage_1d = EXCLUDED.coverage_1d,
                coverage_3d = CASE
                    WHEN watchlist_evaluation_summary.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                    THEN EXCLUDED.coverage_3d
                    WHEN EXCLUDED.evaluation_phase = 't1'
                    THEN watchlist_evaluation_summary.coverage_3d ELSE EXCLUDED.coverage_3d END,
                price_fetch_failed = EXCLUDED.price_fetch_failed,
                avg_next_1d_return = EXCLUDED.avg_next_1d_return,
                win_rate_1d = EXCLUDED.win_rate_1d,
                avg_next_3d_return = CASE
                    WHEN watchlist_evaluation_summary.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                    THEN EXCLUDED.avg_next_3d_return
                    WHEN EXCLUDED.evaluation_phase = 't1'
                    THEN watchlist_evaluation_summary.avg_next_3d_return ELSE EXCLUDED.avg_next_3d_return END,
                win_rate_3d = CASE
                    WHEN watchlist_evaluation_summary.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                    THEN EXCLUDED.win_rate_3d
                    WHEN EXCLUDED.evaluation_phase = 't1'
                    THEN watchlist_evaluation_summary.win_rate_3d ELSE EXCLUDED.win_rate_3d END,
                avg_max_3d_return = CASE
                    WHEN watchlist_evaluation_summary.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                    THEN EXCLUDED.avg_max_3d_return
                    WHEN EXCLUDED.evaluation_phase = 't1'
                    THEN watchlist_evaluation_summary.avg_max_3d_return ELSE EXCLUDED.avg_max_3d_return END,
                avg_max_3d_drawdown = CASE
                    WHEN watchlist_evaluation_summary.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                    THEN EXCLUDED.avg_max_3d_drawdown
                    WHEN EXCLUDED.evaluation_phase = 't1'
                    THEN watchlist_evaluation_summary.avg_max_3d_drawdown ELSE EXCLUDED.avg_max_3d_drawdown END,
                confidence_level = EXCLUDED.confidence_level,
                conclusion_level = EXCLUDED.conclusion_level,
                layer_inversion_warning = EXCLUDED.layer_inversion_warning,
                risk_warning = EXCLUDED.risk_warning,
                diagnostics_json = EXCLUDED.diagnostics_json,
                summary_json = EXCLUDED.summary_json,
                evaluation_schema_version = EXCLUDED.evaluation_schema_version,
                evaluation_phase = CASE
                    WHEN EXCLUDED.evaluation_phase = 't1'
                         AND watchlist_evaluation_summary.t3_updated_at IS NOT NULL
                    THEN watchlist_evaluation_summary.evaluation_phase
                    ELSE EXCLUDED.evaluation_phase END,
                run_as_of_date = EXCLUDED.run_as_of_date,
                target_1d_date = EXCLUDED.target_1d_date,
                target_3d_date = EXCLUDED.target_3d_date,
                evaluation_run_id = COALESCE(
                    EXCLUDED.evaluation_run_id,
                    watchlist_evaluation_summary.evaluation_run_id
                ),
                t1_frozen_at = COALESCE(watchlist_evaluation_summary.t1_frozen_at, EXCLUDED.t1_frozen_at),
                generated_at = NOW()
        """, (
            mode, start_date, end_date, signal_date, as_of_date,
            summary["total_signals"], summary["eligible_1d"], summary["evaluated_1d"],
            summary["eligible_3d"], summary["evaluated_3d"],
            summary["coverage_1d"], summary["coverage_3d"],
            summary.get("missing_reasons", {}).get("price_fetch_failed", 0),
            overall.get("avg_next_1d_return"), overall.get("win_rate_1d"),
            overall.get("avg_next_3d_return"), overall.get("win_rate_3d"),
            overall.get("avg_max_3d_return"), overall.get("avg_max_3d_drawdown"),
            diag.get("confidence_level"), diag.get("conclusion_level"),
            diag.get("layer_diagnostics", {}).get("layer_inversion_warning", False),
            diag.get("risk_diagnostics", {}).get("risk_warning", False),
            json.dumps(diag, ensure_ascii=False),
            json.dumps(summary, ensure_ascii=False),
            schema_version, evaluation_phase, run_as_of_date,
            target_1d_date, target_3d_date, evaluation_phase,
            evaluation_run_id,
        ))

        # ── details ──
        for detail in result.get("details", []):
            status = detail.get("status", {})
            metrics = detail.get("metrics") or {}
            missing_reasons = status.get("missing_reasons", [])
            missing_reason = missing_reasons[0] if missing_reasons else None

            cur.execute("""
                INSERT INTO watchlist_evaluation_result (
                    eval_mode, eval_start_date, eval_end_date, signal_trade_date, as_of_date,
                    signal_key, signal_id, decision_id, evaluation_run_id,
                    code, name, strategy, watchlist_layer, risk_level,
                    action_signal, entry_close,
                    next_1d_return, next_3d_return, max_3d_return, max_3d_drawdown,
                    is_mature_1d, is_mature_3d, price_status, missing_reason, verification_tag,
                    feedback_label, feedback_score, attribution_tags, attribution_text,
                    confidence_level, conclusion_level,
                    evaluation_schema_version, target_1d_date, target_3d_date,
                    t1_evaluated_at,
                    verification_tag_3d, feedback_label_3d, feedback_score_3d,
                    attribution_tags_3d, attribution_text_3d, t3_evaluated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    CASE WHEN %s = 't1' THEN NOW() ELSE NULL END,
                    %s, %s, %s,
                    %s, %s, CASE WHEN %s = 't3' THEN NOW() ELSE NULL END
                )
                ON CONFLICT (eval_mode, eval_start_date, eval_end_date, signal_trade_date, signal_key, as_of_date)
                DO UPDATE SET
                    signal_id = EXCLUDED.signal_id,
                    decision_id = EXCLUDED.decision_id,
                    evaluation_run_id = COALESCE(
                        EXCLUDED.evaluation_run_id,
                        watchlist_evaluation_result.evaluation_run_id
                    ),
                    entry_close = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.entry_close
                        ELSE COALESCE(watchlist_evaluation_result.entry_close, EXCLUDED.entry_close) END,
                    next_1d_return = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.next_1d_return
                        ELSE COALESCE(watchlist_evaluation_result.next_1d_return, EXCLUDED.next_1d_return) END,
                    next_3d_return = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.next_3d_return
                        ELSE COALESCE(watchlist_evaluation_result.next_3d_return, EXCLUDED.next_3d_return) END,
                    max_3d_return = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.max_3d_return
                        ELSE COALESCE(watchlist_evaluation_result.max_3d_return, EXCLUDED.max_3d_return) END,
                    max_3d_drawdown = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.max_3d_drawdown
                        ELSE COALESCE(watchlist_evaluation_result.max_3d_drawdown, EXCLUDED.max_3d_drawdown) END,
                    is_mature_1d = COALESCE(watchlist_evaluation_result.is_mature_1d, FALSE) OR EXCLUDED.is_mature_1d,
                    is_mature_3d = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.is_mature_3d
                        ELSE COALESCE(watchlist_evaluation_result.is_mature_3d, FALSE) OR EXCLUDED.is_mature_3d END,
                    price_status = EXCLUDED.price_status,
                    missing_reason = EXCLUDED.missing_reason,
                    verification_tag = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.verification_tag
                        ELSE COALESCE(watchlist_evaluation_result.verification_tag, EXCLUDED.verification_tag) END,
                    feedback_label = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.feedback_label
                        ELSE COALESCE(watchlist_evaluation_result.feedback_label, EXCLUDED.feedback_label) END,
                    feedback_score = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.feedback_score
                        ELSE COALESCE(watchlist_evaluation_result.feedback_score, EXCLUDED.feedback_score) END,
                    attribution_tags = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.attribution_tags
                        ELSE COALESCE(watchlist_evaluation_result.attribution_tags, EXCLUDED.attribution_tags) END,
                    attribution_text = CASE
                        WHEN watchlist_evaluation_result.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
                        THEN EXCLUDED.attribution_text
                        ELSE COALESCE(watchlist_evaluation_result.attribution_text, EXCLUDED.attribution_text) END,
                    confidence_level = EXCLUDED.confidence_level,
                    conclusion_level = EXCLUDED.conclusion_level,
                    evaluation_schema_version = EXCLUDED.evaluation_schema_version,
                    target_1d_date = EXCLUDED.target_1d_date,
                    target_3d_date = EXCLUDED.target_3d_date,
                    t1_evaluated_at = COALESCE(watchlist_evaluation_result.t1_evaluated_at, EXCLUDED.t1_evaluated_at),
                    verification_tag_3d = COALESCE(watchlist_evaluation_result.verification_tag_3d, EXCLUDED.verification_tag_3d),
                    feedback_label_3d = COALESCE(watchlist_evaluation_result.feedback_label_3d, EXCLUDED.feedback_label_3d),
                    feedback_score_3d = COALESCE(watchlist_evaluation_result.feedback_score_3d, EXCLUDED.feedback_score_3d),
                    attribution_tags_3d = COALESCE(watchlist_evaluation_result.attribution_tags_3d, EXCLUDED.attribution_tags_3d),
                    attribution_text_3d = COALESCE(watchlist_evaluation_result.attribution_text_3d, EXCLUDED.attribution_text_3d),
                    t3_evaluated_at = COALESCE(watchlist_evaluation_result.t3_evaluated_at, EXCLUDED.t3_evaluated_at),
                    evaluated_at = NOW()
            """, (
                mode, start_date, end_date, detail["trade_date"], as_of_date,
                detail["signal_key"], detail["signal_id"], detail.get("decision_id"),
                result.get("run_id"),
                detail["code"], detail["name"],
                detail["strategy"], detail["watchlist_layer"], detail["risk_level"],
                detail.get("action_signal") or detail.get("watchlist_layer"),
                metrics.get("entry_close"),
                metrics.get("next_1d_return"), metrics.get("next_3d_return"),
                metrics.get("max_3d_return"), metrics.get("max_3d_drawdown"),
                status.get("eligible_1d", False), status.get("eligible_3d", False),
                "ok" if detail.get("metrics") else "missing",
                missing_reason,
                detail.get("verification_tag"),
                detail.get("feedback_label"),
                detail.get("feedback_score"),
                json.dumps(detail.get("attribution_tags") or [], ensure_ascii=False),
                detail.get("attribution_text"),
                diag.get("confidence_level"), diag.get("conclusion_level"),
                schema_version,
                status.get("target_1d_date") or target_1d_date,
                status.get("target_3d_date") or target_3d_date,
                evaluation_phase,
                detail.get("verification_tag_3d"),
                detail.get("feedback_label_3d"),
                detail.get("feedback_score_3d"),
                json.dumps(detail.get("attribution_tags_3d") or [], ensure_ascii=False),
                detail.get("attribution_text_3d"),
                evaluation_phase,
            ))

        conn.commit()
        n_details = len(result.get("details", []))
        print(f"\n[DB] 已写入 summary + {n_details} 条 detail 到 evaluation 表")

    except Exception as e:
        conn.rollback()
        print(f"[WARN] 落库失败，已回滚: {e}")
    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="观察池有效性评估（唯一评价入口）")
    parser.add_argument("--mode", type=str, default="range", choices=["range", "daily"],
                        help="评价模式（默认 range）")
    parser.add_argument("--start", type=str, default=None, help="range: 起始日期 YYYYMMDD")
    parser.add_argument("--end", type=str, default=None, help="range: 结束日期 YYYYMMDD")
    parser.add_argument("--days", type=int, default=None, help="range: 最近 N 天")
    parser.add_argument("--signal-date", type=str, default=None, help="daily: 信号日期 YYYYMMDD")
    parser.add_argument("--as-of", type=str, default=None, help="评价基准日 YYYYMMDD（默认今天）")
    parser.add_argument("--save-db", action="store_true", default=False, help="落库到 evaluation 专用表")
    args = parser.parse_args()

    as_of_date = args.as_of if args.as_of else datetime.now().strftime("%Y%m%d")
    evaluation_run_id = str(uuid.uuid4())

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
        time_model = resolve_evaluation_horizons(args.signal_date, as_of_date)
        if not time_model["t1_mature"]:
            print(f"[ERROR] T+1 尚未成熟，目标交易日: {time_model['t1_date']}")
            return
        records, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons = evaluate_records(
            signals,
            as_of_date=as_of_date,
            horizon="t1",
        )
        total = len(signals)
        print(f"评价完成: 总 {total}, 1d {evaluated_1d}, 3d {evaluated_3d}")

        extra = {
            "signal_date": args.signal_date,
            "as_of_date": time_model["t1_date"],
            "run_as_of_date": as_of_date,
            "target_1d_date": time_model["t1_date"],
            "target_3d_date": time_model["t3_date"],
            "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
            "evaluation_phase": "t1",
            "run_id": evaluation_run_id,
            "mode": "daily",
        }
        result = build_result(records, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons, extra)
        markdown = build_daily_markdown(result)

        suffix = f"{args.signal_date}_{time_model['t1_date']}"
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
        records, eligible_1d, eligible_3d, evaluated_1d, evaluated_3d, missing_reasons = evaluate_records(
            signals,
            as_of_date=as_of_date,
            horizon="full",
        )
        total = len(signals)
        print(f"评价完成: 总 {total}, 1d {evaluated_1d}, 3d {evaluated_3d}")

        extra = {
            "start_date": start_date,
            "end_date": end_date,
            "as_of_date": as_of_date,
            "mode": "range",
            "run_id": evaluation_run_id,
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

    if args.save_db:
        save_evaluation_to_db(result)


if __name__ == "__main__":
    main()
