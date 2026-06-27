"""
Central board/concept classification for report presentation.

This module is intentionally presentation-only. It does not change stock
selection, database mappings, or trading plans. It only decides where a board
name should be displayed and how repeated themes should be grouped.
"""
from dataclasses import dataclass

from analysis.board_alias import normalize_board_name


INDUSTRIAL = "industrial"
DYNAMIC_SENTIMENT = "dynamic_sentiment"
INDEX_STYLE = "index_style"
INSTITUTIONAL = "institutional"
ATTRIBUTE = "attribute"
PRICE = "price"
BROAD_LABEL = "broad_label"


@dataclass(frozen=True)
class BoardInfo:
    raw_name: str
    display_name: str
    category: str
    category_label: str
    cluster: str | None = None
    cluster_label: str | None = None


DYNAMIC_SENTIMENT_KEYWORDS = [
    "东方财富热股", "昨日涨停", "昨日首板", "昨日连板",
    "昨日高振幅", "昨日触板", "昨日炸板", "昨日换手",
    "最近多板", "近期新高", "近期强势", "百日新高", "历史新高",
    "趋势股",
]

INDEX_STYLE_KEYWORDS = [
    "HS300_", "上证180_", "中证500", "中盘成长", "权重股",
    "创业板综", "ST板块", "中盘股", "大盘股", "小盘股",
    "大盘价值", "大盘成长", "中盘价值", "中盘成长",
    "小盘价值", "小盘成长",
    "上证380", "上证180", "上证50",
    "深证100R", "深成500",
    "沪深300", "中证1000",
    "创业板指", "科创50",
]

INSTITUTIONAL_KEYWORDS = [
    "机构重仓", "QFII重仓", "融资融券", "MSCI中国", "富时罗素",
    "证金持股", "社保重仓", "基金重仓",
    "沪股通", "深股通", "陆股通", "北向资金",
    "标普道琼斯", "标准普尔", "转融券",
]

ATTRIBUTE_KEYWORDS = [
    "专精特新", "央企", "国企改革", "高送转", "预盈预增", "参股金融",
    "行业龙头", "龙头", "独角兽",
    "年报", "扭亏", "预亏", "预减", "业绩",
]

PRICE_ATTRIBUTE_KEYWORDS = [
    "百元股", "低价股", "高价股", "破净股",
]

BROAD_LABEL_KEYWORDS = [
    "题材股", "科技风格", "消费风格", "成长风格", "价值风格",
]


CATEGORY_LABELS = {
    DYNAMIC_SENTIMENT: "动态情绪",
    INDEX_STYLE: "指数/风格",
    INSTITUTIONAL: "资金属性",
    ATTRIBUTE: "属性标签",
    PRICE: "价格属性",
    BROAD_LABEL: "宽泛标签",
    INDUSTRIAL: "产业概念",
}


CLUSTER_ALIASES = [
    ("金融/券商", [
        "非银金融", "证券", "证券Ⅱ", "证券Ⅲ", "券商概念",
        "互联网金融", "多元金融", "保险", "银行",
    ]),
    ("半导体", [
        "半导体", "半导体概念", "国产芯片", "芯片概念",
        "集成电路", "集成电路封测", "先进封装", "存储芯片",
    ]),
    ("机器人", [
        "机器人", "机器人概念", "人形机器人", "减速器",
    ]),
    ("AI/算力", [
        "人工智能", "算力", "算力概念", "东数西算", "液冷服务器",
        "数据中心", "云计算", "服务器",
    ]),
    ("汽车链", [
        "车联网", "车联网(车路云)", "汽车零部件", "新能源汽车",
        "特斯拉概念", "无人驾驶", "智能驾驶",
    ]),
]

INDEX_STYLE_PATTERNS = [
    "成份", "成分", "创业成份", "创业板成份", "科创成份",
]

BROAD_LABEL_PATTERNS = [
    "风格",
]

CLUSTER_PATTERNS = [
    ("金融/券商", ["证券", "券商", "非银", "金融", "保险", "银行"]),
    ("半导体", ["半导体", "芯片", "中芯", "集成电路", "先进封装", "存储"]),
    ("机器人", ["机器人", "减速器"]),
    ("AI/算力", ["人工智能", "算力", "服务器", "数据中心", "云计算", "东数西算"]),
    ("汽车链", ["汽车", "车联网", "车路云", "新能源车", "特斯拉", "无人驾驶", "智能驾驶"]),
]


