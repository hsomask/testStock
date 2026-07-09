"""Unified correction engine for trade-plan candidate decisions.

The engine owns recommendation-layer corrections: strategy feedback,
mainline fit, entry quality, and context feedback. Callers keep their existing
entry points, but decision logic should flow through this module instead of
being repeated in rendering or orchestration code.
"""
import math

import pandas as pd


CORRECTION_ENGINE_VERSION = "2026-07-09-v2"
STRATEGY_FEEDBACK_VERSION = "strategy-feedback-v1"
CONTEXT_FEEDBACK_VERSION = "context-feedback-v1"
BAD_ENTRY_QUALITIES = {"高位追强", "短线偏高", "量能过热", "波段偏高"}


def load_strategy_feedback(window_days=5):
    try:
        from analysis.strategy_feedback import load_latest_strategy_feedback
        return load_latest_strategy_feedback(window_days=window_days)
    except Exception:
        return {}


def load_context_feedback():
    try:
        from analysis.context_feedback import load_latest_context_feedback
        return load_latest_context_feedback()
    except Exception:
        return {}


def safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        val = float(value)
        if math.isnan(val):
            return None
        return val
    except Exception:
        return None


def fmt_pct(value):
    val = safe_float(value)
    return "-" if val is None else f"{val:.1%}"


def direction_fit_score(primary_direction, preferred_clusters):
    direction = str(primary_direction or "").strip()
    preferred = [str(x).strip() for x in (preferred_clusters or []) if str(x).strip()]
    if not direction or direction == "-":
        return 50
    if not preferred:
        return 70
    return 100 if direction in preferred else 60


def entry_quality(row):
    pct_chg = safe_float(row.get("pct_chg"))
    pct_5d = safe_float(row.get("pct_5d"))
    pct_20d = safe_float(row.get("pct_20d"))
    volume_ratio = safe_float(row.get("volume_ratio"))
    close = safe_float(row.get("close"))
    low = safe_float(row.get("observe_low"))
    high = safe_float(row.get("observe_high"))

    if pct_chg is not None and pct_chg >= 9:
        return "高位追强"
    if pct_5d is not None and pct_5d >= 20:
        return "短线偏高"
    if volume_ratio is not None and volume_ratio >= 6:
        return "量能过热"
    if pct_20d is not None and pct_20d >= 50:
        return "波段偏高"
    if close is not None and low is not None and high is not None and low <= close <= high:
        return "分歧低吸"
    return "均线承接"


def _strategy_feedback_decision(category, reason, strategy, feedback):
    status = feedback.get("status")
    if status not in ("weak", "blocked"):
        return category, reason, []

    sample = feedback.get("sample_count") or 0
    win_rate = fmt_pct(feedback.get("win_rate_1d"))
    failed_rate = fmt_pct(feedback.get("failed_rate"))
    feedback_reason = feedback.get("reason") or "策略近期反馈偏弱"
    note = f"策略反馈降级：近5日样本{sample}，胜率{win_rate}，失败率{failed_rate}，{feedback_reason}"
    tags = ["策略反馈偏弱"]

    if status == "weak" and category == "候选低吸":
        return "只观察", f"{reason}；{note}", tags
    if status == "blocked" and category in ("候选低吸", "只观察"):
        return "交易条件不满足", f"{reason}；{note}", tags
    return category, reason, tags


def _rule_correction(category, reason, score, quality):
    tags = []
    if score >= 100:
        tags.append("主线一致")
    elif score < 80:
        tags.append("非今日主线")
        if category == "候选低吸":
            category = "只观察"
            reason = f"{reason}；纠偏降级：非今日主线，先观察承接"

    tags.append(quality)
    if quality in BAD_ENTRY_QUALITIES and category == "候选低吸":
        category = "只观察"
        reason = f"{reason}；纠偏降级：{quality}，不追高"

    return category, reason, tags


