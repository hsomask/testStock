"""Normalized daily report facts shared by renderers and sidecars.

This module intentionally does not fetch or infer new data.  It only packages
the already-computed pipeline outputs into one stable shape so renderers,
email, LLM context and future ML features consume the same facts.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_daily_facts(
    trade_date: str,
    data_status: Any,
    quality: dict[str, Any] | None,
    market: dict[str, Any] | None,
    industry: Any = None,
    concept: Any = None,
    sentiment: dict[str, Any] | None = None,
    selectors: Any = None,
    board_ratio_changes: Any = None,
    mode: str = "unified",
    trade_plan: dict[str, Any] | None = None,
    board_trend_summary: Any = None,
    report_context: dict[str, Any] | None = None,
    themes: list[dict[str, Any]] | None = None,
    t1_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded, immutable-ish fact bundle for one daily report run."""
    return {
        "trade_date": trade_date,
        "mode": mode,
        "data_status": data_status,
        "quality": deepcopy(quality or {}),
        "market": deepcopy(market or {}),
        "industry": industry,
        "concept": concept,
        "sentiment": deepcopy(sentiment or {}),
        "selectors": selectors,
        "board_ratio_changes": board_ratio_changes,
        "trade_plan": deepcopy(trade_plan or {}),
        "board_trend_summary": board_trend_summary,
        "report_context": deepcopy(report_context or {}),
        "themes": deepcopy(themes or []),
        "t1_data": deepcopy(t1_data or {}),
        "raw_refs": {
            "has_data_status": bool(data_status),
            "industry_present": industry is not None,
            "concept_present": concept is not None,
            "selectors_present": selectors is not None,
            "board_trend_summary_present": board_trend_summary is not None,
            "report_context_present": report_context is not None,
            "theme_count": len(themes or []),
        },
    }