def classify_board(name: str) -> BoardInfo:
    raw = str(name or "").strip()
    display = normalize_board_name(raw)
    category = _category_for(display)
    cluster = get_board_cluster(display) if category == INDUSTRIAL else None
    return BoardInfo(
        raw_name=raw,
        display_name=display,
        category=category,
        category_label=CATEGORY_LABELS.get(category, "其他标签"),
        cluster=cluster,
        cluster_label=cluster,
    )


def _category_for(name: str) -> str:
    if not name:
        return INDUSTRIAL
    for kw in INDEX_STYLE_PATTERNS:
        if kw in name:
            return INDEX_STYLE
    for kw in BROAD_LABEL_PATTERNS:
        if kw in name:
            return BROAD_LABEL
    for kw in DYNAMIC_SENTIMENT_KEYWORDS:
        if kw in name:
            return DYNAMIC_SENTIMENT
    for kw in INDEX_STYLE_KEYWORDS:
        if kw in name:
            return INDEX_STYLE
    for kw in INSTITUTIONAL_KEYWORDS:
        if kw in name:
            return INSTITUTIONAL
    for kw in PRICE_ATTRIBUTE_KEYWORDS:
        if kw in name:
            return PRICE
    for kw in BROAD_LABEL_KEYWORDS:
        if kw in name:
            return BROAD_LABEL
    for kw in ATTRIBUTE_KEYWORDS:
        if kw in name:
            return ATTRIBUTE
    return INDUSTRIAL


def classify_concept_label(name: str) -> str:
    return classify_board(name).category


def label_category_name(category: str) -> str:
    return CATEGORY_LABELS.get(category, "其他标签")


def is_mainline_board(name: str) -> bool:
    return classify_board(name).category == INDUSTRIAL


def is_style_label(name: str) -> bool:
    return classify_board(name).category in {
        DYNAMIC_SENTIMENT, INDEX_STYLE, INSTITUTIONAL, ATTRIBUTE, PRICE, BROAD_LABEL
    }


def is_broad_label(name: str) -> bool:
    return classify_board(name).category == BROAD_LABEL


def get_board_cluster(name: str) -> str | None:
    display = normalize_board_name(str(name or "").strip())
    for cluster, aliases in CLUSTER_ALIASES:
        for alias in aliases:
            if alias == display or alias in display:
                return cluster
    for cluster, patterns in CLUSTER_PATTERNS:
        for pattern in patterns:
            if pattern in display:
                return cluster
    return display or None


def dedup_board_directions(items, limit=None):
    """
    Deduplicate board direction tuples by mainline cluster.

    items: iterable of (name, change)
    returns: list of (display_name, change), preserving the strongest absolute
    move per cluster after sorting by change descending.
    """
    best_by_cluster = {}
    order = []
    for name, change in items:
        info = classify_board(name)
        if info.category != INDUSTRIAL:
            continue
        cluster = info.cluster or info.display_name
        current = best_by_cluster.get(cluster)
        candidate = (cluster, change, info.display_name)
        if current is None:
            best_by_cluster[cluster] = candidate
            order.append(cluster)
        elif abs(change) > abs(current[1]):
            best_by_cluster[cluster] = candidate

    result = [(cluster, change) for cluster, change, _ in best_by_cluster.values()]
    result.sort(key=lambda x: x[1], reverse=True)
    return result[:limit] if limit else result


def explain_non_industrial_label(name: str, category: str | None = None) -> str:
    label_map = {
        "昨日高振幅": "短线波动增强，资金博弈激烈",
        "东方财富热股": "热门股成交占比变化",
        "最近多板": "连板/强势股活跃",
        "近期新高": "趋势新高股活跃",
        "百日新高": "中期趋势股活跃",
        "历史新高": "长期趋势股活跃",
        "趋势股": "趋势风格标签，不代表具体产业主线",
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
        "百元股": "高价股成交占比变化，不代表产业主线",
        "题材股": "宽泛交易标签，不代表具体产业主线",
        "科技风格": "风格标签，不代表具体产业主线",
        "专精特新": "专精特新属性股票成交占比变化",
        "国企改革": "国企改革属性股票成交占比变化",
        "央企": "央企属性股票成交占比变化",
        "预盈预增": "业绩预增属性股票成交占比变化",
        "2025年报扭亏": "财报事件标签，不代表产业主线",
        "ST板块": "ST板块成交占比变化",
    }
    if name in label_map:
        return label_map[name]
    cat = category or classify_board(name).category_label
    return f"{cat}，不作为产业主线"
