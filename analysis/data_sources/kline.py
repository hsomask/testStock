"""Sina and Tencent daily K-line source adapters."""

import logging

import numpy as np
import pandas as pd

from analysis.utils import safe_numeric


logger = logging.getLogger(__name__)
_REQUIRED_COLUMNS = ("date", "open", "close", "high", "low", "volume")


def _validate_history_frame(frame, source):
    """Reject malformed provider rows before they can poison the shared cache."""
    if frame is None or frame.empty or any(column not in frame.columns for column in _REQUIRED_COLUMNS):
        return pd.DataFrame()
    result = frame.copy()
    parsed_dates = pd.to_datetime(result["date"], errors="coerce")
    valid = parsed_dates.notna()
    for field in ("open", "close", "high", "low", "volume"):
        valid &= pd.to_numeric(result[field], errors="coerce").notna()
    valid &= (result[["open", "close", "high", "low"]] > 0).all(axis=1)
    valid &= result["volume"] >= 0
    valid &= result["high"] >= result[["open", "close", "low"]].max(axis=1)
    valid &= result["low"] <= result[["open", "close", "high"]].min(axis=1)
    dropped = int((~valid).sum())
    result = result.loc[valid].copy()
    if result.empty:
        logger.warning("%s K-line payload rejected: no valid OHLCV rows", source)
        return pd.DataFrame()
    result["date"] = parsed_dates.loc[valid].dt.strftime("%Y-%m-%d")
    result = result.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    if dropped:
        logger.warning("%s K-line payload dropped %s malformed rows", source, dropped)
    return result.reset_index(drop=True)


def _history_session():
    import requests

    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    })
    return session


def fetch_sina_history(code: str, days: int = 80, *, session_factory=_history_session):
    try:
        response = session_factory().get(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            params={"symbol": code, "scale": "240", "ma": "no", "datalen": str(days)},
            timeout=15,
        )
        records = response.json()
        if not records or not isinstance(records, list):
            return pd.DataFrame()
        frame = pd.DataFrame(records).rename(columns={"day": "date"})
        frame = safe_numeric(frame, ["open", "close", "high", "low", "volume"])
        for field in ("amount", "pct_chg", "turnover"):
            if field not in frame.columns:
                frame[field] = np.nan
        frame["data_source"] = "sina"
        return _validate_history_frame(frame, "sina")
    except Exception as exc:
        logger.debug("Sina history fetch failed: %s, %s", code, exc)
        return pd.DataFrame()


def fetch_tencent_history(code: str, days: int = 80, *, session_factory=_history_session):
    try:
        response = session_factory().get(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": f"{code},day,,,{days},qfq"},
            timeout=15,
        )
        payload = response.json()
        if payload.get("code") != 0:
            return pd.DataFrame()
        stock_data = payload.get("data", {}).get(code, {})
        klines = stock_data.get("qfqday") or stock_data.get("day") or []
        if not klines:
            return pd.DataFrame()
        frame = pd.DataFrame(
            klines,
            columns=["date", "open", "close", "high", "low", "volume"],
        )
        frame = safe_numeric(frame, ["open", "close", "high", "low", "volume"])
        frame["amount"] = np.nan
        frame["pct_chg"] = np.nan
        frame["turnover"] = np.nan
        frame["data_source"] = "tencent"
        return _validate_history_frame(frame, "tencent")
    except Exception as exc:
        logger.debug("Tencent history fetch failed: %s, %s", code, exc)
        return pd.DataFrame()
