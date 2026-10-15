"""Read existing daily artifacts without triggering business computation."""
from __future__ import annotations

import json
import re
import math
from datetime import datetime
from pathlib import Path


MARKET_FIELDS = (
    "score", "status", "summary", "total_amount", "up_count", "down_count",
    "limit_up", "limit_down",
)
STOCK_FIELDS = (
    "code", "name", "strategy", "close", "pct_chg", "primary_direction",
    "risk_level", "observe_low", "observe_high", "pressure_price",
    "invalid_price", "reason", "display_reason", "risk_reasons",
)
THEME_FIELDS = ("name", "level", "score", "reasons", "beginner_explain", "sustainability_risk")


def valid_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("Expected YYYYMMDD")
    datetime.strptime(value, "%Y%m%d")
    return value


def pick(value, fields):
    source = value if isinstance(value, dict) else {}
    return {key: public_value(source.get(key)) for key in fields}


def public_value(value):
    """Only scalar values and scalar lists cross the artifact boundary."""
    if isinstance(value, str):
        return value[:4000]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [public_value(item) for item in value[:50] if not isinstance(item, (dict, list))]
    return None


def board_scope(code):
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        return "unsupported"
    if code.startswith(("300", "301")):
        return "research_only"
    if code.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return "main_board"
    return "unsupported"


class DailyArtifactReader:
    """File-only reader; callers cannot choose arbitrary filenames."""

    def __init__(self, daily_dir):
        self.root = Path(daily_dir).resolve()

    def _read(self, prefix, day):
        path = self.root / f"{prefix}_{valid_date(day)}.json"
        if path.resolve().parent != self.root:
            return None, "invalid_path"
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                return None, "oversized"
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None, "missing"
        except (OSError, UnicodeError, ValueError):
            return None, "invalid"
        if not isinstance(value, dict):
            return None, "invalid"
        if value.get("trade_date") != day:
            return None, "date_mismatch"
        return value, "available"

    def dates(self):
        days = set()
        for path in self.root.glob("daily_summary_*.json"):
            day = path.stem.removeprefix("daily_summary_")
            try:
                days.add(valid_date(day))
            except ValueError:
                continue
        return sorted(days, reverse=True)

    def daily(self, day):
        valid_date(day)
        summary, summary_status = self._read("daily_summary", day)
        plan, plan_status = self._read("trade_plan", day)
        summary, plan = summary or {}, plan or {}
        decision = plan.get("decision")
        canonical = isinstance(decision, dict) and decision.get("schema_version") == "daily_decision_v1"
        decision = decision if canonical else {}
        execution = decision.get("execution") or {}
        mode = decision.get("mode") or {}
        restrictions = plan.get("market_restrictions") or {}
        allowed = (
            isinstance(execution, dict) and execution.get("execution_allowed") is True
            and isinstance(mode, dict) and mode.get("code") in {"defensive", "trial", "offensive"}
            and isinstance(restrictions, dict) and restrictions.get("allow_real_trade") is True
        )
        groups = decision.get("plans") if canonical else plan.get("plans")
        rows = []
        for layer, items in (groups.items() if isinstance(groups, dict) else []):
            if not isinstance(items, list):
                continue
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                row = pick(raw, STOCK_FIELDS)
                scope = board_scope(row["code"])
                row.update({
                    "source_layer": layer,
                    "board_scope": scope,
                    "price_reference_date": day,
                    "recommendation_eligible": bool(
                        allowed and scope == "main_board" and layer == "候选低吸"
                    ),
                })
                rows.append(row)
        themes = summary.get("themes")
        return {
            "schema_version": "web_review_daily_v1",
            "trade_date": day,
            "generated_at": public_value(summary.get("generated_at")),
            "sources": {"summary": summary_status, "trade_plan": plan_status},
            "decision_status": "canonical" if canonical else "unverified",
            "market": pick(summary.get("market"), MARKET_FIELDS),
            "sentiment": pick(summary.get("sentiment"), ("score", "stage")),
            "quality": pick(summary.get("quality"), ("confidence_score", "issues")),
            "themes": [pick(t, THEME_FIELDS) for t in themes if isinstance(t, dict)] if isinstance(themes, list) else [],
            "mode": pick(mode, ("code", "name", "summary")),
            "restrictions": pick(restrictions, ("allow_real_trade", "max_position_pct", "reasons")),
            "new_recommendations_allowed": bool(allowed),
            "candidates": rows,
            "events_status": "not_connected",
        }
