"""Regression checks for the provider-neutral LLM adapter."""
from analysis.llm_adapter import (
    LLM_OUTPUT_SCHEMA_VERSION,
    build_request,
    run_adapter,
    validate_interpretation,
)


def _pack():
    return {
        "schema_version": "llm_fact_pack_v1",
        "fact_pack_id": "llmfp:test",
        "status": "degraded",
        "definitions": {"pending": "not mature"},
        "limitations": [{"code": "coverage", "severity": "warning"}],
        "facts": {
            "trade_date": "20260821", "as_of_date": "20260823",
            "market": {"score": 75.9}, "horizons": {}, "data_quality": {},
            "artifact_summary": {}, "evaluation_summary": {},
            "strategy_feedback": [], "correction_effectiveness": {},
            "pipeline": {"reconciliation": {}},
            "signals": [{
                "signal_id": "sig-1", "code": "000001", "name": "fixture",
                "strategy": "fixture", "final_layer": "observe",
                "primary_direction": "fixture", "decision": {},
                "evaluation": {"t1": {"state": "pending"}},
                "evidence_refs": [
                    "stock_signal:sig-1", "candidate_feature_snapshot:1",
                    "watchlist_evaluation_result:pending",
                ],
            }],
        },
    }


class FixtureProvider:
    provider_name = "fixture"
    model_name = "fixture-v1"

    def generate(self, request):
        output = {
            "schema_version": LLM_OUTPUT_SCHEMA_VERSION,
            "fact_pack_id": request["fact_pack_id"],
            "task": request["task"],
            "summary": "截至当前日期，T+1尚未自然到期。",
            "findings": [{
                "kind": "fact",
                "claim": "T+1处于pending，不能判断为失败。",
                "evidence_refs": ["stock_signal:sig-1"],
                "confidence": "high",
            }],
            "risks": [],
            "next_validations": ["目标交易日后复查"],
            "limitations_acknowledged": ["coverage"],
        }
        if request["task"] == "compare":
            output["comparison_fact_pack_id"] = request["comparison_fact_pack_id"]
        return output


def main():
    pack = _pack()
    request = build_request(pack, "explain")
    assert len(request["facts"]["signals"]) == 1
    result = run_adapter(pack, FixtureProvider(), task="explain")
    assert result.interpretation["findings"][0]["confidence"] == "high"

    invalid = FixtureProvider().generate(request)
    invalid["findings"][0]["evidence_refs"] = ["invented:1"]
    try:
        validate_interpretation(invalid, pack=pack, task="explain")
    except ValueError as exc:
        assert "finding_evidence_unknown" in str(exc)
    else:
        raise AssertionError("unknown evidence reference was accepted")

    comparison = _pack()
    comparison["fact_pack_id"] = "llmfp:comparison"
    compared = run_adapter(
        pack, FixtureProvider(), task="compare", comparison_pack=comparison,
    )
    assert compared.interpretation["comparison_fact_pack_id"] == "llmfp:comparison"
    print("[OK] LLM adapter regression check")


if __name__ == "__main__":
    main()
