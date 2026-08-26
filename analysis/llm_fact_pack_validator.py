"""Pure quality gate for LLM fact packs; never reads or writes trading data."""
from __future__ import annotations

import math
from typing import Any

from analysis.llm_fact_pack import FACT_PACK_SCHEMA_VERSION, _canonical_hash
from analysis.trade_calendar import normalize_trade_date


ALLOWED_PACK_STATUS = {"ready", "degraded", "blocked"}
ALLOWED_EVALUATION_STATUS = {
    "pending", "success", "degraded", "blocked", "failed", "missing",
    "unavailable", "unknown", "deferred",
}
SECRET_KEY_PARTS = {"password", "secret", "token", "api_key", "dsn", "credential"}


def _walk(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            yield child, item
            yield from _walk(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child = f"{path}[{index}]"
            yield child, item
            yield from _walk(item, child)


def validate_fact_pack(pack: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def error(code, **context): errors.append({"code": code, **context})
    def warning(code, **context): warnings.append({"code": code, **context})

    if pack.get("schema_version") != FACT_PACK_SCHEMA_VERSION:
        error("schema_version_invalid")
    facts = pack.get("facts")
    if not isinstance(facts, dict):
        error("facts_missing")
        facts = {}
    if pack.get("content_sha256") != _canonical_hash(facts):
        error("content_hash_mismatch")
    try:
        trade_date = normalize_trade_date(facts.get("trade_date"))
        as_of_date = normalize_trade_date(facts.get("as_of_date"))
        if trade_date > as_of_date:
            error("as_of_before_trade_date")
    except Exception:
        error("date_invalid")

    if pack.get("status") not in ALLOWED_PACK_STATUS:
        error("pack_status_invalid", value=pack.get("status"))
    signals = facts.get("signals") or []
    if not isinstance(signals, list) or not signals:
        error("signals_missing")
        signals = []
    signal_ids = [item.get("signal_id") for item in signals]
    decision_ids = [item.get("decision_id") for item in signals]
    if any(not value for value in signal_ids):
        error("signal_identity_missing")
    if any(not value for value in decision_ids):
        error("decision_identity_missing")
    if len({value for value in signal_ids if value}) != len(signal_ids):
        error("signal_identity_duplicate")
    snapshot_rows = int(((pack.get("source_manifest") or {}).get("snapshots") or {}).get("rows") or 0)
    if snapshot_rows != len(signals):
        error("snapshot_identity_count_mismatch", signals=len(signals), snapshots=snapshot_rows)

    evaluation = facts.get("evaluation_status") or {}
    allowed_sections = ["market", "sentiment", "themes", "watchlist"]
    for horizon in ("t1", "t3"):
        status = (evaluation.get(horizon) or {}).get("status", "unknown")
        if status not in ALLOWED_EVALUATION_STATUS:
            error("evaluation_status_invalid", horizon=horizon, value=status)
        elif status == "success":
            allowed_sections.append(f"evaluation_{horizon}")
        elif status in {"pending", "deferred", "degraded", "unknown"}:
            warning(f"evaluation_{horizon}_{status}")
        else:
            error(f"evaluation_{horizon}_{status}")

    reconciliation = ((facts.get("pipeline") or {}).get("reconciliation") or {})
    if reconciliation.get("overall_status") in {"failed", "blocked"}:
        error("pipeline_reconciliation_failed")
    if not facts.get("report"):
        error("canonical_report_missing")

    for path, value in _walk(pack):
        key = path.rsplit(".", 1)[-1].lower()
        if any(part in key for part in SECRET_KEY_PARTS):
            error("secret_like_key_present", path=path)
        if isinstance(value, float) and not math.isfinite(value):
            error("non_finite_number", path=path)

    for limitation in pack.get("limitations") or []:
        target = errors if limitation.get("severity") == "blocking" else warnings
        target.append({"code": f"pack_limit:{limitation.get('code', 'unknown')}"})

    status = "blocked" if errors else ("degraded" if warnings else "ready")
    return {
        "status": status,
        "schema_version": FACT_PACK_SCHEMA_VERSION,
        "fact_pack_id": pack.get("fact_pack_id"),
        "errors": errors,
        "warnings": warnings,
        "allowed_sections": sorted(set(allowed_sections)),
        "counts": {"signals": len(signals), "snapshots": snapshot_rows},
    }
