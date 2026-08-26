"""Provider-neutral adapter for grounded LLM interpretation.

The adapter consumes only ``llm_fact_pack_v1`` and returns a validated JSON
document.  It has no database access and no dependency on trading modules.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from analysis.llm_fact_pack import FACT_PACK_SCHEMA_VERSION
from analysis.llm_fact_pack_validator import validate_fact_pack


LLM_OUTPUT_SCHEMA_VERSION = "llm_interpretation_v1"
ALLOWED_TASKS = {"explain", "summarize", "compare", "diagnose"}
ALLOWED_FINDING_KINDS = {"fact", "inference", "caveat"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
STATIC_EVIDENCE_REFS = {
    "fact:market", "fact:data_quality", "fact:report",
    "fact:evaluation_summary", "fact:strategy_feedback",
    "fact:correction_effectiveness", "fact:pipeline", "fact:horizons",
}


class LLMProvider(Protocol):
    provider_name: str
    model_name: str

    def generate(self, request: dict[str, Any]) -> dict[str, Any] | str:
        """Return a JSON object or a JSON string matching the output contract."""


@dataclass(frozen=True)
class AdapterResult:
    provider_name: str
    model_name: str
    request: dict[str, Any]
    interpretation: dict[str, Any]


def compact_fact_pack(pack: dict[str, Any]) -> dict[str, Any]:
    if pack.get("schema_version") != FACT_PACK_SCHEMA_VERSION:
        raise ValueError("unsupported_fact_pack_schema")
    facts = pack.get("facts") or {}
    signals = []
    for item in facts.get("signals") or []:
        signals.append({
            "signal_id": item.get("signal_id"),
            "code": item.get("code"),
            "name": item.get("name"),
            "strategy": item.get("strategy"),
            "final_layer": item.get("final_layer"),
            "primary_direction": item.get("primary_direction"),
            "decision": deepcopy(item.get("decision") or {}),
            "evaluation": deepcopy(item.get("evaluation") or {}),
            "evidence_refs": item.get("evidence_refs") or [],
        })
    pipeline = facts.get("pipeline") or {}
    artifact = facts.get("artifact_summary") or {}
    return {
        "schema_version": pack["schema_version"],
        "fact_pack_id": pack.get("fact_pack_id"),
        "status": pack.get("status"),
        "trade_date": facts.get("trade_date"),
        "as_of_date": facts.get("as_of_date"),
        "definitions": pack.get("definitions") or {},
        "limitations": pack.get("limitations") or [],
        "market": facts.get("market") or {},
        "horizons": facts.get("horizons") or {},
        "data_quality": facts.get("data_quality") or {},
        "themes": artifact.get("themes") or [],
        "risk_directions": artifact.get("risk_directions") or [],
        "signals": signals,
        "evaluation_summary": facts.get("evaluation_summary") or {},
        "evaluation_status": facts.get("evaluation_status") or {},
        "strategy_feedback": facts.get("strategy_feedback") or [],
        "correction_effectiveness": facts.get("correction_effectiveness") or {},
        "pipeline": {"reconciliation": pipeline.get("reconciliation") or {}},
    }


def build_request(
    pack: dict[str, Any], task: str = "explain",
    comparison_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if task not in ALLOWED_TASKS:
        raise ValueError(f"unsupported_task:{task}")
    gate = validate_fact_pack(pack)
    if pack.get("status") == "blocked" or gate["status"] == "blocked":
        raise ValueError("fact_pack_blocked")
    if task == "compare" and comparison_pack is None:
        raise ValueError("compare_requires_second_fact_pack")
    if comparison_pack is not None and comparison_pack.get("status") == "blocked":
        raise ValueError("comparison_fact_pack_blocked")
    compact = compact_fact_pack(pack)
    allowed = set(gate["allowed_sections"])
    for signal in compact["signals"]:
        evaluation = signal.get("evaluation") or {}
        for horizon in ("t1", "t3"):
            if f"evaluation_{horizon}" in allowed:
                continue
            current = evaluation.get(horizon) or {}
            evaluation[horizon] = {
                key: current.get(key) for key in ("state", "mature", "target_date")
            }
    if "evaluation_t1" not in allowed and "evaluation_t3" not in allowed:
        compact["evaluation_summary"] = {}
    request = {
        "request_schema_version": "llm_grounded_request_v1",
        "task": task,
        "fact_pack_id": pack.get("fact_pack_id"),
        "quality_gate": gate,
        "system_policy": {
            "role": "read_only_a_share_report_interpreter",
            "grounding": "Use only supplied facts. Never invent missing values.",
            "status_semantics": (
                "pending is not failure; unavailable_price is not success; "
                "signal count is not stock count"
            ),
            "forbidden": [
                "select new stocks", "change scores", "change layers",
                "change position limits", "create entry prices",
                "give personalized trading instructions", "write data",
            ],
            "output_language": "zh-CN",
        },
        "output_contract": {
            "schema_version": LLM_OUTPUT_SCHEMA_VERSION,
            "required_fields": [
                "schema_version", "fact_pack_id", "task", "summary",
                "findings", "risks", "next_validations",
                "limitations_acknowledged",
            ],
            "finding_contract": {
                "required": ["kind", "claim", "evidence_refs", "fact_refs", "confidence"],
                "kind": sorted(ALLOWED_FINDING_KINDS),
                "confidence": sorted(ALLOWED_CONFIDENCE),
                "fact_ref": {"required": ["path", "value"], "path_root": "facts"},
            },
        },
        "facts": compact,
    }
    if comparison_pack is not None:
        request["comparison_fact_pack_id"] = comparison_pack.get("fact_pack_id")
        request["comparison_facts"] = compact_fact_pack(comparison_pack)
    return request


def allowed_evidence_refs(
    pack: dict[str, Any], comparison_pack: dict[str, Any] | None = None,
) -> set[str]:
    refs = set(STATIC_EVIDENCE_REFS)
    for signal in (pack.get("facts") or {}).get("signals") or []:
        refs.update(str(value) for value in signal.get("evidence_refs") or [])
    if comparison_pack is not None:
        for signal in (comparison_pack.get("facts") or {}).get("signals") or []:
            refs.update(str(value) for value in signal.get("evidence_refs") or [])
    return refs


def _resolve_fact_path(pack: dict[str, Any], path: str) -> Any:
    if not isinstance(path, str) or not path.startswith("facts."):
        raise KeyError(path)
    value: Any = pack
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
            continue
        else:
            raise KeyError(path)
    return value


def _same_fact_value(expected: Any, claimed: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(claimed, (int, float)):
        return abs(float(expected) - float(claimed)) <= 1e-9
    return expected == claimed


def validate_interpretation(
    output: dict[str, Any] | str,
    *,
    pack: dict[str, Any],
    task: str,
    comparison_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError as exc:
            raise ValueError("model_output_not_json") from exc
    if not isinstance(output, dict):
        raise ValueError("model_output_not_object")
    required = {
        "schema_version", "fact_pack_id", "task", "summary", "findings",
        "risks", "next_validations", "limitations_acknowledged",
    }
    missing = required - set(output)
    if missing:
        raise ValueError(f"model_output_missing_fields:{sorted(missing)}")
    if output["schema_version"] != LLM_OUTPUT_SCHEMA_VERSION:
        raise ValueError("model_output_schema_mismatch")
    if output["fact_pack_id"] != pack.get("fact_pack_id"):
        raise ValueError("model_output_fact_pack_mismatch")
    if output["task"] != task:
        raise ValueError("model_output_task_mismatch")
    if task == "compare" and output.get("comparison_fact_pack_id") != (comparison_pack or {}).get("fact_pack_id"):
        raise ValueError("model_output_comparison_fact_pack_mismatch")
    if not isinstance(output["summary"], str) or not output["summary"].strip():
        raise ValueError("model_output_summary_empty")
    if not isinstance(output["findings"], list):
        raise ValueError("model_output_findings_not_list")
    allowed_refs = allowed_evidence_refs(pack, comparison_pack)
    for index, finding in enumerate(output["findings"]):
        if not isinstance(finding, dict):
            raise ValueError(f"finding_not_object:{index}")
        if finding.get("kind") not in ALLOWED_FINDING_KINDS:
            raise ValueError(f"finding_kind_invalid:{index}")
        if finding.get("confidence") not in ALLOWED_CONFIDENCE:
            raise ValueError(f"finding_confidence_invalid:{index}")
        if not str(finding.get("claim") or "").strip():
            raise ValueError(f"finding_claim_empty:{index}")
        refs = finding.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"finding_evidence_missing:{index}")
        unknown = {str(ref) for ref in refs} - allowed_refs
        if unknown:
            raise ValueError(f"finding_evidence_unknown:{index}:{sorted(unknown)}")
        fact_refs = finding.get("fact_refs")
        if finding.get("kind") in {"fact", "inference"} and not fact_refs:
            raise ValueError(f"finding_fact_refs_missing:{index}")
        if fact_refs is not None and not isinstance(fact_refs, list):
            raise ValueError(f"finding_fact_refs_not_list:{index}")
        for ref_index, ref in enumerate(fact_refs or []):
            if not isinstance(ref, dict) or "path" not in ref or "value" not in ref:
                raise ValueError(f"finding_fact_ref_invalid:{index}:{ref_index}")
            source_pack = comparison_pack if ref.get("source") == "comparison" else pack
            if source_pack is None:
                raise ValueError(f"finding_fact_ref_source_invalid:{index}:{ref_index}")
            try:
                actual = _resolve_fact_path(source_pack, ref["path"])
            except KeyError as exc:
                raise ValueError(f"finding_fact_path_unknown:{index}:{ref_index}") from exc
            if not _same_fact_value(actual, ref["value"]):
                raise ValueError(f"finding_fact_value_mismatch:{index}:{ref_index}")
    for field in ("risks", "next_validations", "limitations_acknowledged"):
        if not isinstance(output[field], list):
            raise ValueError(f"model_output_{field}_not_list")
    return output


def run_adapter(
    pack: dict[str, Any],
    provider: LLMProvider,
    *,
    task: str = "explain",
    comparison_pack: dict[str, Any] | None = None,
) -> AdapterResult:
    request = build_request(pack, task, comparison_pack)
    raw = provider.generate(request)
    interpretation = validate_interpretation(
        raw, pack=pack, task=task, comparison_pack=comparison_pack,
    )
    return AdapterResult(
        provider_name=str(provider.provider_name),
        model_name=str(provider.model_name),
        request=request,
        interpretation=interpretation,
    )
