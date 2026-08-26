"""Governance and audit controls for the read-only LLM sidecar."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from analysis.llm_adapter import (
    AdapterResult,
    LLM_OUTPUT_SCHEMA_VERSION,
    LLMProvider,
    run_adapter,
)
from analysis.llm_fact_pack import _canonical_hash
from analysis.llm_fact_pack_validator import validate_fact_pack


LLM_POLICY_VERSION = "llm_sidecar_policy_v1"
LLM_PROMPT_VERSION = "llm_grounded_prompt_v1"
FORBIDDEN_OUTPUT_PHRASES = {
    "保证收益", "稳赚", "必涨", "满仓买入", "重仓买入", "立即买入",
    "修改评分", "提升仓位上限", "新增候选股",
}
MAX_FINDINGS = 12
MAX_SUMMARY_CHARS = 2400


class PolicyViolation(ValueError):
    pass


@dataclass(frozen=True)
class GovernedResult:
    status: str
    run_id: str
    idempotency_key: str
    interpretation: dict[str, Any] | None
    error_message: str | None = None


def validate_fact_pack_integrity(pack: dict[str, Any]) -> None:
    expected = _canonical_hash(pack.get("facts") or {})
    if expected != pack.get("content_sha256"):
        raise PolicyViolation("fact_pack_content_hash_mismatch")
    if pack.get("status") == "blocked":
        raise PolicyViolation("fact_pack_blocked")
    policy = pack.get("policy") or {}
    if policy.get("mode") != "read_only_sidecar":
        raise PolicyViolation("fact_pack_policy_mode_invalid")
    gate = validate_fact_pack(pack)
    if gate["status"] == "blocked":
        raise PolicyViolation(
            "fact_pack_gate_blocked:" + ",".join(item["code"] for item in gate["errors"])
        )


def _warning_codes(pack: dict[str, Any]) -> set[str]:
    return {
        str(item.get("code"))
        for item in pack.get("limitations") or []
        if item.get("severity") in {"blocking", "warning"} and item.get("code")
    }


def validate_output_policy(output: dict[str, Any], pack: dict[str, Any]) -> None:
    findings = output.get("findings") or []
    if len(findings) > MAX_FINDINGS:
        raise PolicyViolation("too_many_findings")
    if len(str(output.get("summary") or "")) > MAX_SUMMARY_CHARS:
        raise PolicyViolation("summary_too_long")
    searchable = json.dumps(output, ensure_ascii=False)
    hit = sorted(phrase for phrase in FORBIDDEN_OUTPUT_PHRASES if phrase in searchable)
    if hit:
        raise PolicyViolation(f"forbidden_output_phrase:{hit}")
    acknowledged = {str(value) for value in output.get("limitations_acknowledged") or []}
    missing = _warning_codes(pack) - acknowledged
    if missing:
        raise PolicyViolation(f"limitations_not_acknowledged:{sorted(missing)}")


def idempotency_key(
    pack: dict[str, Any], provider: LLMProvider, task: str,
    comparison_pack: dict[str, Any] | None = None,
) -> str:
    raw = "|".join([
        str(pack.get("fact_pack_id")), task, str(provider.provider_name),
        str(provider.model_name), str((comparison_pack or {}).get("fact_pack_id") or ""),
        LLM_PROMPT_VERSION, LLM_POLICY_VERSION,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _insert_fact_pack(conn, pack: dict[str, Any]):
    facts = pack.get("facts") or {}
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO llm_fact_pack (
            fact_pack_id,schema_version,trade_date,as_of_date,
            content_sha256,status,facts_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (fact_pack_id) DO NOTHING
        """,
        (
            pack["fact_pack_id"], pack["schema_version"], facts["trade_date"],
            facts["as_of_date"], pack["content_sha256"], pack["status"],
            json.dumps(pack, ensure_ascii=False, default=str),
        ),
    )
    cur.execute(
        "SELECT content_sha256 FROM llm_fact_pack WHERE fact_pack_id=%s",
        (pack["fact_pack_id"],),
    )
    row = cur.fetchone()
    cur.close()
    if not row or row[0] != pack["content_sha256"]:
        raise PolicyViolation("persisted_fact_pack_hash_mismatch")


def _existing_success(conn, key: str) -> GovernedResult | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT run_id,response_json FROM llm_interpretation_run
        WHERE idempotency_key=%s AND status='success'
        """,
        (key,),
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return GovernedResult(
        status="reused", run_id=row[0], idempotency_key=key,
        interpretation=row[1],
    )


def _existing_running(conn, key: str) -> GovernedResult | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT run_id FROM llm_interpretation_run
        WHERE idempotency_key=%s AND status='running'
        """,
        (key,),
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return GovernedResult(
        status="in_progress", run_id=row[0], idempotency_key=key,
        interpretation=None,
    )


