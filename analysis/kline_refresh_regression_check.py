"""Regression checks for target-date refresh and K-line provenance."""

from unittest.mock import patch

import numpy as np
import pandas as pd

from analysis import data_fetcher


TARGET_DATE = "2026-08-07"


def _row(date=TARGET_DATE, close=10.2, volume=1000, source="cache"):
    return {
        "date": date,
        "open": 10.0,
        "close": close,
        "high": 10.3,
        "low": 9.9,
        "volume": volume,
        "amount": np.nan,
        "pct_chg": np.nan,
        "turnover": np.nan,
        "data_source": source,
    }


def main():
    complete = pd.DataFrame([_row()])
    incomplete = complete.copy()
    incomplete.loc[0, "close"] = np.nan

    assert data_fetcher._target_dates_needing_refresh(complete, TARGET_DATE) == set()
    assert data_fetcher._target_dates_needing_refresh(incomplete, TARGET_DATE) == {TARGET_DATE}
    assert data_fetcher._target_dates_needing_refresh(pd.DataFrame(), TARGET_DATE) == {TARGET_DATE}

    changed = pd.DataFrame([_row(close=10.5, source="sina")])
    conflicts = data_fetcher._validate_kline_conflicts(complete, changed)
    assert conflicts == [{"date": TARGET_DATE, "fields": ["close"]}]

    fetched = pd.DataFrame([_row(close=10.5, source="sina")])
    saved = []
    with (
        patch.object(data_fetcher, "_get_hist_from_db", return_value=incomplete),
        patch.object(data_fetcher, "_latest_expected_cache_date", return_value=TARGET_DATE),
        patch.object(data_fetcher, "fetch_sina_history", return_value=fetched),
        patch.object(data_fetcher, "fetch_tencent_history", side_effect=AssertionError("fallback must not run")),
        patch.object(data_fetcher, "enrich_limitup_flags", side_effect=lambda frame: frame),
        patch.object(data_fetcher, "_save_hist_to_db", side_effect=lambda code, frame: saved.append(frame.copy())),
    ):
        result = data_fetcher.get_stock_history("600000", days=1, name="浦发银行")

    assert len(saved) == 1 and len(saved[0]) == 1
    assert saved[0].iloc[0]["data_source"] == "sina"
    assert result.iloc[-1]["close"] == 10.5
    assert result.iloc[-1]["data_source"] == "sina"

    older_only = pd.DataFrame([_row(date="2026-08-06", close=10.1, source="sina")])
    saved_without_target = []
    with (
        patch.object(data_fetcher, "_get_hist_from_db", return_value=incomplete),
        patch.object(data_fetcher, "_latest_expected_cache_date", return_value=TARGET_DATE),
        patch.object(data_fetcher, "fetch_sina_history", return_value=older_only),
        patch.object(data_fetcher, "fetch_tencent_history", return_value=pd.DataFrame()),
        patch.object(data_fetcher, "enrich_limitup_flags", side_effect=lambda frame: frame),
        patch.object(data_fetcher, "_save_hist_to_db", side_effect=lambda code, frame: saved_without_target.append(frame.copy())),
    ):
        unresolved_result = data_fetcher.get_stock_history("600000", days=5)

    assert TARGET_DATE in unresolved_result["date"].astype(str).tolist()
    target_row = unresolved_result[unresolved_result["date"] == TARGET_DATE].iloc[0]
    assert pd.isna(target_row["close"])
    assert all(TARGET_DATE not in frame["date"].astype(str).tolist() for frame in saved_without_target)

    fallback_saved = []
    tencent_target = pd.DataFrame([_row(close=10.4, source="tencent")])
    with (
        patch.object(data_fetcher, "_get_hist_from_db", return_value=incomplete),
        patch.object(data_fetcher, "_latest_expected_cache_date", return_value=TARGET_DATE),
        patch.object(data_fetcher, "fetch_sina_history", return_value=older_only),
        patch.object(data_fetcher, "fetch_tencent_history", return_value=tencent_target),
        patch.object(data_fetcher, "enrich_limitup_flags", side_effect=lambda frame: frame),
        patch.object(data_fetcher, "_save_hist_to_db", side_effect=lambda code, frame: fallback_saved.append(frame.copy())),
    ):
        fallback_result = data_fetcher.get_stock_history("600000", days=5)
    assert fallback_result[fallback_result["date"] == TARGET_DATE].iloc[0]["close"] == 10.4
    assert fallback_saved[0].iloc[0]["data_source"] == "tencent"

    with (
        patch.object(data_fetcher, "_get_hist_from_db", return_value=complete),
        patch.object(data_fetcher, "_latest_expected_cache_date", return_value=TARGET_DATE),
        patch.object(data_fetcher, "fetch_sina_history", side_effect=AssertionError("fresh cache must be used")),
    ):
        cached_result = data_fetcher.get_stock_history("600000", days=1)
    assert cached_result.iloc[-1]["data_source"] == "cache"

    print("[OK] kline refresh regression check")


if __name__ == "__main__":
    main()
