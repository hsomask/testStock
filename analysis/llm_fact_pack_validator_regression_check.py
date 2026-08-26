"""Regression checks for the independent LLM fact-pack quality gate."""
from copy import deepcopy

from analysis.llm_adapter_regression_check import _pack
from analysis.llm_fact_pack import _canonical_hash
from analysis.llm_fact_pack_validator import validate_fact_pack


def valid_pack():
    pack = _pack()
    pack["content_sha256"] = _canonical_hash(pack["facts"])
    return pack


def main():
    result = validate_fact_pack(valid_pack())
    assert result["status"] == "degraded"
    assert not result["errors"]
    assert "evaluation_t1" in result["allowed_sections"]
    assert "evaluation_t3" not in result["allowed_sections"]

    broken = deepcopy(valid_pack())
    broken["facts"]["signals"][0]["decision_id"] = None
    broken["content_sha256"] = _canonical_hash(broken["facts"])
    result = validate_fact_pack(broken)
    assert result["status"] == "blocked"
    assert any(item["code"] == "decision_identity_missing" for item in result["errors"])

    tampered = valid_pack()
    tampered["facts"]["market"]["score"] = 99
    result = validate_fact_pack(tampered)
    assert any(item["code"] == "content_hash_mismatch" for item in result["errors"])
    print("[OK] LLM fact pack validator regression check")


if __name__ == "__main__":
    main()
