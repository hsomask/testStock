import pandas as pd
import numpy as np
from datetime import datetime
import akshare as ak
import logging

from analysis.utils import safe_numeric

logger = logging.getLogger(__name__)

# ── 数据源通道选择 ──
# AkShare 内部封装了多个数据源，不同通道字段有差异
# 优先级：东方财富(EM) > 新浪(Sina) > 同花顺(THS) > 腾讯(TX)

# 当前数据源可用状态（运行时动态检测）
_SOURCE_STATUS = {
    "eastmoney": None,  # None=未检测, True=可用, False=不可用
    "sina": None,
    "ths": None,
    "tencent": None,
}


def _check_eastmoney():
    """检测东方财富数据源是否可用"""
    if _SOURCE_STATUS["eastmoney"] is not None:
        return _SOURCE_STATUS["eastmoney"]
    try:
        import requests as _req
        s = _req.Session()
        s.trust_env = False
        s.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        })
        r = s.get(
            "https://push2delay.eastmoney.com/api/qt/clist/get",
            params={"pn": "1", "pz": "10", "po": "1", "np": "1", "fltt": "2", "invt": "2",
                    "fid": "f3", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                    "fields": "f12,f14"},
            timeout=15
        )
        data = r.json()
        _SOURCE_STATUS["eastmoney"] = data.get("data", {}).get("total", 0) > 100
    except Exception:
        _SOURCE_STATUS["eastmoney"] = False
    logger.info(f"EastMoney source: {'OK' if _SOURCE_STATUS['eastmoney'] else 'DOWN'}")
    return _SOURCE_STATUS["eastmoney"]


def _check_sina():
    if _SOURCE_STATUS["sina"] is not None:
        return _SOURCE_STATUS["sina"]
    try:
        import requests as _req
        s = _req.Session()
        s.trust_env = False
        s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
        r = s.get("https://hq.sinajs.cn/list=sh600000", timeout=10)
        _SOURCE_STATUS["sina"] = "var hq_str" in r.text
    except Exception:
        _SOURCE_STATUS["sina"] = False
    return _SOURCE_STATUS["sina"]


# ── 通用工具 ──

def get_trade_date():
    return datetime.now().strftime("%Y%m%d")


def is_trade_day(trade_date: str) -> bool:
    try:
        cal = ak.tool_trade_date_hist_sina()
        cal["trade_date"] = pd.to_datetime(cal["trade_date"]).dt.strftime("%Y%m%d")
        return trade_date in set(cal["trade_date"])
    except Exception:
        return True


def _ensure_columns(df, required_cols):
    """确保 DataFrame 包含指定列，缺失的填 NaN"""
    for col in required_cols:
        if col not in df.columns:
            df[col] = np.nan
    return df


# ── 个股行情 ──

def fetch_stock_spot():
    """
    获取 A 股实时行情
    优先东方财富(全字段)，不可用时降级新浪(少部分字段)
    """
    if _check_eastmoney():
        return _fetch_stock_spot_em()
    return _fetch_stock_spot_sina()


def _fetch_stock_spot_em():
    """东方财富通道：使用 push2delay 端点分页获取，字段最全"""
    import requests as _req

    s = _req.Session()
    s.trust_env = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    })

    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    base_params = {
        "pz": "100",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23",
    }

    all_rows = []
    page = 1
    total = None

    while True:
        params = {**base_params, "pn": str(page)}
        resp = s.get(url, params=params, timeout=30)
        data = resp.json()

        if data.get("data") is None:
            raise RuntimeError(f"EastMoney 接口返回异常：{resp.text[:200]}")

        if total is None:
            total = data["data"].get("total", 0)

        diff = data["data"].get("diff") or []
        all_rows.extend(diff)

        if len(all_rows) >= total:
            break
        page += 1

    df = pd.DataFrame(all_rows)
    if df.empty:
        raise RuntimeError("EastMoney 返回空数据")

    col_map = {
        "f12": "code",
        "f14": "name",
        "f2": "close",
        "f3": "pct_chg",
        "f5": "volume",
        "f6": "amount",
        "f7": "amplitude",
        "f8": "turnover",
        "f9": "pe",
        "f10": "volume_ratio",
        "f15": "high",
        "f16": "low",
        "f17": "open",
        "f18": "pre_close",
        "f20": "total_mv",
        "f21": "float_mv",
        "f23": "pb",
    }
    df = df.rename(columns=col_map)

    df["code"] = df["code"].astype(str)
    for col in ["close", "pct_chg", "volume", "amount", "amplitude",
                "high", "low", "open", "pre_close", "volume_ratio",
                "turnover", "pe", "pb", "total_mv", "float_mv"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["code", "name", "close", "pct_chg"])
    df["data_source"] = "eastmoney"
    return df


