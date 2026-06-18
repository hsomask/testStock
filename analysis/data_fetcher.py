import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta
import akshare as ak
import logging

warnings.filterwarnings("ignore")

from analysis.utils import safe_numeric
from analysis.limitup_metrics import enrich_limitup_flags

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
        # API 失败时用星期简单判断（周一至周五为交易日）
        from datetime import datetime
        try:
            dt = datetime.strptime(str(trade_date)[:8], "%Y%m%d")
            return dt.weekday() < 5  # 0=Mon, 4=Fri
        except Exception:
            return False


def _latest_expected_cache_date():
    """Return the minimum recent date a daily K-line cache should cover."""
    today = datetime.now().date()
    offset = 1
    candidate = today - timedelta(days=offset)
    while candidate.weekday() >= 5:
        offset += 1
        candidate = today - timedelta(days=offset)
    return candidate.strftime("%Y-%m-%d")


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
    优先东方财富，降级新浪，最终 fallback 腾讯
    """
    # 东方财富
    if _check_eastmoney():
        df = _fetch_index_spot_em()
        if df is not None and not df.empty:
            return df
    # 新浪
    df = _fetch_index_spot_sina()
    if df is not None and not df.empty:
        return df
    # 腾讯 fallback
    from analysis.data_sources.tencent import fetch_index_spot_tencent
    indices = fetch_index_spot_tencent()
    if indices:
        return pd.DataFrame(indices)
    return pd.DataFrame()


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


def _fetch_em_delay(fs_filter, fields, rename_map, numeric_cols, pz=100):
    """通用 EastMoney push2delay 分页获取"""
    import requests as _req

    s = _req.Session()
    s.trust_env = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    })

    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    all_rows = []
    page = 1
    total = None

    while True:
        params = {
            "pn": str(page),
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
        if total is None:
            total = data.get("data", {}).get("total", 0)
        diff = data.get("data", {}).get("diff") or []
        all_rows.extend(diff)
        if len(all_rows) >= total:
            break
        page += 1

    df = pd.DataFrame(all_rows)
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

def _history_session():
    import requests as _req
    s = _req.Session()
    s.trust_env = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    })
    return s


def _get_stock_history_sina(code: str, days: int = 80):
    """新浪通道：直连 money.finance.sina.com.cn"""
    try:
        s = _history_session()
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        r = s.get(url, params={"symbol": code, "scale": "240", "ma": "no", "datalen": str(days)}, timeout=15)
        records = r.json()
        if not records or not isinstance(records, list):
            return pd.DataFrame()

        df = pd.DataFrame(records)
        rename_map = {
            "day": "date", "open": "open", "close": "close",
            "high": "high", "low": "low", "volume": "volume",
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
    except Exception as e:
        logger.debug(f"Sina 历史行情获取失败：{code}, {e}")
        return pd.DataFrame()


def _get_stock_history_tx(code: str, days: int = 80):
    """腾讯通道：直连 web.ifzq.gtimg.cn"""
    try:
        s = _history_session()
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        r = s.get(url, params={"param": f"{code},day,,,{days},qfq"}, timeout=15)
        data = r.json()
        if data.get("code") != 0:
            return pd.DataFrame()

        # 从嵌套结构中提取数据
        stock_data = data.get("data", {}).get(code, {})
        klines = stock_data.get("qfqday") or stock_data.get("day") or []
        if not klines:
            return pd.DataFrame()

        df = pd.DataFrame(klines, columns=["date", "open", "close", "high", "low", "volume"])
        df = safe_numeric(df, ["open", "close", "high", "low", "volume"])
        df["amount"] = np.nan
        df["pct_chg"] = np.nan
        df["turnover"] = np.nan
        return df
    except Exception as e:
        logger.debug(f"Tencent 历史行情获取失败：{code}, {e}")
        return pd.DataFrame()


_hist_db_conn = None

def _get_hist_db_conn():
    global _hist_db_conn
    if _hist_db_conn is not None:
        try:
            if not _hist_db_conn.closed:
                # 验证连接仍可用
                cur = _hist_db_conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                return _hist_db_conn
        except Exception:
            # 连接已断开，关闭并重建
            try:
                _hist_db_conn.close()
            except Exception:
                pass
            _hist_db_conn = None

    import psycopg2 as _pg
    from data.config import DATABASE_DSN as _dsn
    if not _dsn:
        return None
    _hist_db_conn = _pg.connect(_dsn)
    return _hist_db_conn


def _close_hist_db_conn():
    global _hist_db_conn
    if _hist_db_conn is not None and not _hist_db_conn.closed:
        _hist_db_conn.close()
    _hist_db_conn = None


def calc_macd(close_series, fast=12, slow=26, signal=9):
    """计算 MACD 指标，返回 DIF, DEA, MACD 柱"""
    close = pd.to_numeric(pd.Series(close_series), errors="coerce").dropna()
    if len(close) < slow + signal:
        return pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = (dif - dea) * 2
    return dif, dea, macd_bar


def _get_hist_from_db(code, days=80):
    """从 stock_hist_kline 表读取历史K线"""
    conn = _get_hist_db_conn()
    if conn is None:
        return pd.DataFrame()
    try:
        df = pd.read_sql(
            "SELECT trade_date as date, name, open, close, high, low, volume, "
            "pre_close, pct_chg, amount, turnover, limit_ratio, "
            "limit_up_price, limit_down_price, is_limit_up, is_limit_down, "
            "is_touched_limit_up, is_failed_limit_up, data_source "
            "FROM stock_hist_kline WHERE code=%s "
            "ORDER BY trade_date DESC LIMIT %s",
            conn, params=(code, days)
        )
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.sort_values("date")
        return df
    except Exception as e:
        try:
            conn.rollback()
            df = pd.read_sql(
                "SELECT trade_date as date, open, close, high, low, volume "
                "FROM stock_hist_kline WHERE code=%s "
                "ORDER BY trade_date DESC LIMIT %s",
                conn, params=(code, days)
            )
            if df.empty:
                return df
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df.sort_values("date")
            df["amount"] = np.nan
            df["pct_chg"] = np.nan
            df["turnover"] = np.nan
            return df
        except Exception as fallback_error:
            logger.debug(f"读取历史K线缓存失败：{code}, {e}; fallback={fallback_error}")
            return pd.DataFrame()


def _save_hist_to_db(code, df):
    """保存历史K线到 stock_hist_kline，复用连接批量写入"""
    conn = _get_hist_db_conn()
    if conn is None or df.empty or "date" not in df.columns:
        return
    try:
        cur = conn.cursor()
        for _, row in df.iterrows():
            if pd.isna(row.get("date")):
                continue
            cur.execute("""
                INSERT INTO stock_hist_kline (
                    code, trade_date, name,
                    open, close, high, low, volume,
                    pre_close, pct_chg, amount, turnover,
                    limit_ratio, limit_up_price, limit_down_price,
                    is_limit_up, is_limit_down, is_touched_limit_up, is_failed_limit_up,
                    data_source, updated_at
                )
                VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, CURRENT_TIMESTAMP
                )
                ON CONFLICT (code, trade_date)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    open = EXCLUDED.open,
                    close = EXCLUDED.close,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    volume = EXCLUDED.volume,
                    pre_close = EXCLUDED.pre_close,
                    pct_chg = EXCLUDED.pct_chg,
                    amount = EXCLUDED.amount,
                    turnover = EXCLUDED.turnover,
                    limit_ratio = EXCLUDED.limit_ratio,
                    limit_up_price = EXCLUDED.limit_up_price,
                    limit_down_price = EXCLUDED.limit_down_price,
                    is_limit_up = EXCLUDED.is_limit_up,
                    is_limit_down = EXCLUDED.is_limit_down,
                    is_touched_limit_up = EXCLUDED.is_touched_limit_up,
                    is_failed_limit_up = EXCLUDED.is_failed_limit_up,
                    data_source = EXCLUDED.data_source,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                code,
                str(row["date"])[:10],
                _text_or_none(row.get("name")),
                _num_or_none(row.get("open")),
                _num_or_none(row.get("close")),
                _num_or_none(row.get("high")),
                _num_or_none(row.get("low")),
                _num_or_none(row.get("volume")),
                _num_or_none(row.get("pre_close")),
                _num_or_none(row.get("pct_chg")),
                _num_or_none(row.get("amount")),
                _num_or_none(row.get("turnover")),
                _num_or_none(row.get("limit_ratio")),
                _num_or_none(row.get("limit_up_price")),
                _num_or_none(row.get("limit_down_price")),
                _bool_or_none(row.get("is_limit_up")),
                _bool_or_none(row.get("is_limit_down")),
                _bool_or_none(row.get("is_touched_limit_up")),
                _bool_or_none(row.get("is_failed_limit_up")),
                _text_or_none(row.get("data_source")),
            ))
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
            cur = conn.cursor()
            for _, row in df.iterrows():
                if pd.isna(row.get("date")):
                    continue
                cur.execute("""
                    INSERT INTO stock_hist_kline (code, trade_date, open, close, high, low, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (code, trade_date) DO NOTHING
                """, (
                    code,
                    str(row["date"])[:10],
                    _num_or_none(row.get("open")),
                    _num_or_none(row.get("close")),
                    _num_or_none(row.get("high")),
                    _num_or_none(row.get("low")),
                    _num_or_none(row.get("volume")),
                ))
            conn.commit()
            cur.close()
            logger.debug(f"历史K线扩展字段保存失败，已回退旧字段：{code}, {e}")
        except Exception as fallback_error:
            logger.debug(f"保存历史K线失败：{code}, {e}; fallback={fallback_error}")


