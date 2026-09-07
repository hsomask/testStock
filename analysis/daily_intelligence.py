"""Unified daily intelligence view for reports, email and sidecar output.

This module is presentation-only.  It does not select stocks, fetch market
data, write trading tables, or change evaluation facts.  Its job is to turn
existing daily facts into one reader-facing decision view.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from analysis.daily_decision import FINAL_LAYERS, normalize_final_plans
from analysis.report_insights import (
    assess_profit_effect,
    check_weak_market,
    compute_market_width,
    explain_sentiment_stage,
    generate_validation_checklist,
    validate_position_consistency,
)


INTELLIGENCE_SCHEMA_VERSION = "daily_intelligence_v1"

DISPLAY_LAYERS = (
    ("候选低吸", "可以考虑", "满足条件才考虑"),
    ("只观察", "只观察", "只看不动，等待确认"),
    ("交易条件不满足", "暂不行动", "条件还没到，暂不进入主动观察"),
    ("高风险回避", "明确回避", "风险偏高，只复盘不参与"),
    ("不可交易过滤", "不可交易", "流动性、状态或规则过滤"),
)


def _short(value: Any, max_len: int = 46) -> str:
    text = str(value or "").replace("\n", "；").replace("|", "/").strip()
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _fmt_pct(value: Any, default: str = "N/A") -> str:
    try:
        if value is None:
            return default
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return default


def _fmt_pct_raw(value: Any, default: str = "N/A") -> str:
    try:
        if value is None:
            return default
        return f"{float(value):.2f}%"
    except Exception:
        return default


def _fmt_num(value: Any, digits: int = 2, default: str = "-") -> str:
    try:
        if value is None:
            return default
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    except Exception:
        return default


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _entry_zone(stock: dict[str, Any]) -> str:
    low = stock.get("observe_low", stock.get("buy_low"))
    high = stock.get("observe_high", stock.get("buy_high"))
    low_s = _fmt_num(low)
    high_s = _fmt_num(high)
    if low_s == "-" and high_s == "-":
        return "-"
    if low_s == high_s or high_s == "-":
        return low_s
    if low_s == "-":
        return high_s
    return f"{low_s}~{high_s}"


def _stop_price(stock: dict[str, Any]) -> str:
    return _fmt_num(stock.get("invalid_price", stock.get("stop_loss")))


def _target_price(stock: dict[str, Any]) -> str:
    return _fmt_num(stock.get("pressure_price", stock.get("target")))


def _decision_plans(trade_plan: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    decision = (trade_plan or {}).get("decision") or {}
    plans = decision.get("plans") or (trade_plan or {}).get("plans") or {}
    normalized = normalize_final_plans(plans)
    return {layer: [dict(item) for item in normalized.get(layer, []) or []] for layer in FINAL_LAYERS}


def _mode_from_trade_plan(trade_plan: dict[str, Any] | None) -> tuple[str, str, str]:
    decision = (trade_plan or {}).get("decision") or {}
    mode = decision.get("mode") or {}
    execution = decision.get("execution") or {}
    if mode.get("name"):
        return (
            str(mode.get("code") or ""),
            str(mode.get("name") or "空仓"),
            str(execution.get("summary") or mode.get("summary") or "按统一交易计划执行。"),
        )
    restrictions = (trade_plan or {}).get("market_restrictions") or {}
    name = str(restrictions.get("trade_mode") or "空仓")
    return "", name, "缺少统一交易决策对象，按保守模式展示。"


def _mode_actions(mode_name: str) -> tuple[str, str]:
    actions = {
        "进攻": ("主线核心分歧低吸", "追高扩散、无主线普买"),
        "试错": ("小仓试错、只看核心方向", "后排跟风加仓、情绪高潮追入"),
        "防守": ("观察为主，极小仓核心低吸", "追高、中位股、跟风加仓"),
        "空仓": ("复盘观察，等待修复", "新开仓、追涨、补仓摊平"),
    }
    return actions.get(mode_name, ("观察为主", "追高"))


def _extract_directions(board_ratio_changes: Any) -> tuple[list[str], list[str]]:
    if board_ratio_changes is None:
        return [], []
    rows = []
    try:
        if hasattr(board_ratio_changes, "to_dict"):
            rows = board_ratio_changes.to_dict("records")
        elif isinstance(board_ratio_changes, list):
            rows = board_ratio_changes
    except Exception:
        rows = []
    rising, falling = [], []
    for row in rows:
        name = str(row.get("board_name") or row.get("name") or "").strip()
        if not name:
            continue
        change = row.get("ratio_change_3d", row.get("ratio_change_5d", 0))
        try:
            change_f = float(change or 0)
        except Exception:
            change_f = 0
        target = rising if change_f >= 0 else falling
        if name not in target:
            target.append(name)
    return rising[:5], falling[:5]


def _avoid_text(falling: list[str], avoid_do: str) -> str:
    if falling:
        return "、".join(falling[:3])
    return f"暂无明确退潮方向；操作上避免{avoid_do}"


def _fallback_watch_directions(action_plan: dict[str, Any]) -> list[str]:
    counts: dict[str, int] = {}
    for section in action_plan.get("sections") or []:
        for item in section.get("items") or []:
            name = str(item.get("direction") or "").strip()
            if not name or name == "-":
                continue
            counts[name] = counts.get(name, 0) + 1
    return [
        name for name, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ][:5]


def _outcome_fact(ret: Any, label: str | None) -> str:
    try:
        r = float(ret)
    except Exception:
        if label == "data_insufficient":
            return "数据不足，暂不评价"
        return "结果待确认"
    if r <= -0.095:
        return "次日跌停或接近跌停，信号失败"
    if r <= -0.05:
        return "次日大跌，信号失败"
    if r <= -0.03:
        return "次日下跌超过3%，承接失败"
    if r < 0:
        return "次日小幅走弱，承接不足"
    if r >= 0.095:
        return "次日涨停或接近涨停，信号强兑现"
    if r >= 0.05:
        return "次日大涨，信号强兑现"
    if r >= 0.03:
        return "次日上涨超过3%，信号兑现"
    return "次日小幅走强，信号部分兑现"


def _learning_adjustment(ret: Any, reason: str, label: str | None) -> str:
    try:
        r = float(ret)
    except Exception:
        return "样本不成熟，不进入策略纠偏"
    if r <= -0.03:
        if "策略" in reason:
            return "对应策略继续降权，等待胜率修复"
        if "涨幅" in reason or "追高" in reason or "位置" in reason:
            return "高位加速票降低优先级，只等分歧承接"
        if "均线" in reason:
            return "跌破均线类样本降低买点容错"
        return "记录失败样本，继续积累同类特征"
    if r >= 0.03:
        if "涨幅接近涨停" in reason or "追高" in reason:
            return "虽强兑现，但仍只作高波动样本观察"
        return "记录有效样本，增加同类条件置信度"
    return "弱反馈样本，暂不改变规则权重"


def _review_item(item: dict[str, Any], category: str) -> dict[str, Any]:
    ret = item.get("ret", item.get("next_1d_return"))
    label = item.get("feedback_label")
    reason = str(item.get("attribution_text") or item.get("feedback_reason") or "")
    return {
        "category": category,
        "name": item.get("name") or item.get("code") or "-",
        "layer": item.get("layer") or item.get("final_layer") or item.get("yesterday_layer") or "-",
        "return": ret,
        "return_text": _fmt_pct(ret),
        "outcome_fact": _outcome_fact(ret, label),
        "possible_reason": _short(reason or "现有字段未定位到单一原因", 52),
        "learning_adjustment": _short(_learning_adjustment(ret, reason, label), 52),
    }


def _build_t1_review(t1_data: dict[str, Any] | None) -> dict[str, Any]:
    data = t1_data or {}
    status = data.get("status")
    if not data.get("available") or status in {"defer", "missing"}:
        return {
            "available": False,
            "status": status or "missing",
            "summary": data.get("message") or data.get("reason") or "Evaluation 尚未形成完整结果",
            "rows": [],
            "learning_quality": "pending",
        }
    td = data.get("data") or data
    top = (td.get("top_winners") or td.get("top") or [])[:3]
    bottom = (td.get("top_losers") or td.get("bottom") or [])[:3]
    rows = [_review_item(item, "较好") for item in top]
    rows.extend(_review_item(item, "较弱") for item in bottom)
    coverage = 0.0
    try:
        coverage = float(td.get("evaluated_1d", 0) or 0) / max(float(td.get("total_signals", 0) or 0), 1.0)
    except Exception:
        coverage = 0.0
    official = status == "ok"
    if official and coverage >= 0.9:
        learning_quality = "正式学习样本"
    elif coverage >= 0.8:
        learning_quality = "低权重观察样本"
    else:
        learning_quality = "只复盘，不进入学习"
    return {
        "available": True,
        "status": status,
        "official": official,
        "evaluated": td.get("evaluated_1d", 0),
        "total": td.get("total_signals", 0),
        "coverage": coverage,
        "avg_return": td.get("avg_return_1d", td.get("avg_next_1d_return")),
        "win_rate": td.get("win_rate_1d"),
        "summary": "正式样本，可用于修正次日计划" if official else "降级样本，只作方向观察",
        "learning_quality": learning_quality,
        "rows": rows,
        "correction_effectiveness": data.get("correction_effectiveness") or {},
    }


def build_t1_review_view(t1_data: dict[str, Any] | None) -> dict[str, Any]:
    """Public wrapper for safe rerender tools that only update the T+1 block."""
    return _build_t1_review(t1_data)


def _stock_reason(item: dict[str, Any]) -> str:
    return _short(
        item.get("display_reason")
        or item.get("reason")
        or item.get("entry_reason")
        or item.get("risk_reasons")
        or "等待确认",
        58,
    )


def _build_action_plan(trade_plan: dict[str, Any] | None) -> dict[str, Any]:
    plans = _decision_plans(trade_plan)
    sections = []
    for raw_layer, title, description in DISPLAY_LAYERS:
        items = []
        for item in plans.get(raw_layer, []) or []:
            items.append({
                "code": item.get("code"),
                "name": item.get("name") or item.get("code") or "-",
                "strategy": item.get("strategy") or "-",
                "direction": item.get("board_name") or item.get("primary_direction") or item.get("industry") or "-",
                "entry_zone": _entry_zone(item),
                "target": _target_price(item),
                "stop": _stop_price(item),
                "reason": _stock_reason(item),
            })
        sections.append({
            "layer": raw_layer,
            "title": title,
            "description": description,
            "count": len(items),
            "items": items,
        })
    return {
        "sections": sections,
        "counts": {s["layer"]: s["count"] for s in sections},
        "total": sum(s["count"] for s in sections),
    }


def _build_risk_board(market_read: dict[str, Any], action_plan: dict[str, Any]) -> list[str]:
    risks = []
    if market_read.get("width_weak"):
        risks.append("市场宽度偏弱，机会集中在少数方向，不做扩散普买。")
    if market_read.get("sentiment_stage") in {"高潮", "过热"}:
        risks.append("短线情绪偏热，避免后排跟风和加速追入。")
    counts = action_plan.get("counts") or {}
    if counts.get("交易条件不满足", 0) > counts.get("候选低吸", 0):
        risks.append("多数入池标的尚未满足交易条件，明日重点是等触发而不是提前买。")
    if counts.get("高风险回避", 0) or counts.get("不可交易过滤", 0):
        risks.append("高风险或不可交易标的只用于复盘，不进入正常候选。")
    return list(dict.fromkeys(risks))[:4]


def build_daily_intelligence(
    trade_date: str,
    data_status: Any,
    quality: dict[str, Any],
    market: dict[str, Any],
    industry: Any = None,
    concept: Any = None,
    sentiment: dict[str, Any] | None = None,
    selectors: Any = None,
    board_ratio_changes: Any = None,
    mode: str = "unified",
    trade_plan: dict[str, Any] | None = None,
    board_trend_summary: Any = None,
    report_context: dict[str, Any] | None = None,
    themes: list[dict[str, Any]] | None = None,
    t1_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market = market or {}
    sentiment = sentiment or {}
    width = compute_market_width(market)
    profit = assess_profit_effect(market)
    weak_triggers, weak_checked, weak_items, green_ratio, lb_ratio = check_weak_market(market)
    s_score = sentiment.get("score", 0)
    s_stage, _ = explain_sentiment_stage(s_score, sentiment.get("stage", ""))
    pos = validate_position_consistency(trade_plan)
    mode_code, mode_name, mode_summary = _mode_from_trade_plan(trade_plan)
    can_do, avoid_do = _mode_actions(mode_name)
    market_status_text = str(market.get("status", "") or "")
    width_weak = bool(
        width.get("green_ratio", 0) > 0.6
        or width.get("adv_ratio", 1) < 0.5
        or "宽度偏弱" in market_status_text
        or "宽度弱" in market_status_text
    )
    if width_weak:
        width_impact = "机会集中，只看核心承接"
    else:
        width_impact = "宽度尚可，仍需确认持续性"
    profit_detail = str(profit.get("detail") or "")
    if width_weak and "宽度正常" in profit_detail:
        profit_detail = "短线仍有活跃方向，但下跌家数更多，赚钱效应集中在少数主线。"
    rising, falling = _extract_directions(board_ratio_changes)
    action_plan = _build_action_plan(trade_plan)
    if not rising:
        rising = _fallback_watch_directions(action_plan)
    market_read = {
        "score": market.get("score", 0),
        "status": market.get("status", ""),
        "summary": market.get("summary", ""),
        "mode_code": mode_code,
        "mode_name": mode_name,
        "mode_summary": mode_summary,
        "can_do": can_do,
        "avoid_do": avoid_do,
        "width": width,
        "width_weak": width_weak,
        "width_impact": width_impact,
        "profit_level": profit.get("level"),
        "profit_detail": profit_detail,
        "weak_triggers": weak_triggers,
        "weak_checked": weak_checked,
        "weak_items": weak_items,
        "green_ratio": green_ratio,
        "limit_breadth_ratio": lb_ratio,
        "sentiment_score": s_score,
        "sentiment_stage": s_stage,
        "rising_directions": rising,
        "falling_directions": falling,
        "position": pos,
    }
    validations = generate_validation_checklist(
        market, [{"name": name} for name in rising[:3]], profit, weak_triggers
    )[:3]
    t1_review = _build_t1_review(t1_data)
    learning_state = {
        "t1_quality": t1_review.get("learning_quality"),
        "coverage": t1_review.get("coverage"),
        "ml_ready": bool(t1_review.get("official") and (t1_review.get("coverage") or 0) >= 0.9),
        "note": "进入正式反馈/ML候选样本" if t1_review.get("official") and (t1_review.get("coverage") or 0) >= 0.9 else "仅复盘观察，等待覆盖率或样本成熟",
    }
    risk_board = _build_risk_board(market_read, action_plan)
    return {
        "schema_version": INTELLIGENCE_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "mode": mode,
        "headline": {
            "mode": mode_name,
            "summary": mode_summary,
            "position_text": f"0~{min(pos.get('max_pct', 0), 3)}成，确认后上限{pos.get('max_pct', 0)}成",
            "single_position_text": f"单票上限{pos.get('single_pct', 0)}成",
            "watch": "、".join(rising[:3]) or "暂无明确主线",
            "avoid": _avoid_text(falling, avoid_do),
        },
        "market_read": market_read,
        "t1_review": t1_review,
        "action_plan": action_plan,
        "risk_board": risk_board,
        "validations": validations or ["主线是否继续获得资金承接", "高位亏钱效应是否扩大", "观察池是否满足触发条件"],
        "data_quality": deepcopy(quality or {}),
        "learning_state": learning_state,
        "raw_refs": {
            "has_data_status": bool(data_status),
            "industry_present": industry is not None,
            "concept_present": concept is not None,
            "selectors_present": selectors is not None,
            "board_trend_summary_present": board_trend_summary is not None,
            "report_context_present": report_context is not None,
            "theme_count": len(themes or []),
        },
    }


def _render_plan_section(lines: list[str], section: dict[str, Any]) -> None:
    lines.extend([f"#### {section['title']}（{section['count']}只）", ""])
    items = section.get("items") or []
    if not items:
        lines.extend(["暂无。", ""])
        return
    limit = 8 if section["count"] <= 8 else 8
    lines.extend(["| 股票 | 策略 | 方向 | 买点/观察区 | 目标 | 止损/失效 | 原因 |", "|---|---|---|---|---|---|---|"])
    for item in items[:limit]:
        lines.append(
            f"| {item['name']} | {item['strategy']} | {item['direction']} | "
            f"{item['entry_zone']} | {item['target']} | {item['stop']} | {_short(item['reason'], 34)} |"
        )
    if section["count"] > limit:
        lines.append(f"| ... | ... | ... | ... | ... | ... | 另有{section['count'] - limit}只见附录 |")
    lines.append("")


def render_daily_intelligence_markdown(ctx: dict[str, Any]) -> str:
    trade_date = ctx["trade_date"]
    date_display = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    h = ctx["headline"]
    m = ctx["market_read"]
    q = ctx["data_quality"]
    t1 = ctx["t1_review"]
    learning = ctx["learning_state"]
    pos = m["position"]
    lines = [
        "---",
        f"date: {date_display}",
        f"schema_version: {ctx['schema_version']}",
        f"market_status: {m.get('status')}",
        f"market_score: {m.get('score')}",
        f"sentiment_stage: {m.get('sentiment_stage')}",
        f"position_cap: {pos.get('max_pct', 0)}成",
        f"data_confidence: {q.get('confidence_score', 0)}",
        "---",
        "",
        f"# A股收盘复盘与次日计划｜{date_display}",
        "",
        "## 0. 明天怎么做",
        "",
        f"> **{h['mode']}模式。{h['summary']}**",
        "",
        f"- 仓位：{h['position_text']}，{h['single_position_text']}",
        f"- 只看：{h['watch']}",
        f"- 不碰：{h['avoid']}",
        "",
        "| 复盘项目 | 今日结果 | 对次日的影响 |",
        "|---|---|---|",
        f"| 市场环境 | {m.get('status')}（{float(m.get('score') or 0):.1f}分） | {m.get('can_do')} |",
        f"| 短线情绪 | {m.get('sentiment_stage')}（{float(m.get('sentiment_score') or 0):.1f}分） | 避免{m.get('avoid_do')} |",
        f"| 市场宽度 | 上涨{m['width'].get('up_count', 0)} / 下跌{m['width'].get('down_count', 0)} | {m.get('width_impact')} |",
        f"| 赚钱效应 | {m.get('profit_level')} | {_short(m.get('profit_detail'), 48)} |",
        f"| 数据可信度 | {q.get('confidence_score', 0)}/100 | {'可用于次日计划' if q.get('confidence_score', 0) >= 80 else '只作观察，不下确定结论'} |",
        "",
        "## 1. 昨日观察池兑现复盘（T+1）",
        "",
    ]
    if not t1.get("available"):
        lines.extend([f"> **暂缓评价：** {t1.get('summary')}。明日计划不使用未成熟收益结论。", ""])
    else:
        lines.extend([
            f"**完成度：** {t1.get('evaluated', 0)}/{t1.get('total', 0)}　"
            f"**平均收益：** {_fmt_pct(t1.get('avg_return'))}　"
            f"**上涨比例：** {_fmt_pct(t1.get('win_rate'))}　"
            f"**学习状态：** {t1.get('learning_quality')}",
            "",
            f"> **复盘结论：** {t1.get('summary')}。",
            "",
        ])
        rows = t1.get("rows") or []
        if rows:
            lines.extend(["| 分类 | 股票 | 表现 | 结果事实 | 可能原因 | 后续调整 |", "|---|---|---:|---|---|---|"])
            for row in rows:
                lines.append(
                    f"| {row['category']} | {row['name']} | {row['return_text']} | "
                    f"{row['outcome_fact']} | {row['possible_reason']} | {row['learning_adjustment']} |"
                )
            lines.append("")
    lines.extend([
        "## 2. 明日观察池",
        "",
        f"> 观察池总数 {ctx['action_plan']['total']} 只。先看可考虑；没有可考虑时，看“暂不行动”里哪些条件最接近。",
        "",
    ])
    for section in ctx["action_plan"]["sections"]:
        if section["layer"] == "不可交易过滤" and section["count"] == 0:
            continue
        _render_plan_section(lines, section)
    lines.extend([
        "## 3. 市场与主线",
        "",
        f"- 市场发生了什么：{m.get('summary') or '市场数据生成中'}",
        f"- 主线观察：{h['watch']}。",
        f"- 退潮回避：{h['avoid']}。",
        f"- 明日核心判断：{m.get('width_impact')}；{m.get('can_do')}。",
        "",
        "## 4. 风险与失效",
        "",
    ])
    for item in ctx.get("risk_board") or ["没有新增高优先级风险。"]:
        lines.append(f"- {item}")
    lines.extend(["", "## 5. 数据与学习状态", ""])
    lines.extend([
        f"- 信号数据：{'正常' if ctx['raw_refs'].get('has_data_status') else '待确认'}",
        f"- 数据可信度：{q.get('confidence_score', 0)}/100",
        f"- T+1学习样本：{learning.get('t1_quality')}；{learning.get('note')}",
        f"- 完整指标与审计明细：[查看附录](daily_report_{trade_date}_appendix.md)",
        "",
        "---",
        "",
        "本报告仅用于数据复盘和学习，不构成任何投资建议。",
    ])
    return "\n".join(lines)


def daily_intelligence_to_email(ctx: dict[str, Any]) -> str:
    h = ctx["headline"]
    t1 = ctx["t1_review"]
    q = ctx["data_quality"]
    parts = [
        "## 明天怎么做",
        f"- 模式：{h['mode']}，{h['summary']}",
        f"- 仓位：{h['position_text']}，{h['single_position_text']}",
        f"- 只看：{h['watch']}",
        f"- 不碰：{h['avoid']}",
        "",
        "## 昨日复盘",
    ]
    if t1.get("available"):
        parts.append(
            f"- 完成度：{t1.get('evaluated', 0)}/{t1.get('total', 0)}；"
            f"平均收益：{_fmt_pct(t1.get('avg_return'))}；"
            f"上涨比例：{_fmt_pct(t1.get('win_rate'))}；"
            f"学习状态：{t1.get('learning_quality')}"
        )
    else:
        parts.append(f"- 暂缓评价：{t1.get('summary')}")
    parts.extend(["", "## 明日观察池"])
    for section in ctx["action_plan"]["sections"]:
        if section["count"]:
            parts.append(f"- {section['title']}：{section['count']}只")
    parts.extend([
        "",
        "## 数据状态",
        f"- 数据可信度：{q.get('confidence_score', 0)}/100",
        f"- LLM/ML上下文：daily_intelligence_{ctx['trade_date']}.json",
    ])
    return "\n".join(parts)


def intelligence_llm_view(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded sidecar view for future LLM use."""
    return {
        "schema_version": ctx["schema_version"],
        "trade_date": ctx["trade_date"],
        "headline": ctx["headline"],
        "market_read": {
            key: ctx["market_read"].get(key)
            for key in (
                "score", "status", "mode_name", "mode_summary", "width_weak",
                "width_impact", "profit_level", "profit_detail",
                "sentiment_score", "sentiment_stage",
            )
        },
        "t1_review": {
            key: ctx["t1_review"].get(key)
            for key in (
                "available", "status", "official", "evaluated", "total",
                "coverage", "avg_return", "win_rate", "summary",
                "learning_quality",
            )
        },
        "t1_examples": ctx["t1_review"].get("rows", [])[:6],
        "action_counts": ctx["action_plan"].get("counts", {}),
        "risk_board": ctx.get("risk_board") or [],
        "data_quality": ctx.get("data_quality") or {},
        "learning_state": ctx.get("learning_state") or {},
        "policy": {
            "allowed_tasks": ["explain", "summarize", "compare", "diagnose"],
            "forbidden_tasks": ["select_new_stocks", "change_position", "write_trading_tables"],
        },
    }


def write_daily_intelligence_sidecar(ctx: dict[str, Any], out_dir: str | Path) -> Path:
    path = Path(out_dir) / f"daily_intelligence_{ctx['trade_date']}.json"
    path.write_text(
        json.dumps(intelligence_llm_view(ctx), ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return path
