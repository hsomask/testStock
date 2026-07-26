"""Canonical daily trading mode and stock-level final decision."""
from __future__ import annotations

from copy import deepcopy


DAILY_DECISION_SCHEMA_VERSION = "daily_decision_v1"
FINAL_LAYERS = (
    "候选低吸",
    "只观察",
    "交易条件不满足",
    "高风险回避",
    "不可交易过滤",
)
LAYER_PRIORITY = {
    "候选低吸": 10,
    "只观察": 20,
    "交易条件不满足": 30,
    "高风险回避": 40,
    "不可交易过滤": 50,
}
RESOLUTION_RULE = "不可交易过滤>高风险回避>交易条件不满足>只观察>候选低吸"


def _market_shape(market):
    facts = (market or {}).get("market_facts") or {}
    breadth = facts.get("breadth") or {}
    limitup = facts.get("limitup") or {}
    up = float(breadth.get("up_count", market.get("up_count", 0)) or 0)
    down = float(breadth.get("down_count", market.get("down_count", 0)) or 0)
    flat = float(breadth.get("flat_count", market.get("flat_count", 0)) or 0)
    total = up + down + flat
    limit_up = float(limitup.get("sealed_count", market.get("limit_up", 0)) or 0)
    limit_down = max(
        float(limitup.get("limit_down_count", market.get("limit_down", 0)) or 0),
        1.0,
    )
    return {
        "green_ratio": down / total if total else 0.0,
        "advance_ratio": up / max(down, 1.0),
        "limit_ratio": limit_up / limit_down,
    }


def _weak_trigger_count(market, shape):
    triggers = int(shape["green_ratio"] > 0.60) + int(shape["limit_ratio"] < 1)
    facts = (market or {}).get("market_facts") or {}
    limitup = facts.get("limitup") or {}
    if not limitup:
        limitup = (market or {}).get("limitup_stats") or {}
    yesterday_return = limitup.get("yesterday_limit_up_avg_return")
    three_board_count = limitup.get("three_board_plus_count")
    if yesterday_return is not None:
        triggers += int(float(yesterday_return or 0) < 0)
    if three_board_count is not None:
        triggers += int(int(three_board_count or 0) == 0)
    return triggers


def derive_trading_mode(market, restrictions):
    """Return stable mode code, Chinese label and explanation."""
    shape = _market_shape(market or {})
    weak_triggers = _weak_trigger_count(market or {}, shape)
    score = float((market or {}).get("score", 0) or 0)
    pos_cap = float((restrictions or {}).get("max_position_pct", 0) or 0)
    allow_trade = bool((restrictions or {}).get("allow_real_trade", True))
    profit_weak = shape["limit_ratio"] <= 1 or (
        shape["advance_ratio"] < 0.5 and shape["green_ratio"] > 0.7
    )

    if not allow_trade or pos_cap <= 0 or score < 45 or weak_triggers >= 3:
        return "empty", "空仓", "亏钱效应或交易限制较强，今日不宜开新仓。"
    if pos_cap <= 2 or shape["green_ratio"] > 0.65 or shape["advance_ratio"] < 0.5 or profit_weak:
        return "defensive", "防守", "市场宽度或赚钱效应偏弱，只看核心方向。"
    if pos_cap <= 3 or weak_triggers >= 1 or shape["green_ratio"] > 0.55:
        return "trial", "试错", "有局部机会，但确认度不足，适合小仓观察。"
    return "offensive", "进攻", "市场环境相对可用，可围绕主线做分歧低吸。"


def _stock_key(item):
    code = str((item or {}).get("code", "") or "").strip()
    name = str((item or {}).get("name", "") or "").strip()
    return code or f"name:{name}"


def normalize_final_plans(raw_plans):
    """Resolve all strategy signals into exactly one final layer per stock."""
    grouped = {}
    order = []
    for layer in FINAL_LAYERS:
        for item in (raw_plans or {}).get(layer, []) or []:
            key = _stock_key(item)
            if not key:
                continue
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            candidate = deepcopy(item)
            candidate["_source_layer"] = layer
            grouped[key].append(candidate)

    normalized = {layer: [] for layer in FINAL_LAYERS}
    for key in order:
        candidates = grouped[key]
        winner = max(
            candidates,
            key=lambda item: LAYER_PRIORITY.get(
                str(item.get("final_layer") or item.get("_source_layer") or ""),
                -1,
            ),
        )
        final_layer = str(winner.get("final_layer") or winner.get("_source_layer"))
        if final_layer not in normalized:
            final_layer = "只观察"

        strategies = []
        matched_layers = []
        for candidate in candidates:
            strategy = str(candidate.get("strategy", "") or "").strip()
            if strategy and strategy not in strategies:
                strategies.append(strategy)
            source_layer = str(candidate.get("final_layer") or candidate.get("_source_layer") or "")
            if source_layer and source_layer not in matched_layers:
                matched_layers.append(source_layer)

        result = {k: v for k, v in winner.items() if k != "_source_layer"}
        result["strategy"] = " / ".join(strategies)
        result["matched_strategies"] = strategies
        result["matched_layers"] = matched_layers
        result["final_layer"] = final_layer
        result["resolution_rule"] = RESOLUTION_RULE
        normalized[final_layer].append(result)
    return normalized


def build_daily_decision(market, restrictions, raw_plans):
    """Build the single decision object consumed by rendering and snapshots."""
    mode_code, mode_name, mode_summary = derive_trading_mode(market, restrictions)
    plans = normalize_final_plans(raw_plans)
    summary = {layer: len(plans[layer]) for layer in FINAL_LAYERS}
    executable_count = summary["候选低吸"]
    market_allows_trade = bool((restrictions or {}).get("allow_real_trade"))
    execution_allowed = market_allows_trade and executable_count > 0
    if execution_allowed:
        action_summary = mode_summary
    elif market_allows_trade:
        action_summary = f"{mode_summary} 当前没有满足条件的候选，继续等待。"
    else:
        action_summary = mode_summary
    return {
        "schema_version": DAILY_DECISION_SCHEMA_VERSION,
        "mode": {
            "code": mode_code,
            "name": mode_name,
            "summary": mode_summary,
        },
        "plans": plans,
        "summary": summary,
        "execution": {
            "market_allows_trade": market_allows_trade,
            "candidate_available": executable_count > 0,
            "executable_candidate_count": executable_count,
            "execution_allowed": execution_allowed,
            "summary": action_summary,
        },
        "raw_strategy_signal_count": sum(
            len((raw_plans or {}).get(layer, []) or []) for layer in FINAL_LAYERS
        ),
        "distinct_stock_count": sum(summary.values()),
        "resolution_rule": RESOLUTION_RULE,
    }
