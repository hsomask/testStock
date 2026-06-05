"""
Presentation-only helpers for daily report rendering.

This module must not:
- mutate database records
- change stock selection
- change trade_plan
- call market data APIs
- write evaluation results
"""
import numpy as np

# ═══════════════════════════════════════════
# 概念标签分流
# ═══════════════════════════════════════════

DYNAMIC_SENTIMENT_KEYWORDS = [
    "东方财富热股", "昨日涨停", "昨日首板", "昨日连板",
    "昨日高振幅", "最近多板", "近期新高", "百日新高", "历史新高",
]

INDEX_STYLE_KEYWORDS = [
    "HS300_", "上证180_", "中证500", "中盘成长", "权重股",
    "创业板综", "ST板块",
]

INSTITUTIONAL_KEYWORDS = [
    "机构重仓", "QFII重仓", "融资融券", "MSCI中国", "富时罗素",
]


def classify_concept_label(name):
    """将概念名称分为: industrial / dynamic_sentiment / index_style / institutional"""
    if not name:
        return "industrial"
    for kw in DYNAMIC_SENTIMENT_KEYWORDS:
        if kw in name:
            return "dynamic_sentiment"
    for kw in INDEX_STYLE_KEYWORDS:
        if kw in name:
            return "index_style"
    for kw in INSTITUTIONAL_KEYWORDS:
        if kw in name:
            return "institutional"
    return "industrial"


def is_dynamic_label(name):
    """检查板块名是否属于动态/风格/机构标签（旧接口，保持兼容）"""
    return classify_concept_label(name) != "industrial"


def split_board_names(concepts, sort_by_change=True):
    """
    将概念板块名称列表分为产业概念和非产业标签。
    返回 (industrial, non_industrial)
    """
    industrial = []
    non_industrial = []
    for name, change_val in concepts:
        cat = classify_concept_label(name)
        if cat == "industrial":
            industrial.append((name, change_val))
        else:
            cat_label = {"dynamic_sentiment": "动态情绪", "index_style": "指数/风格", "institutional": "资金/机构"}.get(cat, "其他")
            non_industrial.append((name, change_val, cat_label))

    if sort_by_change:
        industrial.sort(key=lambda x: x[1], reverse=True)
        non_industrial.sort(key=lambda x: abs(x[1]), reverse=True)
    return industrial, non_industrial


def filter_effective_themes(themes):
    """从主题列表中分离有效主线和动态标签"""
    effective = []
    dynamic = []
    for t in (themes or []):
        name = t.get("name", "")
        if classify_concept_label(name) != "industrial":
            dynamic.append(t)
        else:
            effective.append(t)
    return effective, dynamic


# ═══════════════════════════════════════════
# 弱市不做检查
# ═══════════════════════════════════════════

def check_weak_market(market):
    """弱市不做检查。返回 (triggers, checked, items, green_ratio, lb_ratio)"""
    up = market.get("up_count", 0)
    down = market.get("down_count", 0)
    flat = market.get("flat_count", 0)
    limit_up = market.get("limit_up", 0)
    limit_down = max(market.get("limit_down", 0), 1)
    total = up + down + flat

    items = []
    green_ratio = down / total if total > 0 else 0
    lb_ratio = limit_up / limit_down

    # 可计算项 1
    if total > 0:
        triggered = green_ratio > 0.6
        items.append({"name": "绿盘占比 > 60%", "value": f"{green_ratio:.1%}",
                       "triggered": triggered, "status": "checked",
                       "note": "多数个股下跌" if triggered else "宽度正常"})
    else:
        items.append({"name": "绿盘占比 > 60%", "value": "N/A", "triggered": False,
                       "status": "insufficient", "note": "数据不足"})

    # 可计算项 2
    triggered = lb_ratio < 1
    items.append({"name": "涨跌停比 < 1", "value": f"{lb_ratio:.1f}",
                   "triggered": triggered, "status": "checked",
                   "note": "跌停压过涨停" if triggered else "涨停多于跌停"})

    # 数据不足项
    for name in ["昨涨停今表现差", "3板以上稀少", "量能持续萎缩"]:
        items.append({"name": name, "value": "N/A", "triggered": False,
                       "status": "insufficient", "note": "当前数据源未覆盖"})

    triggers = sum(1 for it in items if it["triggered"])
    checked = sum(1 for it in items if it["status"] == "checked")
    return triggers, checked, items, green_ratio, lb_ratio


