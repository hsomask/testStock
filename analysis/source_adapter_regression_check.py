"""Behavior-equivalence checks for limit-up and board source adapters."""

from unittest.mock import patch

import pandas as pd

from analysis import data_fetcher
from analysis import stock_board_mapper
from analysis.data_sources.eastmoney import fetch_paginated
from analysis.data_sources.eastmoney_board import (
    fetch_board_constituents,
    fetch_board_list,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _PagedSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return _Response(payload)


def main():
    session = _PagedSession([
        {"data": {"total": 3, "diff": [{"f12": "BK1", "f14": "板块一"}, {"f12": "BK2", "f14": "板块二"}]}},
        {"data": {"total": 3, "diff": [{"f12": "BK3", "f14": "板块三"}]}},
    ])
    frame = fetch_paginated(
        "m:90+t:2",
        "f12,f14",
        pz=2,
        session_factory=lambda: session,
    )
    assert list(frame["f12"]) == ["BK1", "BK2", "BK3"]
    assert [call[1]["params"]["pn"] for call in session.calls] == ["1", "2"]
    assert all(call[1]["timeout"] == 30 for call in session.calls)

    retry_session = _PagedSession([
        RuntimeError("temporary"),
        {"data": {"total": 1, "diff": [{"f12": "BK1", "f14": "板块一"}]}},
    ])
    retry_frame = fetch_paginated(
        "m:90+t:2",
        "f12,f14",
        retries=1,
        session_factory=lambda: retry_session,
    )
    assert len(retry_frame) == 1 and len(retry_session.calls) == 2

    stalled_session = _PagedSession([
        {"data": {"total": 10, "diff": []}},
        {"data": {"total": 10, "diff": []}},
    ])
    try:
        fetch_paginated(
            "m:90+t:2",
            "f12,f14",
            retries=0,
            max_empty_pages=2,
            session_factory=lambda: stalled_session,
        )
        raise AssertionError("stalled pagination must fail")
    except RuntimeError as exc:
        assert "stalled" in str(exc)

    calls = []

    def board_pages(fs_filter, fields, pz):
        calls.append((fs_filter, fields, pz))
        return pd.DataFrame([
            {"f12": "BK001", "f14": "有效板块"},
            {"f12": "BK002", "f14": None},
        ])

    assert fetch_board_list("行业", page_fetcher=board_pages) == [("BK001", "有效板块")]
    assert calls[-1] == ("m:90+t:2", "f12,f14", 500)
    assert fetch_board_list("概念", page_fetcher=board_pages) == [("BK001", "有效板块")]
    assert calls[-1] == ("m:90+t:3", "f12,f14", 500)

    def constituent_page(fs_filter, fields, pz):
        calls.append((fs_filter, fields, pz))
        return pd.DataFrame([{"f12": 1, "f14": "股票一"}])

    assert fetch_board_constituents("BK001", page_fetcher=constituent_page) == [("000001", "股票一")]
    assert calls[-1] == ("b:BK001", "f12,f14", 500)

    fallback = pd.DataFrame([
        {"code": f"{index:06d}", "name": f"stock-{index}", "close": 10.0, "pct_chg": 1.0}
        for index in range(1000)
    ])
    with (
        patch.object(data_fetcher, "_check_eastmoney", return_value=True),
        patch.object(data_fetcher, "_fetch_stock_spot_em", side_effect=RuntimeError("primary down")),
        patch.object(data_fetcher, "_fetch_stock_spot_sina", return_value=fallback),
    ):
        assert data_fetcher.fetch_stock_spot() is fallback

    try:
        data_fetcher._validate_stock_spot_frame(fallback.head(10), "fixture")
        raise AssertionError("partial stock universe must fail")
    except RuntimeError as exc:
        assert "too small" in str(exc)

    with patch.object(stock_board_mapper, "fetch_board_list", return_value=[]):
        try:
            stock_board_mapper.update_industry_stock_map(None)
            raise AssertionError("empty board list must fail loudly")
        except RuntimeError as exc:
            assert "empty" in str(exc)

    print("[OK] source adapter regression check")


if __name__ == "__main__":
    main()
