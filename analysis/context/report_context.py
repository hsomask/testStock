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


def build_report_context(
    trade_date: str,
    market: dict[str, Any] | None = None,
    sentiment: dict[str, Any] | None = None,
    boards: dict[str, Any] | None = None,
    themes: dict[str, Any] | None = None,
    watchlists: dict[str, Any] | None = None,
    trade_plan: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    pipeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = build_empty_report_context(trade_date)
    context["market"] = market or {}
    context["sentiment"] = sentiment or {}
    context["boards"] = boards or {}
    context["themes"] = themes or {}
    context["watchlists"] = watchlists or {}
    context["trade_plan"] = trade_plan or {}
    context["quality"] = quality or {}
    context["pipeline"] = pipeline or {}
    return context