def _context_reason(item, label):
    sample = item.get("sample_count") or 0
    win_rate = fmt_pct(item.get("win_rate_1d"))
    failed_rate = fmt_pct(item.get("failed_rate"))
    reason = item.get("reason") or "场景反馈偏弱"
    return f"{label}近20日样本{sample}，胜率{win_rate}，失败率{failed_rate}，{reason}"


def _context_decision(category, reason, strategy, market_status, score, quality, primary_direction, context_feedback):
    direction_bucket = "mainline" if score >= 80 else "non_mainline"
    checks = [
        ("strategy_market", strategy, str(market_status or ""), f"{strategy}/{market_status}"),
        ("strategy_direction", strategy, direction_bucket, f"{strategy}/主线匹配"),
        ("strategy_entry", strategy, str(quality or ""), f"{strategy}/{quality}"),
        ("direction", "", str(primary_direction or ""), f"{primary_direction}方向"),
    ]

    hits = []
    for dim, strat, scene, label in checks:
        item = context_feedback.get((dim, strat, scene))
        if item and item.get("status") in ("weak", "blocked"):
            hits.append((dim, item, label))

    if not hits:
        return category, reason, None, []

    blocked = [x for x in hits if x[1].get("status") == "blocked"]
    selected = blocked[0] if blocked else hits[0]
    _, item, label = selected
    note = _context_reason(item, label)
    tags = [f"场景反馈:{x[2]}" for x in hits[:3]]

    if category == "候选低吸":
        category = "交易条件不满足" if item.get("status") == "blocked" else "只观察"
        reason = f"{reason}；场景反馈降级：{note}"
    elif category == "只观察" and item.get("status") == "blocked":
        category = "交易条件不满足"
        reason = f"{reason}；场景反馈强降级：{note}"
    elif "场景反馈" not in reason:
        reason = f"{reason}；场景反馈提示：{note}"

    return category, reason, item, tags


def _data_quality_decision(category, reason, strategy, data_confidence):
    try:
        confidence = float(data_confidence or 0)
    except Exception:
        confidence = 0
    if strategy == "滚雪球趋势" and confidence < 70 and category == "候选低吸":
        return "只观察", "报告可信度低于70，只观察，不生成候选低吸", ["数据可信度不足"]
    return category, reason, []


def _correction_level(base_layer, final_layer, feedback_status, context_item, score, quality):
    if final_layer == "交易条件不满足" and base_layer != final_layer:
        return "blocked"
    if final_layer == "只观察" and base_layer == "候选低吸":
        return "weak"
    if feedback_status == "blocked" or (context_item and context_item.get("status") == "blocked"):
        return "blocked"
    if feedback_status == "weak" or (context_item and context_item.get("status") == "weak"):
        return "weak"
    if score < 80 or quality in BAD_ENTRY_QUALITIES:
        return "mild"
    return "none"


def decision_score(base_layer, direction_score, quality, feedback, context_item):
    score = 50.0
    if base_layer == "候选低吸":
        score += 20
    elif base_layer == "只观察":
        score += 5
    elif base_layer == "交易条件不满足":
        score -= 10
    elif base_layer == "高风险回避":
        score -= 25

    score += (float(direction_score or 0) - 70) * 0.25
    if quality == "分歧低吸":
        score += 8
    elif quality == "均线承接":
        score += 4
    elif quality in BAD_ENTRY_QUALITIES:
        score -= 12

    fb_score = safe_float(feedback.get("feedback_score") if feedback else None)
    if fb_score is not None:
        score += (fb_score - 50) * 0.2
    if feedback and feedback.get("status") == "weak":
        score -= 8
    if feedback and feedback.get("status") == "blocked":
        score -= 16
    if context_item and context_item.get("status") == "weak":
        score -= 8
    if context_item and context_item.get("status") == "blocked":
        score -= 16

    return round(max(0, min(100, score)), 1)


