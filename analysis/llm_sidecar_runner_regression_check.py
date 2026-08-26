"""Regression checks for the explicit LLM sidecar entry point."""
from pathlib import Path
from tempfile import TemporaryDirectory

from analysis import llm_sidecar_runner as runner
from analysis.llm_adapter_regression_check import FixtureProvider, _pack
from analysis.llm_fact_pack import _canonical_hash


def main():
    pack = _pack()
    pack["content_sha256"] = _canonical_hash(pack["facts"])
    pack["policy"] = {"mode": "read_only_sidecar"}
    pack["fact_pack_id"] = "llmfp:fixture"
    original_build, original_save = runner.build_fact_pack, runner.save_fact_pack
    original_fact_pack_dir = runner.FACT_PACK_DIR
    with TemporaryDirectory() as temp:
        try:
            runner.build_fact_pack = lambda *_a, **_k: pack
            runner.save_fact_pack = lambda *_a, **_k: Path(temp) / "fact.json"
            runner.FACT_PACK_DIR = Path(temp)
            validated = runner.run_sidecar("20260821")
            assert validated["status"] == "validated"
            assert validated["llm_called"] is False

            interpreted = runner.run_sidecar("20260821", provider=FixtureProvider())
            assert interpreted["status"] == "success"
            assert interpreted["llm_called"] is True

            pack["facts"]["signals"][0]["decision_id"] = None
            pack["content_sha256"] = _canonical_hash(pack["facts"])
            class MustNotRun(FixtureProvider):
                def generate(self, _request):
                    raise AssertionError("blocked fact pack reached provider")
            blocked = runner.run_sidecar("20260821", provider=MustNotRun())
            assert blocked["status"] == "blocked"
            assert blocked["llm_called"] is False
        finally:
            runner.build_fact_pack, runner.save_fact_pack = original_build, original_save
            runner.FACT_PACK_DIR = original_fact_pack_dir
    print("[OK] LLM sidecar runner regression check")


if __name__ == "__main__":
    main()
