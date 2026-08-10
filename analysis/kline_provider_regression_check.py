"""Behavior-equivalence checks for the extracted K-line providers."""

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from analysis.data_sources.kline import fetch_sina_history, fetch_tencent_history
from analysis.utils import safe_numeric


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payload)


def _legacy_sina(records):
    if not records or not isinstance(records, list):
        return pd.DataFrame()
    frame = pd.DataFrame(records).rename(columns={
        "day": "date",
        "open": "open",
        "close": "close",
        "high": "high",
        "low": "low",
        "volume": "volume",
    })
    frame = safe_numeric(frame, ["open", "close", "high", "low", "volume"])
    if "amount" not in frame.columns:
        frame["amount"] = np.nan
    if "pct_chg" not in frame.columns:
        frame["pct_chg"] = np.nan
    if "turnover" not in frame.columns:
        frame["turnover"] = np.nan
    return frame


def _legacy_tencent(code, payload):
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
    return frame


def _factory(session):
    return lambda: session


def main():
    code = "sh600000"
    sina_payload = [{
        "day": "2026-08-10",
        "open": "10.10",
        "close": "10.35",
        "high": "10.50",
        "low": "10.00",
        "volume": "123456",
    }]
    sina_session = _Session(sina_payload)
    actual_sina = fetch_sina_history(code, 80, session_factory=_factory(sina_session))
    assert actual_sina["data_source"].eq("sina").all()
    assert_frame_equal(actual_sina.drop(columns=["data_source"]), _legacy_sina(sina_payload))
    assert sina_session.calls[0][1]["params"] == {
        "symbol": code,
        "scale": "240",
        "ma": "no",
        "datalen": "80",
    }
    assert sina_session.calls[0][1]["timeout"] == 15

    tx_payload = {
        "code": 0,
        "data": {
            code: {
                "qfqday": [["2026-08-10", "10.10", "10.35", "10.50", "10.00", "123456"]]
            }
        },
    }
    tx_session = _Session(tx_payload)
    actual_tx = fetch_tencent_history(code, 80, session_factory=_factory(tx_session))
    assert actual_tx["data_source"].eq("tencent").all()
    assert_frame_equal(actual_tx.drop(columns=["data_source"]), _legacy_tencent(code, tx_payload))
    assert tx_session.calls[0][1]["params"] == {"param": f"{code},day,,,80,qfq"}
    assert tx_session.calls[0][1]["timeout"] == 15

    assert fetch_sina_history(code, session_factory=_factory(_Session([]))).empty
    assert fetch_tencent_history(
        code,
        session_factory=_factory(_Session({"code": 1})),
    ).empty
    assert fetch_sina_history(
        code,
        session_factory=_factory(_Session(ValueError("invalid json"))),
    ).empty

    print("[OK] kline provider regression check")


if __name__ == "__main__":
    main()