def display_reason(final_layer, correction_level, tags, reason):
    if final_layer == "高风险回避":
        return "风险偏高，仅复盘"
    if "场景反馈强降级" in reason:
        return "场景反馈偏弱，交易条件不满足"
    if "场景反馈降级" in reason:
        return "场景反馈偏弱，先观察"
    if "纠偏降级" in reason:
        if "非今日主线" in tags:
            return "纠偏降级：非今日主线，先观察"
        for tag in BAD_ENTRY_QUALITIES:
            if tag in tags or tag in reason:
                return f"纠偏降级：{tag}，不追高"
        return "纠偏降级，先观察"
    if "策略反馈降级" in reason or "策略反馈偏弱" in tags:
        return "策略反馈偏弱，先降级"
    if "数据可信度不足" in tags:
        return "报告可信度低于70，只观察"
    if final_layer == "候选低吸":
        return "主线一致，等待分歧低吸"
    if final_layer == "交易条件不满足":
        return reason
    if correction_level in ("weak", "blocked"):
        return "反馈偏弱，先观察"
    return "条件不足，等确认"


def terminal_decision(*, layer, reason, row=None, primary_direction="-", preferred_clusters=None):
    """Normalize a terminal decision that must not enter correction rules."""
    if row is None:
        row = {}
    score = direction_fit_score(primary_direction, preferred_clusters or [])
    quality = entry_quality(row)
    return {
        "base_layer": layer,
        "final_layer": layer,
        "reason": reason,
        "display_reason": reason,
        "decision_score": 0.0,
        "direction_fit_score": score,
        "entry_quality": quality,
        "correction_level": "terminal",
        "correction_tags": [layer],
        "decision_reasons": [reason],
        "correction_engine_version": CORRECTION_ENGINE_VERSION,
        "strategy_feedback_version": STRATEGY_FEEDBACK_VERSION,
        "context_feedback_version": CONTEXT_FEEDBACK_VERSION,
        "strategy_feedback": {},
        "context_feedback": {},
    }


def evaluate_candidate(
    *,
    base_layer,
    base_reason,
    row,
    strategy,
    primary_direction,
    preferred_clusters,
    market_status,
    data_confidence=None,
    strategy_feedback_map=None,
    context_feedback_map=None,
):
    """Return a normalized correction decision for one candidate."""
    strategy_feedback_map = strategy_feedback_map or {}
    context_feedback_map = context_feedback_map or {}
    feedback = strategy_feedback_map.get(strategy) or {}

    final_layer = base_layer
    reason = base_reason
    score = direction_fit_score(primary_direction, preferred_clusters)
    quality = entry_quality(row)

    final_layer, reason, strategy_tags = _strategy_feedback_decision(final_layer, reason, strategy, feedback)
    final_layer, reason, rule_tags = _rule_correction(final_layer, reason, score, quality)
    final_layer, reason, context_item, context_tags = _context_decision(
        final_layer,
        reason,
        strategy,
        market_status,
        score,
        quality,
        primary_direction,
        context_feedback_map,
    )
    final_layer, reason, data_tags = _data_quality_decision(
        final_layer,
        reason,
        strategy,
        data_confidence,
    )

    tags = []
    for tag in strategy_tags + rule_tags + context_tags + data_tags:
        if tag and tag not in tags:
            tags.append(tag)

    level = _correction_level(base_layer, final_layer, feedback.get("status"), context_item, score, quality)
    dscore = decision_score(base_layer, score, quality, feedback, context_item)

    return {
        "base_layer": base_layer,
        "final_layer": final_layer,
        "reason": reason,
        "display_reason": display_reason(final_layer, level, tags, reason),
        "decision_score": dscore,
        "direction_fit_score": score,
        "entry_quality": quality,
        "correction_level": level,
        "correction_tags": tags,
        "decision_reasons": [reason],
        "correction_engine_version": CORRECTION_ENGINE_VERSION,
        "strategy_feedback_version": STRATEGY_FEEDBACK_VERSION,
        "context_feedback_version": CONTEXT_FEEDBACK_VERSION,
        "strategy_feedback": feedback,
        "context_feedback": context_item,
    }
