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
    "昨日高振幅", "昨日触板", "昨日炸板", "昨日换手",
    "最近多板", "近期新高", "近期强势", "百日新高", "历史新高",
]

INDEX_STYLE_KEYWORDS = [
    "HS300_", "上证180_", "中证500", "中盘成长", "权重股",
    "创业板综", "ST板块", "中盘股", "大盘股", "小盘股",
    "大盘价值", "大盘成长", "中盘价值", "中盘成长",
    "小盘价值", "小盘成长",
    "上证380", "上证180", "上证50",
    "深证100R", "深成500",
    "沪深300", "中证500", "中证1000",
    "创业板综", "创业板指", "科创50",
]

INSTITUTIONAL_KEYWORDS = [
    "机构重仓", "QFII重仓", "融资融券", "MSCI中国", "富时罗素",
    "证金持股", "社保重仓", "基金重仓",
    "沪股通", "深股通", "陆股通", "北向资金",
    "标普道琼斯", "转融券",
]

ATTRIBUTE_KEYWORDS = [
    "专精特新", "央企", "国企改革", "高送转", "预盈预增", "参股金融",
    "行业龙头", "龙头", "独角兽",
]

PRICE_ATTRIBUTE_KEYWORDS = [
    "百元股", "低价股", "高价股", "破净股",
]


def classify_concept_label(name):
    """将概念名称分为: industrial / dynamic_sentiment / index_style / institutional / attribute / price / other"""
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
    for kw in ATTRIBUTE_KEYWORDS:
        if kw in name:
            return "attribute"
    for kw in PRICE_ATTRIBUTE_KEYWORDS:
        if kw in name:
            return "price"
    return "industrial"


def is_industrial_theme(name):
    """是否为产业概念（可进入主线）"""
    return classify_concept_label(name) == "industrial"


def is_non_industrial_label(name):
    """是否为非产业标签（不可进入主线/产业概念表/退潮/机会/风险）"""
    return classify_concept_label(name) != "industrial"


def is_dynamic_label(name):
    """检查板块名是否不属于产业概念"""
    return classify_concept_label(name) != "industrial"


