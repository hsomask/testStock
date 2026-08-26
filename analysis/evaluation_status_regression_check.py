"""Regression checks for the canonical Evaluation data-status contract."""
from analysis.evaluation_status import (
    resolve_evaluation_status,
    should_backfill_evaluation,
)


def _resolve(**overrides):
    values = {
        "mature": True,
        "target_date": "20260820",
        "as_of_date": "20260821",
        "eligible_count": 25,
        "evaluated_count": 25,
    }
    values.update(overrides)
    return resolve_evaluation_status(**values)


def main():
    assert _resolve(mature=False)["status"] == "pending"
    assert _resolve(evaluated_count=25)["status"] == "success"
    assert _resolve(evaluated_count=24)["status"] == "success"
    low = _resolve(eligible_count=26, evaluated_count=18)
    assert low["status"] == "degraded" and low["missing_count"] == 8
    assert low["reason_code"] == "mature_low_coverage"
    assert should_backfill_evaluation(low)
    missing = _resolve(evaluated_count=0)
    assert missing["status"] == "missing" and should_backfill_evaluation(missing)
    same_day = _resolve(
        target_date="20260821", as_of_date="20260821", evaluated_count=0,
    )
    assert same_day["status"] == "deferred"
    assert not should_backfill_evaluation(same_day)
    failed = _resolve(execution_status="failed")
    assert failed["status"] == "failed" and should_backfill_evaluation(failed)
    print("[OK] Evaluation status regression check")


if __name__ == "__main__":
    main()
