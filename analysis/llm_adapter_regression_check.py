"""Regression checks for the provider-neutral LLM adapter."""
from analysis.llm_adapter import (
    LLM_OUTPUT_SCHEMA_VERSION,
    build_request,
    run_adapter,
    validate_interpretation,
)
from analysis.llm_fact_pack import _canonical_hash


def _pack():
    pack = {
        "schema_version": "llm_fact_pack_v1",
        "fact_pack_id": "llmfp:test",
        "status": "degraded",
        "definitions": {"pending": "not mature"},
        "limitations": [{"code": "coverage", "severity": "warning"}],
        "facts": {
            "trade_date": "20260821", "as_of_date": "20260823",
            "market": {"score": 75.9}, "horizons": {}, "data_quality": {},
            "artifact_summary": {}, "evaluation_summary": {}, "report": {"id": 1},
            "evaluation_status": {
                "t1": {"status": "success"}, "t3": {"status": "pending"},
            },
            "strategy_feedback": [], "correction_effectiveness": {},
            "pipeline": {"reconciliation": {}},
            "signals": [{
                "signal_id": "sig-1", "decision_id": "dec-1", "code": "000001", "name": "fixture",
                "strategy": "fixture", "final_layer": "observe",
                "primary_direction": "fixture", "decision": {},
                "evaluation": {"t1": {"state": "pending"}},
                "evidence_refs": [
                    "stock_signal:sig-1", "candidate_feature_snapshot:1",
                    "watchlist_evaluation_result:pending",
                ],
            }],
        },
        "source_manifest": {"snapshots": {"rows": 1}},
    }
    pack["content_sha256"] = _canonical_hash(pack["facts"])
    return pack


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
                "fact_refs": [{
                    "path": "facts.market.score", "value": request["facts"]["market"]["score"],
                }],
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
    original_hash = pack["content_sha256"]
    request = build_request(pack, "explain")
    assert len(request["facts"]["signals"]) == 1
    assert request["quality_gate"]["status"] == "degraded"
    assert set(request["facts"]["signals"][0]["evaluation"]["t3"]) == {
        "state", "mature", "target_date",
    }
    assert pack["content_sha256"] == original_hash
    assert "t3" not in pack["facts"]["signals"][0]["evaluation"]
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

    wrong_value = FixtureProvider().generate(request)
    wrong_value["findings"][0]["fact_refs"] = [{"path": "facts.market.score", "value": 99}]
    try:
        validate_interpretation(wrong_value, pack=pack, task="explain")
    except ValueError as exc:
        assert "finding_fact_value_mismatch" in str(exc)
    else:
        raise AssertionError("invented fact value was accepted")

    comparison = _pack()
    comparison["fact_pack_id"] = "llmfp:comparison"
    compared = run_adapter(
        pack, FixtureProvider(), task="compare", comparison_pack=comparison,
    )
    assert compared.interpretation["comparison_fact_pack_id"] == "llmfp:comparison"
    print("[OK] LLM adapter regression check")


if __name__ == "__main__":
    main()
