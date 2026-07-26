"""Stable identity helpers for the signal -> snapshot -> evaluation lineage."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime


SIGNAL_ID_SCHEMA_VERSION = "signal_id_v1"
SIGNAL_NAMESPACE = uuid.UUID("fd8d6d51-70af-5f0b-9ed4-5e0eab6e6171")
DECISION_ID_SCHEMA_VERSION = "decision_id_v1"
DECISION_NAMESPACE = uuid.UUID("61081e70-5df6-5271-a71e-fcfd22a93ed3")


def normalize_signal_date(value) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y%m%d")
    text = str(value or "").strip()
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) != 8:
        raise ValueError(f"invalid signal date: {value!r}")
    return digits


def normalize_stock_code(value) -> str:
    text = str(value or "").strip().lower()
    if text.startswith(("sh", "sz", "bj")):
        text = text[2:]
    if text.isdigit() and len(text) <= 6:
        text = text.zfill(6)
    if not text:
        raise ValueError("stock code is required")
    return text


def normalize_strategy(value) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        raise ValueError("strategy is required")
    return text


def signal_natural_key(trade_date, code, strategy) -> str:
    return "|".join(
        (
            SIGNAL_ID_SCHEMA_VERSION,
            normalize_signal_date(trade_date),
            normalize_stock_code(code),
            normalize_strategy(strategy),
        )
    )


def build_signal_id(trade_date, code, strategy) -> str:
    """Return a deterministic UUIDv5 for one strategy-grain stock signal."""
    return str(uuid.uuid5(SIGNAL_NAMESPACE, signal_natural_key(trade_date, code, strategy)))


def build_decision_id(trade_date, code) -> str:
    """Return one stable stock-level decision id shared by all strategies."""
    natural_key = "|".join(
        (
            DECISION_ID_SCHEMA_VERSION,
            normalize_signal_date(trade_date),
            normalize_stock_code(code),
        )
    )
    return str(uuid.uuid5(DECISION_NAMESPACE, natural_key))


def ensure_signal_id(signal: dict) -> str:
    current = str((signal or {}).get("signal_id") or "").strip()
    if current:
        return current
    return build_signal_id(
        (signal or {}).get("trade_date"),
        (signal or {}).get("code"),
        (signal or {}).get("strategy"),
    )