def weak_market_conclusion(triggers, checked, green_ratio, lb_ratio):
    """弱市不做结论 — 更直观表达"""
    if checked < 2:
        return "部分触发", "检查项不足，无法完整判断"
    if green_ratio > 0.7 and lb_ratio <= 1:
        return "弱市信号较强", "原则上只观察或极轻仓"
    if green_ratio > 0.6 and lb_ratio > 3:
        return "部分触发", "不是全面弱市，而是结构分化；只看核心方向，不普买"
    if triggers <= 1:
        return "未触发明显弱市", "可正常观察"
    return "部分触发", "结构分化，轻仓观察"


# ═══════════════════════════════════════════
# 赚钱效应（口径不冲突）
# ═══════════════════════════════════════════

def assess_profit_effect(market):
    """赚钱效应判断 — 避免与情绪阶段口径冲突"""
    up = market.get("up_count", 0)
    down = max(market.get("down_count", 0), 1)
    limit_up = market.get("limit_up", 0)
    limit_down = max(market.get("limit_down", 0), 1)
    flat = market.get("flat_count", 0)
    total = up + down + flat

    adv_ratio = up / down
    lb_ratio = limit_up / limit_down
    green_ratio = down / total if total > 0 else 0

    if lb_ratio > 3 and green_ratio > 0.6:
        level = "分化偏弱"
        detail = "涨停家数和涨跌停比显示短线仍活跃，但绿盘占比高、涨跌比偏弱，说明赚钱效应集中在少数方向，多数个股亏钱。"
    elif lb_ratio > 3 and green_ratio <= 0.6:
        level = "尚可/活跃"
        detail = "涨跌停比显示短线活跃，市场宽度正常。"
    elif lb_ratio <= 1:
        level = "弱"
        detail = "跌停压过涨停，短线亏钱效应明显。"
    elif adv_ratio < 0.5 and green_ratio > 0.7:
        level = "分化偏弱"
        detail = "涨跌比和绿盘占比显示市场宽度明显偏弱，亏钱效应较为普遍。"
    else:
        level = "尚可"
        detail = "短线宽度正常，但缺少连板高度和炸板率数据，无法完整评估。"

    return {
        "level": level,
        "detail": detail,
        "downgraded": True,
        "note": "由于缺少昨日涨停表现、连板高度、炸板率，本结论为降级判断。",
        "adv_ratio": adv_ratio,
        "lb_ratio": lb_ratio,
        "green_ratio": green_ratio,
    }


# ═══════════════════════════════════════════
# 市场宽度指标
# ═══════════════════════════════════════════

def compute_market_width(market):
    """计算绿盘占比、涨跌比、涨跌停比"""
    up = market.get("up_count", 0)
    down = max(market.get("down_count", 0), 1)
    flat = market.get("flat_count", 0)
    limit_up = market.get("limit_up", 0)
    limit_down = max(market.get("limit_down", 0), 1)
    total = up + down + flat
    return {
        "up_count": up, "down_count": down, "flat_count": flat,
        "limit_up": limit_up, "limit_down": limit_down,
        "adv_ratio": up / down,
        "lb_ratio": limit_up / limit_down,
        "green_ratio": down / total if total > 0 else 0,
    }


# ═══════════════════════════════════════════
# 交易环境判断
# ═══════════════════════════════════════════

def assess_trading_environment(market, sentiment, trade_plan, profit_effect):
    """综合交易环境判断"""
    r = trade_plan.get("market_restrictions", {}) if trade_plan else {}
    return {
        "profit_effect": profit_effect["level"],
        "weak_market_triggers": None,
        "market_volume": f"{market.get('total_amount', 0):.0f}亿" if market.get("total_amount") else "N/A",
        "position_cap": f"{r.get('max_position_pct', 0)}成",
        "single_stock_cap": f"{r.get('single_stock_pct', 0)}成",
        "allow_trade": r.get("allow_real_trade", True),
    }


# ═══════════════════════════════════════════
# 模式标签（降级版）
# ═══════════════════════════════════════════

