"""EastMoney board-list and constituent adapters."""

import pandas as pd

from analysis.data_sources.eastmoney import fetch_paginated


def fetch_board_list(board_type_label, *, page_fetcher=fetch_paginated):
    fs_filter = "m:90+t:2" if board_type_label == "行业" else "m:90+t:3"
    frame = page_fetcher(fs_filter, "f12,f14", pz=500)
    if frame.empty:
        return []
    return [
        (row["f12"], row["f14"])
        for _, row in frame.iterrows()
        if pd.notna(row.get("f14"))
    ]


def fetch_board_constituents(board_code, *, page_fetcher=fetch_paginated):
    frame = page_fetcher(f"b:{board_code}", "f12,f14", pz=500)
    if frame.empty:
        return []
    return [
        (str(row["f12"]).zfill(6), row.get("f14", ""))
        for _, row in frame.iterrows()
    ]