def _fetch_stock_spot_sina():
    """新浪通道：缺 volume_ratio, turnover, pe, pb, total_mv, float_mv, amplitude"""
    df = ak.stock_zh_a_spot()

    rename_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "close",
        "涨跌幅": "pct_chg",
        "成交量": "volume",
        "成交额": "amount",
        "最高": "high",
        "最低": "low",
        "今开": "open",
        "昨收": "pre_close",
    }

    df = df.rename(columns=rename_map)

    # 新浪返回 code 格式为 bj920000, sh600000 等，去掉前缀
    df["code"] = df["code"].astype(str).str[2:]

    numeric_cols = [
        "close", "pct_chg", "volume", "amount",
        "high", "low", "open", "pre_close",
    ]
    df = safe_numeric(df, numeric_cols)

    # 新浪缺失字段填补
    for col in ["volume_ratio", "turnover", "pe", "pb", "total_mv", "float_mv", "amplitude"]:
        df[col] = np.nan

    df = df.dropna(subset=["code", "name", "close", "pct_chg"])
    df["data_source"] = "sina"
    return df


# ── 指数行情 ──

def fetch_index_spot():
    """
    获取主要指数行情
    优先东方财富，不可用时降级新浪
    """
    if _check_eastmoney():
        return _fetch_index_spot_em()
    return _fetch_index_spot_sina()


def _fetch_index_spot_em():
    try:
        df = ak.stock_zh_index_spot_em()
    except Exception:
        df = pd.DataFrame()
    return df


def _fetch_index_spot_sina():
    try:
        df = ak.stock_zh_index_spot_sina()

        rename_map = {
            "代码": "代码",
            "名称": "名称",
            "最新价": "最新价",
            "涨跌幅": "涨跌幅",
            "涨跌额": "涨跌额",
            "昨收": "昨收",
            "今开": "今开",
            "最高": "最高",
            "最低": "最低",
            "成交量": "成交量",
            "成交额": "成交额",
        }
        # 新浪字段名与东方财富一致（中文），保留中文列名给 market.py 用
        # 只补充可能缺失的列
        for col in ["今开", "昨收", "最高", "最低"]:
            if col not in df.columns:
                df[col] = np.nan
    except Exception:
        df = pd.DataFrame()
    return df


# ── 行业/概念板块 ──

def fetch_industry_boards():
    """
    获取行业板块数据
    优先东方财富(含涨跌幅/换手率/领涨股等)，不可用时降级同花顺(仅名称和代码)
    """
    if _check_eastmoney():
        return _fetch_boards_em("行业", ak.stock_board_industry_name_em)
    return _fetch_boards_ths("行业", ak.stock_board_industry_name_ths)


def fetch_concept_boards():
    """
    获取概念板块数据
    优先东方财富(含涨跌幅/换手率/领涨股等)，不可用时降级同花顺(仅名称和代码)
    """
    if _check_eastmoney():
        return _fetch_boards_em("概念", ak.stock_board_concept_name_em)
    return _fetch_boards_ths("概念", ak.stock_board_concept_name_ths)


def _fetch_em_delay(fs_filter, fields, rename_map, numeric_cols, pz=500):
    """通用 EastMoney push2delay 数据获取"""
    import requests as _req

    s = _req.Session()
    s.trust_env = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    })

    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": str(pz),
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": fs_filter,
        "fields": fields,
    }

    resp = s.get(url, params=params, timeout=30)
    data = resp.json()
    rows = data.get("data", {}).get("diff") or []
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.rename(columns=rename_map)
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def _fetch_boards_em(board_type_label, fetch_fn):
    """行业/概念板块数据，使用 push2delay 端点"""
    fs_filter = "m:90+t:2" if board_type_label == "行业" else "m:90+t:3"
    fields = "f2,f3,f4,f6,f8,f12,f14,f20,f104,f105,f128,f136"
    rename_map = {
        "f12": "board_code",
        "f14": "board_name",
        "f2": "price",
        "f3": "pct_chg",
        "f6": "amount",
        "f8": "turnover",
        "f20": "total_mv",
        "f104": "up_count",
        "f105": "down_count",
        "f128": "leader",
        "f136": "leader_pct_chg",
    }
    numeric_cols = ["price", "pct_chg", "amount", "total_mv", "turnover",
                    "up_count", "down_count", "leader_pct_chg"]
    df = _fetch_em_delay(fs_filter, fields, rename_map, numeric_cols, pz=500)
    df["board_type"] = board_type_label
    if "amount" not in df.columns:
        df["amount"] = np.nan
    df["data_source"] = "eastmoney"
    return df