def assign_pattern_tag(stock, pool_name, market, themes):
    """
    给观察池个股分配模式标签（保守版）。
    只使用 high-confidence 标签，默认"待确认"。
    """
    risk = str(stock.get("risk_level", "")).strip()
    action = str(stock.get("action_signal", "")).strip()

    # 高风险复盘
    if risk in ("高", "高风险") or action in ("回避",):
        return "高风险复盘"

    # 强势回调候选：N字异动/二次起爆/短线强势 + 有回调迹象
    strategy = str(stock.get("strategy", "")).strip()
    pct = safe_float(stock.get("pct_chg", 0))
    pct_5d = safe_float(stock.get("pct_5d", np.nan))
    if strategy in ("N字异动", "二次起爆", "短线强势"):
        if pd_notna(pct_5d) and pct_5d < 3:
            return "强势回调候选"

    # 龙回头待确认：前期大涨 + 近期明显回调
    pct_20d = safe_float(stock.get("pct_20d", np.nan))
    if pd_notna(pct_20d) and pd_notna(pct_5d):
        if pct_20d > 30 and pct_5d < -5:
            return "龙回头待确认"

    # 板块龙头：涨幅>5% + 属于有效主线
    if pct is not None and pct > 5 and themes:
        for t in themes:
            if classify_concept_label(t.get("name", "")) == "industrial":
                return "板块龙头"

    return "待确认"


def safe_float(val):
    try:
        v = float(val)
        return v if not np.isnan(v) else None
    except (TypeError, ValueError):
        return None


def pd_notna(val):
    return val is not None


# ═══════════════════════════════════════════
# 观察池展示去重
# ═══════════════════════════════════════════

def dedup_watchlist_entries(entries):
    """
    观察池展示层去重。
    entries: list of {"code": str, "pool": str, "row": Series, "layer": str}
    返回去重后的 entries，同一 code 只保留一次（优先高风险层级）。
    """
    layer_priority = {"高风险复盘": 3, "谨慎观察": 2, "可观察": 1}
    seen = {}

    for e in entries:
        code = str(e.get("code", "")).strip()
        name = str(e.get("row", {}).get("name", ""))
        key = code if code else name
        if not key:
            continue

        if key in seen:
            existing = seen[key]
            # 合并策略来源
            new_pool = f"{existing['pool']} / {e['pool']}" if e["pool"] not in existing["pool"] else existing["pool"]
            existing["pool"] = new_pool
            # 取更保守层级
            existing_pri = layer_priority.get(existing.get("layer", ""), 0)
            current_pri = layer_priority.get(e.get("layer", ""), 0)
            if current_pri > existing_pri:
                existing["layer"] = e["layer"]
                existing["row"] = e["row"]
        else:
            seen[key] = dict(e)

    return list(seen.values())


# ═══════════════════════════════════════════
# 明日验证清单
# ═══════════════════════════════════════════

def generate_validation_checklist(market, themes, profit_effect, weak_triggers):
    """基于今日判断生成 3-5 条明日验证问题"""
    items = []
    effective, _ = filter_effective_themes(themes)
    width = compute_market_width(market)

    if effective:
        items.append(f"{'、'.join(t['name'] for t in effective[:2])} 能否继续承接")
    if width["green_ratio"] > 0.6:
        items.append("市场宽度能否修复（绿盘占比降至 60% 以下）")
    if market.get("limit_up", 0) > 50:
        items.append("今日强势股是否出现亏钱效应")
    items.append("高风险复盘层是否继续强于可观察层")
    items.append("高潮板块是否出现回落")
    return items[:5]


# ═══════════════════════════════════════════
# 情绪阶段解释
# ═══════════════════════════════════════════

def explain_sentiment_stage(score, stage):
    if not stage:
        if score >= 80:
            stage = "高潮"
        elif score >= 65:
            stage = "过热"
        elif score >= 50:
            stage = "升温"
        elif score >= 35:
            stage = "平衡/分歧"
        elif score >= 20:
            stage = "退潮"
        else:
            stage = "冰点"

    stage_map = {
        "高潮": "市场情绪偏高，需警惕高潮后回落",
        "过热": "情绪偏热，建议控制仓位",
        "升温": "短线赚钱效应正在扩散，可适度参与主线",
        "平衡": "市场处于分歧阶段，方向不明确，轻仓观察",
        "分歧": "市场处于分歧阶段，方向不明确，轻仓观察",
        "退潮": "赚钱效应减弱，建议降低仓位",
        "冰点": "市场情绪极度低迷，等待情绪修复",
    }
    return stage, stage_map.get(stage, "数据不足，无法判断")


def validate_position_consistency(trade_plan):
    if not trade_plan:
        return {"ok": True, "max_pct": 0, "single_pct": 0}
    r = trade_plan.get("market_restrictions", {})
    return {"ok": True, "max_pct": r.get("max_position_pct", 0),
            "single_pct": r.get("single_stock_pct", 0)}

