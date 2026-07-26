"""Phase-gate audit for behavior changes between HEAD and the working tree.

The audit is read-only. It proves source equivalence for the raw selector and,
when PostgreSQL is available, measures downstream behavior changes on stored
historical signals and candidate snapshots.

Run:
  python -m analysis.behavior_equivalence_audit
  python -m analysis.behavior_equivalence_audit --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import psycopg2

from analysis.daily_decision import FINAL_LAYERS, normalize_final_plans
from analysis.limitup_metrics import NEAR_LIMIT_UP_PROXIMITY, is_near_limit_up
from analysis.strategy_feedback import _score_for, _status_for
from data.config import DATABASE_DSN


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "behavior_policy.json"
LAYER_PRIORITY = {layer: index for index, layer in enumerate(FINAL_LAYERS)}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _normalize_source(payload: bytes) -> bytes:
    """Ignore platform line endings while preserving all Python source tokens."""
    return payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _head_file(relative_path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=ROOT,
    )


def audit_selector_source() -> dict:
    relative_path = "analysis/selector.py"
    current = _normalize_source((ROOT / relative_path).read_bytes())
    head = _normalize_source(_head_file(relative_path))
    return {
        "status": "pass" if current == head else "fail",
        "path": relative_path,
        "head_sha256": _sha256(head),
        "working_tree_sha256": _sha256(current),
        "behavior_claim": "raw selector formulas, thresholds and ordering are source-identical",
    }


def _connect_readonly():
    if not DATABASE_DSN:
        return None
    conn = psycopg2.connect(DATABASE_DSN)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _load_policy() -> dict:
    if not POLICY_PATH.exists():
        return {}
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _change_accepted(policy: dict, name: str) -> bool:
    item = (policy.get("accepted_changes") or {}).get(name) or {}
    return bool(item.get("accepted"))


def _legacy_trade_plan_near_limit(pct_chg: float, code: str) -> bool:
    threshold = 19.0 if code.startswith(("300", "301", "688")) else 9.5
    return pct_chg >= threshold


def _legacy_correction_near_limit(pct_chg: float) -> bool:
    return pct_chg >= 9.0


def audit_near_limit_behavior(cur, policy: dict) -> dict:
    cur.execute(
        """
        SELECT trade_date, code, name, pct_chg
        FROM stock_signal
        WHERE pct_chg IS NOT NULL
        ORDER BY trade_date, code, strategy
        """
    )
    rows = cur.fetchall()
    trade_plan_differences = []
    correction_differences = []
    for trade_date, code, name, pct_chg in rows:
        code = str(code or "")
        name = str(name or "")
        pct_chg = float(pct_chg)
        canonical = is_near_limit_up(pct_chg, code, name)
        legacy_trade_plan = _legacy_trade_plan_near_limit(pct_chg, code)
        legacy_correction = _legacy_correction_near_limit(pct_chg)
        item = {
            "trade_date": str(trade_date),
            "code": code,
            "name": name,
            "pct_chg": pct_chg,
        }
        if legacy_trade_plan != canonical:
            trade_plan_differences.append(
                {
                    **item,
                    "legacy": legacy_trade_plan,
                    "canonical": canonical,
                }
            )
        if legacy_correction != canonical:
            correction_differences.append(
                {
                    **item,
                    "legacy": legacy_correction,
                    "canonical": canonical,
                }
            )
    accepted = _change_accepted(policy, "board_aware_near_limit")
    configured = (
        (policy.get("accepted_changes") or {})
        .get("board_aware_near_limit", {})
        .get("proximity")
    )
    policy_matches_code = configured is not None and abs(
        float(configured) - NEAR_LIMIT_UP_PROXIMITY
    ) < 1e-12
    return {
        "status": (
            "accepted_change"
            if accepted and policy_matches_code
            else "review_required"
            if trade_plan_differences or correction_differences
            else "pass"
        ),
        "policy_matches_code": policy_matches_code,
        "configured_proximity": NEAR_LIMIT_UP_PROXIMITY,
        "historical_signal_rows": len(rows),
        "trade_plan_difference_count": len(trade_plan_differences),
        "trade_plan_distinct_date_stock_count": len(
            {(item["trade_date"], item["code"]) for item in trade_plan_differences}
        ),
        "correction_difference_count": len(correction_differences),
        "correction_distinct_date_stock_count": len(
            {(item["trade_date"], item["code"]) for item in correction_differences}
        ),
        "trade_plan_examples": trade_plan_differences[:10],
        "correction_examples": correction_differences[:10],
        "reason": "canonical board-aware threshold replaces two inconsistent legacy definitions",
    }


def _legacy_render_resolution(raw_plans: dict) -> dict:
    """Reproduce the old renderer's name dedup and cross-layer precedence."""
    deduped = {}
    for layer in FINAL_LAYERS:
        by_name = {}
        for item in raw_plans.get(layer, []) or []:
            key = item.get("name", item.get("code", ""))
            if key in by_name:
                strategy = str(item.get("strategy", "") or "")
                existing = by_name[key]
                if strategy and strategy not in str(existing.get("strategy", "")):
                    existing["strategy"] = (
                        str(existing.get("strategy", "")) + " / " + strategy
                    ).strip(" /")
            else:
                by_name[key] = dict(item)
        deduped[layer] = list(by_name.values())

    resolved = {}
    for layer in reversed(FINAL_LAYERS):
        for item in deduped[layer]:
            key = str(item.get("code", "") or item.get("name", ""))
            if key and key not in resolved:
                resolved[key] = layer
    return resolved


