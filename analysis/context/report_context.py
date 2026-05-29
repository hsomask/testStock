from __future__ import annotations

from typing import Any


def build_empty_report_context(trade_date: str) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "market": {},
        "sentiment": {},
        "boards": {},
        "themes": {},
        "watchlists": {},
        "trade_plan": {},
        "quality": {},
        "pipeline": {},
    }
