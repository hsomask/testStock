"""Explicit, non-blocking entry point for the governed LLM sidecar."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

import psycopg2

from analysis.llm_fact_pack import FACT_PACK_DIR, build_fact_pack, save_fact_pack
from analysis.llm_fact_pack_validator import validate_fact_pack
from analysis.llm_governance import execute_governed
from data.config import DATABASE_DSN


def load_provider(spec: str):
    if ":" not in spec:
        raise ValueError("provider_spec_must_be_module:attribute")
    module_name, attribute = spec.split(":", 1)
    provider = getattr(importlib.import_module(module_name), attribute)
    return provider() if isinstance(provider, type) else provider


def run_sidecar(
    trade_date: str, *, as_of_date: str | None = None, provider=None,
    task: str = "explain", persist: bool = False, conn=None,
) -> dict:
    pack = build_fact_pack(trade_date, as_of_date, conn=conn)
    gate = validate_fact_pack(pack)
    fact_path = save_fact_pack(pack)
    result = {
        "status": "validated" if gate["status"] != "blocked" else "blocked",
        "fact_pack_id": pack["fact_pack_id"],
        "fact_pack_path": str(fact_path),
        "gate": gate,
        "llm_called": False,
    }
    if gate["status"] == "blocked" or provider is None:
        return result
    own_conn = persist and conn is None
    db = conn
    if own_conn:
        db = psycopg2.connect(DATABASE_DSN)
    try:
        governed = execute_governed(
            pack, provider, task=task, conn=db, persist=persist,
        )
        result.update({
            "status": governed.status,
            "run_id": governed.run_id,
            "idempotency_key": governed.idempotency_key,
            "interpretation": governed.interpretation,
            "error_message": governed.error_message,
            "llm_called": governed.status not in {"reused", "in_progress"},
        })
        if governed.interpretation is not None:
            out_dir = Path(FACT_PACK_DIR) / "interpretations"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"interpretation_{pack['fact_pack_id'].replace(':', '_')}.json"
            out_path.write_text(
                json.dumps(governed.interpretation, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result["interpretation_path"] = str(out_path)
        return result
    finally:
        if own_conn and db is not None:
            db.close()


def main():
    parser = argparse.ArgumentParser(description="Run governed LLM sidecar")
    parser.add_argument("--date", required=True)
    parser.add_argument("--as-of")
    parser.add_argument("--task", default="explain", choices=["explain", "summarize", "diagnose"])
    parser.add_argument("--provider", help="Python provider as module:attribute; omitted means validate-only")
    parser.add_argument("--persist", action="store_true", help="Persist immutable pack and audit run")
    args = parser.parse_args()
    provider = load_provider(args.provider) if args.provider else None
    result = run_sidecar(
        args.date, as_of_date=args.as_of, provider=provider,
        task=args.task, persist=args.persist,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result["status"] in {"blocked", "failed", "rejected"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
