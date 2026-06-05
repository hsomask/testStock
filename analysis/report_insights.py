"""
日报展示解释层（纯展示，不写库、不改选股、不调行情 API）
读取已有 daily_summary / report_context / trade_plan / market 数据，
产出弱市检查、赚钱效应、模式标签、明日验证清单等。
"""
import numpy as np

# ── 动态标签黑名单 ──
DYNAMIC_LABEL_BLACKLIST = {
    "东方财富热股", "昨日涨停", "昨日首板", "昨日连板",
    "昨日高振幅", "最近多板", "近期新高", "历史新高",
    "融资融券", "QFII重仓", "MSCI中国", "富时罗素",
    "创业板综", "中证500", "HS300_", "ST板块",
}


def is_dynamic_label(name):
    """检查板块名是否属于动态标签"""
    if not name:
        return False
    for kw in DYNAMIC_LABEL_BLACKLIST:
        if kw in name:
            return True
    return False


def filter_effective_themes(themes):
    """从主题列表中分离有效主线和动态标签"""
    effective = []
    dynamic = []
    for t in (themes or []):
        name = t.get("name", "")
        if is_dynamic_label(name):
            dynamic.append(t)
        else:
            effective.append(t)
    return effective, dynamic


# ── 弱市不做检查 ──

def check_weak_market(market):
    """
    弱市不做检查。返回 (triggers, total_checked, items)
    当前可检查项：绿盘占比、涨跌停比。其余项数据不足。
    """
    up = market.get("up_count", 0)
    down = market.get("down_count", 0)
    flat = market.get("flat_count", 0)
    limit_up = market.get("limit_up", 0)
    limit_down = max(market.get("limit_down", 0), 1)

    items = []

    # 1. 绿盘占比 > 60%
    total = up + down + flat
    if total > 0:
        green_ratio = down / total
        triggered = green_ratio > 0.6
        items.append({
            "name": "绿盘占比 > 60%",
            "value": f"{green_ratio:.1%}",
            "triggered": triggered,
            "status": "checked",
            "note": "多数个股下跌" if triggered else "宽度正常",
        })
    else:
        items.append({"name": "绿盘占比 > 60%", "value": "N/A", "triggered": False,
                       "status": "insufficient", "note": "数据不足"})

    # 2. 涨跌停比 < 1
    ratio = limit_up / limit_down
    triggered = ratio < 1
    items.append({
        "name": "涨跌停比 < 1",
        "value": f"{ratio:.1f}",
        "triggered": triggered,
        "status": "checked",
        "note": "跌停压过涨停" if triggered else "涨停多于跌停",
    })

    # 3-5. 数据不足
    for name in ["昨涨停今表现差", "3板以上稀少", "量能持续萎缩"]:
        items.append({
            "name": name, "value": "N/A", "triggered": False,
            "status": "insufficient", "note": "当前数据源未覆盖",
        })

    triggers = sum(1 for it in items if it["triggered"])
    checked = sum(1 for it in items if it["status"] == "checked")
    return triggers, checked, items


def weak_market_conclusion(triggers, checked):
    """弱市不做结论"""
    if checked < 2:
        return "检查项不足，无法判断"
    if triggers <= 1:
        return "非典型弱市，可正常观察"
    elif triggers == 2:
        return "结构分化，轻仓观察"
    else:
        return "偏弱，谨慎或极轻仓"


# ── 赚钱效应降级判断 ──

def assess_profit_effect(market):
    """
    基于绿盘占比、涨跌比、涨跌停比做降级定性判断。
    由于缺少昨日涨停表现、连板高度、炸板率，本结论为降级判断。
    """
    up = market.get("up_count", 0)
    down = max(market.get("down_count", 0), 1)
    limit_up = market.get("limit_up", 0)
    limit_down = max(market.get("limit_down", 0), 1)
    flat = market.get("flat_count", 0)
    total = up + down + flat

    adv_ratio = up / down  # 涨跌比
    lb_ratio = limit_up / limit_down  # 涨跌停比
    green_ratio = down / total if total > 0 else 0

    # 综合判断
    if adv_ratio > 1.2 and lb_ratio > 3:
        level = "尚可"
        detail = "涨跌比和涨跌停比显示短线仍有赚钱效应，但集中在少数方向。"
    elif adv_ratio < 0.5 or lb_ratio < 1:
        level = "弱"
        detail = "涨跌比偏弱或跌停压过涨停，追涨风险较高。"
    elif green_ratio > 0.6:
        level = "分化"
        detail = "少数主线赚钱，但多数个股承压，赚钱效应不普遍。"
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


