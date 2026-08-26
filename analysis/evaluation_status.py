"""Canonical Evaluation result-status contract.

Execution status answers whether a task ran.  Data status answers whether the
result is mature and complete enough for reconciliation, backfill and LLM use.
Keeping the two dimensions separate prevents a successful process from making
partial Evaluation data look complete.
"""
from __future__ import annotations

from typing import Any


DEFAULT_EVALUATION_COVERAGE_THRESHOLD = 0.90
FAILED_EXECUTION_STATUSES = {"failed", "blocked", "error", "timeout"}
DEFERRED_EXECUTION_STATUSES = {"pending", "running", "deferred"}


def resolve_evaluation_status(
    *,
    mature: bool,
    target_date: str | None,
    as_of_date: str,
    eligible_count: int,
    evaluated_count: int,
    coverage: float | None = None,
    execution_status: str | None = None,
    minimum_coverage: float = DEFAULT_EVALUATION_COVERAGE_THRESHOLD,
) -> dict[str, Any]:
    """Return one normalized, serializable Evaluation data-status result."""
    eligible = max(0, int(eligible_count or 0))
    evaluated = max(0, min(int(evaluated_count or 0), eligible))
    normalized_coverage = (
        float(coverage) if coverage is not None
        else (evaluated / eligible if eligible else 0.0)
    )
    normalized_coverage = max(0.0, min(normalized_coverage, 1.0))
    threshold = float(minimum_coverage)
    execution = str(execution_status or "unknown").strip().lower()

    if execution in FAILED_EXECUTION_STATUSES:
        status, reason = "failed", "evaluation_execution_failed"
    elif not mature:
        status, reason = "pending", "target_not_mature"
    elif eligible == 0:
        status, reason = "missing", "mature_no_eligible_signals"
    elif evaluated == 0:
        # On the target trading day the nightly market-data/Evaluation jobs may
        # not have run yet.  Only call it missing from the next trading date.
        if target_date and str(target_date) == str(as_of_date):
            status, reason = "deferred", "target_day_data_not_ready"
        elif execution in DEFERRED_EXECUTION_STATUSES:
            status, reason = "deferred", "evaluation_execution_deferred"
        else:
            status, reason = "missing", "mature_no_evaluation"
    elif normalized_coverage < threshold:
        status, reason = "degraded", "mature_low_coverage"
    else:
        status, reason = "success", "coverage_sufficient"

    return {
        "execution_status": execution,
        "status": status,
        "mature": bool(mature),
        "target_date": target_date,
        "as_of_date": str(as_of_date),
        "eligible_count": eligible,
        "evaluated_count": evaluated,
        "missing_count": max(eligible - evaluated, 0),
        "coverage": round(normalized_coverage, 6),
        "threshold": threshold,
        "reason_code": reason,
    }


def should_backfill_evaluation(status: dict[str, Any]) -> bool:
    """Return whether a mature result belongs in the repair queue."""
    return status.get("reason_code") in {
        "mature_low_coverage",
        "mature_no_evaluation",
        "evaluation_execution_failed",
    }
