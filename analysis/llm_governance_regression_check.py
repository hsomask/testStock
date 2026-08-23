"""Regression checks for LLM sidecar governance."""
from analysis.llm_adapter_regression_check import FixtureProvider, _pack
from analysis.llm_fact_pack import _canonical_hash
from analysis.llm_governance import (
    execute_governed,
    idempotency_key,
    validate_fact_pack_integrity,
)


class UnsafeProvider(FixtureProvider):
    def generate(self, request):
        output = super().generate(request)
        output["summary"] = "立即买入并保证收益"
        return output


def main():
    pack = _pack()
    pack["content_sha256"] = _canonical_hash(pack["facts"])
    pack["policy"] = {"mode": "read_only_sidecar"}
    pack["limitations"] = [{"code": "coverage", "severity": "warning"}]
    validate_fact_pack_integrity(pack)

    provider = FixtureProvider()
    assert idempotency_key(pack, provider, "explain") == idempotency_key(
        pack, provider, "explain"
    )
    result = execute_governed(pack, provider, task="explain")
    assert result.status == "success"

    unsafe = execute_governed(pack, UnsafeProvider(), task="explain")
    assert unsafe.status == "rejected"
    assert "forbidden_output_phrase" in unsafe.error_message

    tampered = dict(pack)
    tampered["facts"] = dict(pack["facts"], trade_date="20990101")
    try:
        validate_fact_pack_integrity(tampered)
    except ValueError as exc:
        assert "content_hash_mismatch" in str(exc)
    else:
        raise AssertionError("tampered fact pack was accepted")
    print("[OK] LLM governance regression check")


if __name__ == "__main__":
    main()
