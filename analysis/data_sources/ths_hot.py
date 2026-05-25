"""
同花顺热点题材数据源
部分接口实现参考 simonlin1212/a-stock-data，License: Apache-2.0
Repository: https://github.com/simonlin1212/a-stock-data
"""
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)


def _session():
    s = requests.Session()
    s.trust_env = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.10jqka.com.cn/",
    })
    return s


def ths_hot_reasons_by_stock(date=None):
    """
    获取同花顺当日强势股 + 题材归因（股票级）
    date: YYYYMMDD 或 YYYY-MM-DD，默认今天
    返回 list[dict]: code, name, reason
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    date = str(date).replace("-", "")

    try:
        s = _session()
        url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/"
        r = s.get(url, timeout=15)
        r.encoding = "GBK"
        data = r.json()

        if data.get("errocode") != 0:
            logger.debug(f"同花顺热点接口返回异常：{data.get('errormsg', '')}")
            return []

        results = []
        for item in data.get("data", []):
            code = str(item.get("code", "")).zfill(6)
            if not code or code == "000000":
                continue
            results.append({
                "code": code,
                "name": str(item.get("name", "")),
                "reason": str(item.get("reason", "")),
            })
        return results
    except Exception as e:
        logger.warning(f"同花顺热点数据获取失败：{e}")
        return []


def ths_hot_reasons():
    """获取同花顺概念板块摘要（保留，概念级）"""
    try:
        import akshare as ak
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
            })
        return results
    except Exception as e:
        logger.warning(f"同花顺概念摘要获取失败：{e}")
        return []