def _recover_stale_running(conn, key: str, stale_after_seconds: int = 1800) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE llm_interpretation_run
        SET status='failed',finished_at=CURRENT_TIMESTAMP,
            duration_seconds=EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-started_at)),
            error_message=COALESCE(error_message,'stale_running_recovered')
        WHERE idempotency_key=%s AND status='running'
          AND started_at < CURRENT_TIMESTAMP-(%s * INTERVAL '1 second')
        """,
        (key, int(stale_after_seconds)),
    )
    count = int(cur.rowcount or 0)
    cur.close()
    return count


def _start_run(conn, *, run_id: str, key: str, pack: dict[str, Any],
               provider: LLMProvider, task: str, request: dict[str, Any]):
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(MAX(attempt_no),0)+1 FROM llm_interpretation_run WHERE idempotency_key=%s",
        (key,),
    )
    attempt_no = int(cur.fetchone()[0])
    cur.execute(
        """
        INSERT INTO llm_interpretation_run (
            run_id,idempotency_key,attempt_no,fact_pack_id,task,provider_name,model_name,
            prompt_version,output_schema_version,policy_version,status,request_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running',%s::jsonb)
        """,
        (
            run_id, key, attempt_no, pack["fact_pack_id"], task, provider.provider_name,
            provider.model_name, LLM_PROMPT_VERSION, LLM_OUTPUT_SCHEMA_VERSION,
            LLM_POLICY_VERSION, json.dumps(request, ensure_ascii=False, default=str),
        ),
    )
    cur.close()


def _finish_run(conn, *, run_id: str, status: str, started: float,
                interpretation=None, error_message=None):
    evidence_count = sum(
        len(item.get("evidence_refs") or [])
        for item in (interpretation or {}).get("findings") or []
    )
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE llm_interpretation_run
        SET status=%s,response_json=%s::jsonb,evidence_count=%s,
            error_message=%s,finished_at=CURRENT_TIMESTAMP,duration_seconds=%s
        WHERE run_id=%s
        """,
        (
            status,
            json.dumps(interpretation, ensure_ascii=False, default=str)
            if interpretation is not None else None,
            evidence_count, error_message, time.monotonic() - started, run_id,
        ),
    )
    cur.close()


def execute_governed(
    pack: dict[str, Any],
    provider: LLMProvider,
    *,
    task: str = "explain",
    comparison_pack: dict[str, Any] | None = None,
    conn=None,
    persist: bool = False,
) -> GovernedResult:
    validate_fact_pack_integrity(pack)
    if comparison_pack is not None:
        validate_fact_pack_integrity(comparison_pack)
    key = idempotency_key(pack, provider, task, comparison_pack)
    run_id = str(uuid.uuid4())
    if persist and conn is None:
        raise ValueError("persist_requires_connection")
    if persist:
        _insert_fact_pack(conn, pack)
        if comparison_pack is not None:
            _insert_fact_pack(conn, comparison_pack)
        existing = _existing_success(conn, key)
        if existing:
            conn.commit()
            return existing
        _recover_stale_running(conn, key)
        active = _existing_running(conn, key)
        if active:
            conn.commit()
            return active
    started = time.monotonic()
    adapter_result: AdapterResult | None = None
    try:
        # Build once before audit insertion; run_adapter rebuilds the same
        # deterministic request for validation and provider execution.
        from analysis.llm_adapter import build_request
        request = build_request(pack, task, comparison_pack)
        if persist:
            _start_run(
                conn, run_id=run_id, key=key, pack=pack,
                provider=provider, task=task, request=request,
            )
            conn.commit()
        adapter_result = run_adapter(
            pack, provider, task=task, comparison_pack=comparison_pack,
        )
        validate_output_policy(adapter_result.interpretation, pack)
        if persist:
            _finish_run(
                conn, run_id=run_id, status="success", started=started,
                interpretation=adapter_result.interpretation,
            )
            conn.commit()
        return GovernedResult(
            status="success", run_id=run_id, idempotency_key=key,
            interpretation=adapter_result.interpretation,
        )
    except Exception as exc:
        status = "rejected" if isinstance(exc, (PolicyViolation, ValueError)) else "failed"
        if persist:
            try:
                _finish_run(
                    conn, run_id=run_id, status=status, started=started,
                    interpretation=(adapter_result.interpretation if adapter_result else None),
                    error_message=str(exc),
                )
                conn.commit()
            except Exception:
                conn.rollback()
        return GovernedResult(
            status=status, run_id=run_id, idempotency_key=key,
            interpretation=None, error_message=str(exc),
        )
