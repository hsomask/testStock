"""
小白指标解释模块
根据当天市场情况动态选择学习概念
"""
import random

EXPLAINERS = {
    "成交额": "成交额表示今天市场买卖股票的总金额，金额越大，说明市场越活跃。",
    "成交占比": "成交占比表示某个板块成交额占全市场成交额的比例。如果占比连续上升，说明资金越来越关注这个方向。",
    "量比": "量比表示今天成交量相对平时（近5日均量）是否放大。量比大于1说明比平时更活跃，量比远大于2.5说明异常放量。",
    "换手率": "换手率表示流通股份中有多少比例在今天被买卖。越高说明交易越活跃，但太高也可能代表分歧较大。",
    "MA5": "MA5是最近5个交易日的平均收盘价，用来观察短期趋势。股价站上MA5说明短期偏强。",
    "MA10": "MA10是最近10个交易日的平均收盘价，用来观察短中期趋势。",
    "MA20": "MA20是最近20个交易日的平均收盘价，用来观察中期趋势。",
    "均线多头排列": "当MA5 > MA10 > MA20时，称为多头排列，说明短期、中期趋势都向上。",
    "5日涨幅": "5日涨幅表示最近5个交易日累计涨跌幅，用来判断短期是否涨得过快。",
    "20日涨幅": "20日涨幅表示最近20个交易日累计涨跌幅。涨幅过大说明已经涨了不少，追高风险上升。",
    "板块联动": "板块联动表示不是单只股票孤立上涨，而是它所属的行业或概念也在一起走强。联动上涨比孤立上涨更可靠。",
    "情绪周期": "情绪周期描述市场从冷清（冰点）→ 回暖（平衡）→ 活跃（过热）→ 亢奋（高潮）→ 回落（退潮）的状态循环。",
    "涨停": "涨停表示股票当天涨到交易所规定的最大涨幅限制（主板10%，科创板/创业板20%）。",
    "跌停": "跌停表示股票当天跌到交易所规定的最大跌幅限制。跌停数量多说明市场亏钱效应强。",
    "市场情绪评分": "市场情绪评分综合了涨跌家数、涨停数量、成交额等，0-100分。分数越高，市场越活跃。",
    "主线": "主线是当天市场最关注的方向。主线明确时，相关股票更容易形成联动；主线不明确时，资金比较分散。",
    "参考压力位": "压力位是股价上涨可能遇到阻力的位置，由策略公式计算，不等于一定会到。",
    "风险失效位": "风险失效位是一个观察参考线。如果股价跌破这个位置，说明此前入选的逻辑可能已经变化。",
    "观察池": "观察池是基于数据规则筛选出的股票列表，用于复盘和学习，不是买入建议。",
    "成交占比变化": "成交占比连续3天或5天上升，说明资金持续流入该方向；连续下降则可能说明资金在撤离。",
}


def explain_indicator(name, value=None):
    """获取指标的小白解释，可附带当前数值"""
    base = EXPLAINERS.get(name, "")
    if not base:
        return ""
    if value is not None:
        return f"{base}（当前值：{value}）"
    return base


def explain_market_status(score):
    """根据情绪评分给出小白解释"""
    if score >= 75:
        return "市场很热，机会较多，但追高风险也明显上升。如果热门板块已经连续上涨，需要防止高位分歧。"
    elif score >= 60:
        return "市场整体偏强，可以观察主线方向，但仍要控制仓位，不要追涨过高的股票。"
    elif score >= 45:
        return "市场没有明显单边方向，板块轮动较快，适合多观察、少操作，不适合重仓。"
    elif score >= 30:
        return "市场偏弱，亏钱效应较明显，应减少进攻型操作，优先保护已有持仓。"
    else:
        return "市场风险较高，当前阶段优先学习和观察，不适合追高。等市场情绪回暖后再考虑进攻。"


def get_daily_learning_topics(market, industry, concept, sentiment, selectors):
    """
    根据当天市场情况动态选择 3-5 个学习概念。
    返回 [(概念名, 解释文本), ...]
    """
    candidates = []

    # 成交额放量 → 解释成交额
    if market.get("total_amount", 0) > 10000:
        candidates.append(("成交额", EXPLAINERS["成交额"]))

    # 涨停数量多 → 解释涨停
    if market.get("limit_up", 0) >= 80:
        candidates.append(("涨停", EXPLAINERS["涨停"]))

    # 跌停数量多 → 解释跌停
    if market.get("limit_down", 0) >= 30:
        candidates.append(("跌停", EXPLAINERS["跌停"]))

    # 市场活跃 → 解释情绪周期
    score = sentiment.get("score", 50)
    if score >= 70 or score <= 35:
        candidates.append(("情绪周期", EXPLAINERS["情绪周期"]))

    # 板块联动观察池有结果 → 解释板块联动
    board_linkage = selectors.get("板块联动")
    if board_linkage is not None and not board_linkage.empty:
        candidates.append(("板块联动", EXPLAINERS["板块联动"]))

    # 有观察池结果 → 解释观察池
    any_pool = any(
        v is not None and not (hasattr(v, 'empty') and v.empty)
        for v in selectors.values()
    )
    if any_pool:
        candidates.append(("观察池", EXPLAINERS["观察池"]))

    # 必选基础概念
    base = [
        ("市场情绪评分", EXPLAINERS["市场情绪评分"]),
        ("量比", EXPLAINERS["量比"]),
        ("均线多头排列", EXPLAINERS["均线多头排列"]),
    ]

    # 合并：基础概念 + 动态概念，去重，取 3-5 个
    seen = set()
    result = []
    for name, text in base + candidates:
        if name not in seen:
            seen.add(name)
            result.append((name, text))

    if len(result) > 5:
        result = result[:5]
    elif len(result) < 3:
        # 补充通用概念
        extras = [
            ("换手率", EXPLAINERS["换手率"]),
            ("MA5", EXPLAINERS["MA5"]),
            ("参考压力位", EXPLAINERS["参考压力位"]),
        ]
        for name, text in extras:
            if name not in seen and len(result) < 5:
                seen.add(name)
                result.append((name, text))

    return result