def label_category_name(cat):
    """分类标签 → 中文名"""
    return {
        "dynamic_sentiment": "动态情绪",
        "index_style": "指数/风格",
        "institutional": "资金属性",
        "attribute": "属性标签",
        "price": "价格属性",
        "industrial": "产业概念",
    }.get(cat, "其他标签")


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

    limitup_stats = market.get("limitup_stats") or {}
    if limitup_stats.get("status") == "ok" and limitup_stats.get("yesterday_limit_up_avg_return") is not None:
        avg_return = float(limitup_stats.get("yesterday_limit_up_avg_return") or 0)
        triggered = avg_return < 0
        items.append({"name": "昨涨停今表现差", "value": f"{avg_return:+.2f}%",
                       "triggered": triggered, "status": "checked",
                       "note": "昨日涨停池转弱" if triggered else "昨日涨停池表现尚可"})
    else:
        note = "缺少前一交易日涨停池" if limitup_stats.get("status") == "ok" else "涨停生态日表未生成"
        items.append({"name": "昨涨停今表现差", "value": "未生成", "triggered": False,
                       "status": "insufficient", "note": note})

    if limitup_stats.get("status") == "ok" and limitup_stats.get("three_board_plus_count") is not None:
        three_count = int(limitup_stats.get("three_board_plus_count") or 0)
        triggered = three_count == 0
        items.append({"name": "3板以上稀少", "value": f"{three_count}只",
                       "triggered": triggered, "status": "checked",
                       "note": "高标梯队断层" if triggered else "高标梯队仍在"})
    else:
        note = "缺少前一交易日涨停池" if limitup_stats.get("status") == "ok" else "涨停生态日表未生成"
        items.append({"name": "3板以上稀少", "value": "未生成", "triggered": False,
                       "status": "insufficient", "note": note})

    items.append({"name": "量能持续萎缩", "value": "N/A", "triggered": False,
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
        detail = "短线宽度正常。"

    limitup_stats = market.get("limitup_stats") or {}
    limitup_metrics = market.get("limitup_metrics") or {}
    has_failed_rate = (
        limitup_stats.get("status") == "ok"
        and limitup_stats.get("failed_limit_up_rate") is not None
    ) or (
        limitup_metrics.get("data_status") == "ok"
        and limitup_metrics.get("failed_limit_up_rate") is not None
    )
    has_consecutive = (
        limitup_stats.get("status") == "ok"
        and limitup_stats.get("max_consecutive_limit_up") is not None
    )
    has_yesterday = (
        limitup_stats.get("status") == "ok"
        and limitup_stats.get("yesterday_limit_up_avg_return") is not None
    )

    missing = []
    if not has_yesterday:
        missing.append("昨日涨停表现")
    if not has_consecutive:
        missing.append("连板高度")
    if not has_failed_rate:
        missing.append("炸板率")
    downgraded = bool(missing)
    note = f"由于缺少{'、'.join(missing)}，本结论为降级判断。" if missing else ""

    return {
        "level": level,
        "detail": detail,
        "downgraded": downgraded,
        "note": note,
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

    # 主线相关：涨幅>5% + 属于有效主线
    if pct is not None and pct > 5 and themes:
        for t in themes:
            if classify_concept_label(t.get("name", "")) == "industrial":
                return "主线相关"

    return "待确认"


def assign_stock_role(stock, pool_name, market, themes):
    """
    给日报展示用的个股角色标签。
    仅用于解释，不改变选股、分层或 trade_plan。
    """
    risk = str(stock.get("risk_level", "")).strip()
    action = str(stock.get("action_signal", "")).strip()
    strategy = str(stock.get("strategy", pool_name or "")).strip()
    pct = safe_float(stock.get("pct_chg", 0))
    pct_5d = safe_float(stock.get("pct_5d", np.nan))
    pct_20d = safe_float(stock.get("pct_20d", np.nan))

    if risk in ("高", "高风险") or action in ("回避",):
        return "高风险回避"

    theme_names = [str(t.get("name", "")) for t in (themes or []) if t.get("name")]
    has_effective_theme = bool(theme_names)

    if pd_notna(pct_20d) and pct_20d >= 50:
        return "中位风险"
    if pd_notna(pct_5d) and pct_5d >= 20:
        return "短线偏高"

    if has_effective_theme:
        if strategy in ("板块联动", "滚雪球趋势", "二次起爆"):
            return "主线核心"
        if pd_notna(pct_20d) and pct_20d < 25:
            return "低位补涨"
        return "跟风套利"

    if strategy in ("N字异动", "短线强势", "二次起爆"):
        return "独立观察"

    if pd_notna(pct) and pct >= 7:
        return "独立强势"

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
        names = [t["name"] for t in effective[:3] if t.get("name")]
        items.append(f"{'、'.join(names)} 能否继续承接")
    if width["green_ratio"] > 0.6:
        items.append("市场宽度能否修复（绿盘占比降至 60% 以下）")
    if market.get("limit_up", 0) > 50:
        items.append("今日强势股是否出现亏钱效应")
    if profit_effect.get("downgraded"):
        items.append("缺失的赚钱效应指标能否补齐，避免降级判断")
    items.append("观察池分层是否继续有效（候选低吸强于只观察/高风险）")
    if market.get("limit_up", 0) > 80 or market.get("score", 0) >= 75:
        items.append("高潮方向是否出现冲高回落或炸板扩散")
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


def explain_non_industrial_label(name, category):
    """按标签类型生成个性化解释"""
    label_map = {
        "昨日高振幅": "短线波动增强，资金博弈激烈",
        "东方财富热股": "热门股成交占比变化",
        "最近多板": "连板/强势股活跃",
        "近期新高": "趋势新高股活跃",
        "百日新高": "中期趋势股活跃",
        "历史新高": "长期趋势股活跃",
        "昨日涨停": "涨停股延续活跃",
        "昨日首板": "首板股延续活跃",
        "昨日连板": "连板接力情绪活跃",
        "中盘股": "中盘风格成交占比变化",
        "大盘股": "大盘风格成交占比变化",
        "小盘股": "小盘风格成交占比变化",
        "大盘价值": "价值风格成交占比变化",
        "大盘成长": "大盘成长风格变化",
        "中盘成长": "中盘成长风格变化",
        "权重股": "权重股成交占比变化",
        "机构重仓": "机构属性股票成交占比变化",
        "证金持股": "证金/国家队属性股票成交占比变化",
        "基金重仓": "基金重仓股成交占比变化",
        "社保重仓": "社保重仓股成交占比变化",
        "融资融券": "两融标的成交占比变化",
        "MSCI中国": "外资指数成分股成交占比变化",
        "富时罗素": "外资指数成分股成交占比变化",
        "HS300_": "沪深300成分股成交占比变化",
        "上证180_": "上证180成分股成交占比变化",
        "中证500": "中证500成分股成交占比变化",
        "创业板综": "创业板相关成分股成交占比变化",
        "专精特新": "专精特新属性股票成交占比变化",
        "国企改革": "国企改革属性股票成交占比变化",
        "央企": "央企属性股票成交占比变化",
        "预盈预增": "业绩预增属性股票成交占比变化",
        "ST板块": "ST板块成交占比变化",
    }
    if name in label_map:
        return label_map[name]
    return f"{category}，不作为产业主线"


def validate_position_consistency(trade_plan):
    if not trade_plan:
        return {"ok": True, "max_pct": 0, "single_pct": 0}
    r = trade_plan.get("market_restrictions", {})
    return {"ok": True, "max_pct": r.get("max_position_pct", 0),
            "single_pct": r.get("single_stock_pct", 0)}
