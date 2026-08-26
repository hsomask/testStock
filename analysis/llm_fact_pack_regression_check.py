"""Pure regression checks for the LLM fact-pack contract."""
from analysis.llm_fact_pack import (
    FACT_PACK_SCHEMA_VERSION,
    _canonical_hash,
    _evaluation_state,
    _evaluation_data_status,
    _status_and_limitations,
)


def main():
    assert FACT_PACK_SCHEMA_VERSION == "llm_fact_pack_v1"
    assert _evaluation_state(mature=False, row_present=False, value=None, missing_reason=None) == "pending"
    assert _evaluation_state(mature=True, row_present=False, value=None, missing_reason=None) == "missing_record"
    assert _evaluation_state(mature=True, row_present=True, value=None, missing_reason="suspended") == "unavailable_price"
    assert _evaluation_state(mature=True, row_present=True, value=-0.02, missing_reason=None) == "success"

    signals = [{
        "evaluation": {
            "t1": {"state": "success"},
            "t3": {"state": "unavailable_price"},
        }
    }]
    evaluation_status = _evaluation_data_status(
        signals,
        {
            "t1_mature": True, "t3_mature": True,
            "t1_date": "20260821", "t3_date": "20260825",
        },
        "20260825",
    )
    status, limits = _status_and_limitations(
        trade_date="20260820", as_of_date="20260825",
        signal_rows=[{"snapshot_row_id": 1}], signals=signals,
        report={"id": 1}, quality={"ma_missing_ratio": 0.67},
        artifact_summary={"status": "available"},
        evaluation_status=evaluation_status,
    )
    assert status == "degraded"
    assert {item["code"] for item in limits} == {
        "universe_ma_coverage_limited",
        "mature_evaluation_price_unavailable",
        "historical_as_of_view",
    }
    assert _canonical_hash({"b": 2, "a": 1}) == _canonical_hash({"a": 1, "b": 2})
    print("[OK] LLM fact pack regression check")


if __name__ == "__main__":
    main()