def _fetch_boards_ths(board_type_label, fetch_fn):
    """
    同花顺通道：仅返回板块名称和代码，无实时行情数据
    """
    df = fetch_fn()
    # THS returns ['name', 'code']
    df = df.rename(columns={"name": "board_name", "code": "board_code"})
    df["board_type"] = board_type_label

    # 同花顺缺失的行情字段全部置 NaN
    for col in ["price", "pct_chg", "total_mv", "turnover",
                "up_count", "down_count", "leader", "leader_pct_chg", "amount"]:
        df[col] = np.nan

    df["data_source"] = "ths"
    return df


# ── 个股历史K线 ──

def get_stock_history(code: str, days: int = 80):
    """
    获取个股历史K线，用于计算 MA/涨幅
    优先 Sina，不可用时降级 Tencent
    """
    df = _get_stock_history_sina(code, days)
    if not df.empty:
        return df
    return _get_stock_history_tx(code, days)


def _get_stock_history_sina(code: str, days: int = 80):
    """新浪通道"""
    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            adjust="qfq"
        )
        df = df.tail(days).copy()

        rename_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
            "换手率": "turnover",
        }
        df = df.rename(columns=rename_map)
        df = safe_numeric(df, ["open", "close", "high", "low", "volume", "amount", "pct_chg", "turnover"])
        return df
    except Exception:
        return pd.DataFrame()


def _get_stock_history_tx(code: str, days: int = 80):
    """腾讯通道"""
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=code,
            period="daily",
            adjust="qfq"
        )
        df = df.tail(days).copy()

        rename_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
        }
        df = df.rename(columns=rename_map)
        df = safe_numeric(df, ["open", "close", "high", "low", "volume"])

        if "amount" not in df.columns:
            df["amount"] = np.nan
        if "pct_chg" not in df.columns:
            df["pct_chg"] = np.nan
        if "turnover" not in df.columns:
            df["turnover"] = np.nan

        return df
    except Exception:
        return pd.DataFrame()


# ── 技术指标补充 ──

def enrich_stock_indicators(stock_df):
    """给个股实时数据补充 MA5/MA10/MA20/5日涨幅/20日涨幅"""
    df = stock_df.copy()

    df["ma5"] = np.nan
    df["ma10"] = np.nan
    df["ma20"] = np.nan
    df["pct_5d"] = np.nan
    df["pct_20d"] = np.nan

    candidates = df[
        (df["amount"] > 100000000)
        & (df["close"] > 2)
        & (df["pct_chg"] > -8)
    ].copy()

    candidates = candidates.sort_values("amount", ascending=False).head(500)

    for idx, row in candidates.iterrows():
        hist = get_stock_history(row["code"], days=80)
        if hist.empty or len(hist) < 20:
            continue

        close = hist["close"]
        ma5 = close.tail(5).mean()
        ma10 = close.tail(10).mean()
        ma20 = close.tail(20).mean()

        pct_5d = close.iloc[-1] / close.iloc[-6] - 1 if len(close) >= 6 else np.nan
        pct_20d = close.iloc[-1] / close.iloc[-21] - 1 if len(close) >= 21 else np.nan

        df.loc[idx, "ma5"] = ma5
        df.loc[idx, "ma10"] = ma10
        df.loc[idx, "ma20"] = ma20
        df.loc[idx, "pct_5d"] = pct_5d * 100
        df.loc[idx, "pct_20d"] = pct_20d * 100

    return df


# ── 数据源状态查询 ──

def get_source_status():
    """获取当前数据源可用状态"""
    _check_eastmoney()
    _check_sina()
    return {
        "eastmoney": _SOURCE_STATUS["eastmoney"],
        "sina": _SOURCE_STATUS["sina"],
    }