def _canonical_resolution(raw_plans: dict) -> dict:
    normalized = normalize_final_plans(raw_plans)
    resolved = {}
    for layer, items in normalized.items():
        for item in items:
            key = str(item.get("code", "") or item.get("name", ""))
            if key:
                resolved[key] = layer
    return resolved


def audit_final_layer_resolution(cur) -> dict:
    cur.execute(
        """
        SELECT id, trade_date, code, name, strategy, rule_layer
        FROM candidate_feature_snapshot
        ORDER BY trade_date, id
        """
    )
    by_date = defaultdict(lambda: {layer: [] for layer in FINAL_LAYERS})
    layer_sets = defaultdict(set)
    row_count = 0
    for _, trade_date, code, name, strategy, rule_layer in cur.fetchall():
        if rule_layer not in LAYER_PRIORITY:
            continue
        row_count += 1
        item = {
            "code": str(code or ""),
            "name": str(name or ""),
            "strategy": str(strategy or ""),
            "final_layer": rule_layer,
        }
        by_date[str(trade_date)][rule_layer].append(item)
        layer_sets[(str(trade_date), str(code or ""))].add(rule_layer)

    differences = []
    for trade_date, raw_plans in sorted(by_date.items()):
        legacy = _legacy_render_resolution(raw_plans)
        canonical = _canonical_resolution(raw_plans)
        for key in sorted(set(legacy) | set(canonical)):
            if legacy.get(key) != canonical.get(key):
                differences.append(
                    {
                        "trade_date": trade_date,
                        "stock_key": key,
                        "legacy_layer": legacy.get(key),
                        "canonical_layer": canonical.get(key),
                    }
                )
    multi_layer_count = sum(1 for layers in layer_sets.values() if len(layers) > 1)
    return {
        "status": "pass" if not differences else "fail",
        "snapshot_rows": row_count,
        "snapshot_dates": len(by_date),
        "legacy_multi_layer_date_stock_count": multi_layer_count,
        "resolved_layer_difference_count": len(differences),
        "examples": differences[:10],
        "behavior_claim": (
            "moving precedence from renderer to DailyDecision preserves the old "
            "displayed final layer while eliminating ambiguous stored layers"
        ),
    }


def _feedback_stats(rows: list[dict], *, legacy: bool) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["strategy"]].append(row)
    result = {}
    for strategy, items in grouped.items():
        count = len(items)
        win_rate = sum(item["next_1d_return"] > 0 for item in items) / count
        avg_return = sum(item["next_1d_return"] for item in items) / count
        max_values = [item["max_3d_return"] for item in items if item["max_3d_return"] is not None]
        dd_values = [item["max_3d_drawdown"] for item in items if item["max_3d_drawdown"] is not None]
        avg_max = sum(max_values) / len(max_values) if max_values else None
        avg_dd = sum(dd_values) / len(dd_values) if dd_values else None
        if legacy:
            strong_rate = sum(
                item["feedback_label"] == "strong_follow"
                or item["next_1d_return"] >= 0.03
                or (item["max_3d_return"] is not None and item["max_3d_return"] >= 0.06)
                for item in items
            ) / count
            failed_rate = sum(
                item["feedback_label"] == "failed"
                or item["next_1d_return"] <= -0.03
                or (
                    item["max_3d_drawdown"] is not None
                    and item["max_3d_drawdown"] <= -0.05
                )
                for item in items
            ) / count
            status, _ = _status_for(count, win_rate, avg_return, failed_rate, avg_dd)
            score = _score_for(win_rate, avg_return, strong_rate, failed_rate, avg_dd)
        else:
            strong_rate = sum(
                item["feedback_label"] == "strong_follow"
                or item["next_1d_return"] >= 0.03
                for item in items
            ) / count
            failed_rate = sum(
                item["feedback_label"] == "failed"
                or item["next_1d_return"] <= -0.03
                for item in items
            ) / count
            status, _ = _status_for(count, win_rate, avg_return, failed_rate, None)
            score = _score_for(win_rate, avg_return, strong_rate, failed_rate, None)
        result[strategy] = {
            "sample_count": count,
            "status": status,
            "score": score,
            "strong_rate": round(strong_rate, 6),
            "failed_rate": round(failed_rate, 6),
            "avg_max_3d_return": avg_max,
            "avg_max_3d_drawdown": avg_dd,
        }
    return result