# ── 市场宽度指标 ──

def compute_market_width(market):
    """计算绿盘占比、涨跌比、涨跌停比"""
    up = market.get("up_count", 0)
    down = max(market.get("down_count", 0), 1)
    flat = market.get("flat_count", 0)
    limit_up = market.get("limit_up", 0)
    limit_down = max(market.get("limit_down", 0), 1)
    total = up + down + flat

    return {
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "adv_ratio": up / down,
        "lb_ratio": limit_up / limit_down,
        "green_ratio": down / total if total > 0 else 0,
    }


# ── 交易环境判断 ──

def assess_trading_environment(market, sentiment, trade_plan, profit_effect):
    """综合交易环境判断"""
    r = trade_plan.get("market_restrictions", {}) if trade_plan else {}
    return {
        "profit_effect": profit_effect["level"],
        "weak_market_triggers": None,  # 由调用方填入
        "market_volume": "放量" if market.get("total_amount", 0) > 0 else "N/A",
        "theme_concentration": "集中" if not profit_effect.get("green_ratio", 0) > 0.6 else "分化",
        "position_cap": f"{r.get('max_position_pct', 0)}成",
        "single_stock_cap": f"{r.get('single_stock_pct', 0)}成",
        "allow_trade": r.get("allow_real_trade", True),
    }


# ── 模式标签 ──

def assign_pattern_tag(stock, pool_name, market, themes):
    """
    给观察池个股分配模式标签（轻量判断，不改变股票池）。
    返回标签字符串。
    """
    risk = str(stock.get("risk_level", "")).strip()
    action = str(stock.get("action_signal", "")).strip()
    pct = safe_float(stock.get("pct_chg", 0))
    name = str(stock.get("name", ""))

    # 高风险复盘
    if risk == "高" or action == "回避":
        return "高风险复盘"

    # 龙回头候选：前期强势（20日涨幅>30%）+ 短期回调（5日涨幅<0 或 当日涨幅偏小）
    pct_20d = safe_float(stock.get("pct_20d", np.nan))
    pct_5d = safe_float(stock.get("pct_5d", np.nan))
    if pd_notna(pct_20d) and pd_notna(pct_5d):
        if pct_20d > 30 and pct_5d < 3:
            return "龙回头候选"

    # 龙头确认：当日涨幅>5% + 板块属于有效主线
    if pct > 5 and themes:
        for t in themes:
            if not is_dynamic_label(t.get("name", "")):
                # 简单判断：股票在主线板块范围内
                return "板块龙头"

    # 守株待兔候选：缩量回调
    vol_ratio = safe_float(stock.get("volume_ratio", np.nan))
    if pd_notna(vol_ratio) and pd_notna(pct_5d):
        if vol_ratio < 0.7 and pct_5d < 0:
            return "守株待兔候选"

    return "待确认"


def safe_float(val):
    try:
        v = float(val)
        return v if not np.isnan(v) else None
    except (TypeError, ValueError):
        return None


def pd_notna(val):
    return val is not None


# ── 明日验证清单 ──

def generate_validation_checklist(market, themes, profit_effect, weak_triggers):
    """基于今日判断生成 3-5 条明日验证问题"""
    items = []
    effective, _ = filter_effective_themes(themes)

    # 主线是否能延续
    if effective:
        main_names = "、".join(t["name"] for t in effective[:2])
        items.append(f"{main_names} 能否继续承接")

    # 市场宽度能否修复
    width = compute_market_width(market)
    if width["green_ratio"] > 0.6:
        items.append("市场宽度能否修复（绿盘占比降至 60% 以下）")

    # 今日强势股是否出现亏钱效应
    if market.get("limit_up", 0) > 50:
        items.append("今日强势股是否出现亏钱效应")

    # 高风险层是否继续强于可观察层（evaluation 关联）
    items.append("高风险复盘层是否继续强于可观察层")

    # 资源/高潮板块是否回落
    items.append("高潮板块是否出现回落")

    # 最多 5 条
    return items[:5]


# ── 情绪阶段解释 ──

def explain_sentiment_stage(score, stage):
    """根据评分和阶段生成解释文本"""
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


# ── 仓位冲突检查 ──

def validate_position_consistency(trade_plan):
    """检查日报中仓位是否与 trade_plan 一致"""
    if not trade_plan:
        return {"ok": True, "max_pct": 0, "single_pct": 0}
    r = trade_plan.get("market_restrictions", {})
    return {
        "ok": True,
        "max_pct": r.get("max_position_pct", 0),
        "single_pct": r.get("single_stock_pct", 0),
    }