def _num_or_none(x):
    try:
        if pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None


def _bool_or_none(x):
    try:
        if pd.isna(x):
            return None
        return bool(x)
    except Exception:
        return None


def _text_or_none(x):
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    if x is None:
        return None
    return str(x)


def get_stock_history(
    code: str,
    days: int = 80,
    name: str = "",
    require_fresh: bool = True,
    allow_api: bool = True,
):
    """
    获取个股历史K线。优先从 DB 缓存读取，缺失时从 API 获取并自动入库。
    """
    code = str(code).strip()

    # 1. 先查 DB 缓存
    db_df = _get_hist_from_db(code, days)
    db_dates = set()
    if not db_df.empty and "date" in db_df.columns:
        db_dates = set(db_df["date"].astype(str).str[:10].tolist())
    latest_db_date = max(db_dates) if db_dates else None
    fresh_cutoff = _latest_expected_cache_date() if require_fresh else None

    # 2. 如果 DB 已有足够且不陈旧的数据，直接返回
    has_enough_cache = len(db_dates) >= max(days - 3, 1)
    is_fresh_enough = (not require_fresh) or (latest_db_date and latest_db_date >= fresh_cutoff)
    if has_enough_cache and is_fresh_enough:
        return db_df.tail(days)

    if not allow_api:
        return db_df.tail(days) if not db_df.empty else pd.DataFrame()

    # 3. 从 API 获取
    symbol_candidates = [code]
    if code.startswith(("6", "9")):
        symbol_candidates.append(f"sh{code}")
    elif code.startswith(("0", "3")):
        symbol_candidates.append(f"sz{code}")
    elif code.startswith(("8", "4")):
        symbol_candidates.append(f"bj{code}")

    api_df = pd.DataFrame()
    for symbol in symbol_candidates:
        api_df = _get_stock_history_sina(symbol, days)
        if not api_df.empty:
            break

    if api_df.empty:
        for symbol in symbol_candidates:
            api_df = _get_stock_history_tx(symbol, days)
            if not api_df.empty:
                break

    if api_df.empty:
        logger.debug(f"历史行情全部通道失败：{code}, tried={symbol_candidates}")
        return db_df if not db_df.empty else pd.DataFrame()

    api_df["code"] = code
    api_df["name"] = name
    api_df = enrich_limitup_flags(api_df)
    if "data_source" not in api_df.columns:
        api_df["data_source"] = "get_stock_history"

    # 4. 只保存 DB 中没有的新日期
    new_rows = []
    for _, row in api_df.iterrows():
        d = str(row["date"])[:10]
        if d not in db_dates:
            new_rows.append(row)
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        _save_hist_to_db(code, new_df)

    # 5. 合并 DB + 新增，返回
    if not db_df.empty:
        combined = pd.concat([db_df, api_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["date"]).sort_values("date")
        return combined.tail(days)
    return api_df.tail(days)


# ── 技术指标补充 ──

def calc_history_indicators(hist):
    """从历史K线计算 MA5/MA10/MA20/5日涨幅/20日涨幅"""
    if hist is None or hist.empty or "close" not in hist.columns:
        return None

    close = pd.to_numeric(hist["close"], errors="coerce").dropna()
    if len(close) < 5:
        return None

    return {
        "ma5": close.tail(5).mean() if len(close) >= 5 else np.nan,
        "ma10": close.tail(10).mean() if len(close) >= 10 else np.nan,
        "ma20": close.tail(20).mean() if len(close) >= 20 else np.nan,
        "pct_5d": (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else np.nan,
        "pct_20d": (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else np.nan,
    }


def _estimate_volume_ratio(row, hist):
    """Estimate volume ratio when the real-time source does not provide it."""
    if hist is None or hist.empty or "volume" not in hist.columns:
        return np.nan

    volumes = pd.to_numeric(hist["volume"], errors="coerce").dropna()
    if len(volumes) < 5:
        return np.nan

    current_volume = pd.to_numeric(pd.Series([row.get("volume", np.nan)]), errors="coerce").iloc[0]
    if pd.isna(current_volume) or current_volume <= 0:
        current_volume = volumes.iloc[-1]
        base = volumes.iloc[-6:-1] if len(volumes) >= 6 else volumes.iloc[:-1]
    else:
        base = volumes.tail(5)

    avg_volume = base.mean() if len(base) else np.nan
    if pd.isna(avg_volume) or avg_volume <= 0:
        return np.nan
    return float(current_volume) / float(avg_volume)


def enrich_stock_indicators(stock_df, max_stocks: int = 2000):
    """给个股实时数据补充 MA5/MA10/MA20/5日涨幅/20日涨幅"""
    df = stock_df.copy()

    for col in ["ma5", "ma10", "ma20", "pct_5d", "pct_20d"]:
        if col not in df.columns:
            df[col] = np.nan

    if "volume_ratio" not in df.columns:
        df["volume_ratio"] = np.nan

    # 基础过滤
    base = df[
        (pd.to_numeric(df["close"], errors="coerce") > 2)
        & (pd.to_numeric(df["pct_chg"], errors="coerce") > -8)
    ].copy()

    selected_indices = []
    seen_indices = set()

    def add_indices(indices):
        for idx in indices:
            if len(selected_indices) >= max_stocks:
                break
            if idx in seen_indices:
                continue
            selected_indices.append(idx)
            seen_indices.add(idx)
            if len(selected_indices) >= max_stocks:
                break

    # 1. 成交额靠前
    if "amount" in base.columns:
        add_indices(
            base.sort_values("amount", ascending=False).head(2000).index.tolist()
        )

    # 2. 涨幅靠前
    add_indices(
        base.sort_values("pct_chg", ascending=False).head(300).index.tolist()
    )

    # 3. 量比靠前
    if "volume_ratio" in base.columns:
        add_indices(
            base.sort_values("volume_ratio", ascending=False).head(300).index.tolist()
        )

    # 4. 换手率靠前
    if "turnover" in base.columns:
        add_indices(
            base.sort_values("turnover", ascending=False).head(300).index.tolist()
        )

    success = 0
    fail = 0
    volume_ratio_filled = 0

    for idx in selected_indices:
        code = str(df.at[idx, "code"])
        name = df.at[idx, "name"] if "name" in df.columns else ""
        hist = get_stock_history(code, days=80, name=name, require_fresh=False, allow_api=False)
        indicators = calc_history_indicators(hist)

        if pd.isna(df.at[idx, "volume_ratio"]):
            estimated_volume_ratio = _estimate_volume_ratio(df.loc[idx], hist)
            if pd.notna(estimated_volume_ratio):
                df.loc[idx, "volume_ratio"] = estimated_volume_ratio
                volume_ratio_filled += 1

        if not indicators:
            fail += 1
            continue

        for k, v in indicators.items():
            df.loc[idx, k] = v

        success += 1

    logger.info(f"技术指标补充完成：成功 {success} 只，失败 {fail} 只，候选 {len(selected_indices)} 只")
    return df


def enrich_selected_stocks_indicators(selector_result):
    """对最终观察池股票二次补齐 MA/涨幅"""
    for pool_name, pool_df in selector_result.items():
        if pool_df is None or pool_df.empty:
            continue

        for idx, row in pool_df.iterrows():
            need_fill = (
                pd.isna(row.get("ma5"))
                or pd.isna(row.get("ma10"))
                or pd.isna(row.get("ma20"))
                or pd.isna(row.get("pct_5d"))
                or pd.isna(row.get("pct_20d"))
            )

            if not need_fill:
                continue

            code = str(row.get("code", ""))
            hist = get_stock_history(code, days=80, name=row.get("name", ""))
            indicators = calc_history_indicators(hist)

            if not indicators:
                continue

            for k, v in indicators.items():
                pool_df.at[idx, k] = v

        selector_result[pool_name] = pool_df

    return selector_result


# ── 数据源状态查询 ──

def get_source_status():
    """获取当前数据源可用状态"""
    _check_eastmoney()
    _check_sina()
    return {
        "eastmoney": _SOURCE_STATUS["eastmoney"],
        "sina": _SOURCE_STATUS["sina"],
    }