def audit_feedback_behavior(cur, policy: dict, window_days: int = 5) -> dict:
    cur.execute(
        """
        SELECT DISTINCT as_of_date
        FROM canonical_daily_evaluation_result
        WHERE eval_mode = 'daily'
        ORDER BY as_of_date DESC
        LIMIT %s
        """,
        (window_days,),
    )
    dates = [row[0] for row in cur.fetchall()]
    if not dates:
        return {"status": "not_reproducible", "reason": "no canonical evaluation rows"}
    cur.execute(
        """
        SELECT strategy, next_1d_return, max_3d_return, max_3d_drawdown,
               feedback_label
        FROM canonical_daily_evaluation_result
        WHERE eval_mode = 'daily'
          AND as_of_date = ANY(%s)
          AND next_1d_return IS NOT NULL
          AND COALESCE(strategy, '') <> ''
        """,
        (dates,),
    )
    rows = [
        {
            "strategy": row[0],
            "next_1d_return": float(row[1]),
            "max_3d_return": float(row[2]) if row[2] is not None else None,
            "max_3d_drawdown": float(row[3]) if row[3] is not None else None,
            "feedback_label": row[4],
        }
        for row in cur.fetchall()
    ]
    legacy = _feedback_stats(rows, legacy=True)
    canonical = _feedback_stats(rows, legacy=False)
    differences = []
    status_differences = []
    score_only_differences = []
    for strategy in sorted(set(legacy) | set(canonical)):
        before = legacy.get(strategy)
        after = canonical.get(strategy)
        if not before or not after:
            continue
        if before["status"] != after["status"] or before["score"] != after["score"]:
            item = {
                "strategy": strategy,
                "legacy_status": before["status"],
                "canonical_status": after["status"],
                "legacy_score": before["score"],
                "canonical_score": after["score"],
            }
            differences.append(item)
            if before["status"] != after["status"]:
                status_differences.append(item)
            else:
                score_only_differences.append(item)
    accepted = _change_accepted(policy, "t1_t3_isolation")
    return {
        "status": "accepted_change" if accepted else "review_required" if differences else "pass",
        "evaluation_dates": dates,
        "sample_rows": len(rows),
        "strategy_count": len(canonical),
        "strategy_status_or_score_difference_count": len(differences),
        "strategy_status_difference_count": len(status_differences),
        "strategy_score_only_difference_count": len(score_only_differences),
        "examples": differences[:10],
        "reason": "T+3 outcomes were removed from the T+1 feedback decision",
    }


def run_audit() -> dict:
    policy = _load_policy()
    market_facts_accepted = _change_accepted(policy, "canonical_market_facts")
    result = {
        "schema_version": "behavior_equivalence_audit_v1",
        "baseline": "git HEAD",
        "candidate": "working tree",
        "behavior_policy": {
            "status": "loaded" if policy else "missing",
            "path": str(POLICY_PATH.relative_to(ROOT)),
            "approved_at": policy.get("approved_at"),
            "approved_by": policy.get("approved_by"),
        },
        "selector_source": audit_selector_source(),
        "market_score_replay": {
            "status": "accepted_with_limitation"
            if market_facts_accepted
            else "not_reproducible",
            "reason": (
                "the database has no full-market historical stock snapshot; "
                "source scoring formula is unchanged, but corrected limit-up facts "
                "can change the score near boundaries"
            ),
        },
    }
    conn = _connect_readonly()
    if conn is None:
        result["database_audits"] = {
            "status": "not_run",
            "reason": "DATABASE_DSN is not configured",
        }
    else:
        try:
            cur = conn.cursor()
            result["near_limit_behavior"] = audit_near_limit_behavior(cur, policy)
            result["final_layer_resolution"] = audit_final_layer_resolution(cur)
            result["feedback_behavior"] = audit_feedback_behavior(cur, policy)
            cur.close()
        finally:
            conn.close()

    statuses = [
        value.get("status")
        for value in result.values()
        if isinstance(value, dict) and value.get("status")
    ]
    if "fail" in statuses:
        result["gate_status"] = "fail"
    elif "review_required" in statuses or "not_reproducible" in statuses:
        result["gate_status"] = "review_required"
    else:
        result["gate_status"] = "pass"
    return result


def _print_human(result: dict) -> None:
    print(f"gate_status: {result['gate_status']}")
    selector = result["selector_source"]
    print(f"selector_source: {selector['status']}")
    market = result["market_score_replay"]
    print(f"market_score_replay: {market['status']} - {market['reason']}")
    for key in ("near_limit_behavior", "final_layer_resolution", "feedback_behavior"):
        item = result.get(key)
        if not item:
            continue
        print(f"{key}: {item['status']}")
        for metric, value in item.items():
            if metric.endswith("_count") or metric in {
                "historical_signal_rows",
                "snapshot_rows",
                "snapshot_dates",
                "sample_rows",
                "strategy_count",
            }:
                print(f"  {metric}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()
    result = run_audit()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()
