"""
同花顺热点题材数据源
部分接口实现参考 simonlin1212/a-stock-data，License: Apache-2.0
Repository: https://github.com/simonlin1212/a-stock-data
"""
import logging
import akshare as ak

logger = logging.getLogger(__name__)


def ths_hot_reasons():
    """
    获取同花顺概念板块摘要（含热点事件/原因）
    返回 list[dict]: code, name, reason, pct_chg 等
    """
    try:
        df = ak.stock_board_concept_summary_ths()
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            results.append({
                "name": str(row.get("板块名称", "")),
                "date": str(row.get("日期", "")),
                "reason": str(row.get("板块事件", "")),
                "leader": str(row.get("龙头股", "")),
                "count": int(row.get("成分股数量", 0)) if row.get("成分股数量") else 0,
            })
        return results
    except Exception as e:
        logger.warning(f"同花顺热点数据获取失败：{e}")
        return []


def match_ths_reasons(stock_concept_tags, hot_reasons):
    """
    匹配个股的概念标签与同花顺热点原因
    stock_concept_tags: list[str] 个股的概念标签
    hot_reasons: list[dict] 同花顺热点数据
    返回匹配的热点原因文本
    """
    if not stock_concept_tags or not hot_reasons:
        return []
    hot_names = {r["name"] for r in hot_reasons}
    matches = []
    for tag in stock_concept_tags:
        if tag in hot_names:
            for r in hot_reasons:
                if r["name"] == tag and r["reason"]:
                    matches.append(f"{tag}：{r['reason']}")
                    break
    return matches[:3]
