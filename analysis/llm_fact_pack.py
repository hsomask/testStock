"""Build a versioned, read-only fact pack for an LLM sidecar.

This module does not call a model and does not mutate trading facts.  Its job is
to turn the canonical signal/snapshot/evaluation lineage into a bounded JSON
contract with explicit maturity, provenance and limitations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from analysis.correction_effectiveness import build_correction_effectiveness
from analysis.evaluation_time import resolve_evaluation_horizons
from analysis.evaluation_status import resolve_evaluation_status
from analysis.trade_calendar import normalize_trade_date
from data.config import DATABASE_DSN, REPORT_DIR


FACT_PACK_SCHEMA_VERSION = "llm_fact_pack_v1"
FACT_PACK_DIR = Path(REPORT_DIR) / "llm"


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row_dict(row: dict[str, Any] | None) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in (row or {}).items()}


def _fetch_one(cur, sql: str, params=()) -> dict[str, Any]:
    cur.execute(sql, params)
    return _row_dict(cur.fetchone())


def _fetch_all(cur, sql: str, params=()) -> list[dict[str, Any]]:
    cur.execute(sql, params)
    return [_row_dict(row) for row in cur.fetchall()]


def _load_daily_summary(trade_date: str, report_dir: Path) -> dict[str, Any]:
    path = report_dir / "daily" / f"daily_summary_{trade_date}.json"
    if not path.exists():
        return {"status": "unavailable", "reason": "daily_summary_file_missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "unavailable", "reason": f"daily_summary_invalid:{exc}"}
    actual = normalize_trade_date(data.get("trade_date"))
    if actual != trade_date:
        return {"status": "unavailable", "reason": "daily_summary_date_mismatch"}
    return {
        "status": "available",
        "source": str(path),
        "generated_at": data.get("generated_at"),
        "themes": data.get("themes") or [],
        "risk_directions": data.get("risk_directions") or [],
    }


def _evaluation_state(
    *, mature: bool, row_present: bool, value: Any, missing_reason: Any,
) -> str:
    if not mature:
        return "pending"
    if not row_present:
        return "missing_record"
    if value is not None:
        return "success"
    if missing_reason:
        return "unavailable_price"
    return "missing_value"


def _signal_facts(rows: list[dict[str, Any]], horizons: dict[str, Any]):
    facts = []
    for row in rows:
        feature_json = row.pop("feature_json", None) or {}
        if isinstance(feature_json, str):
            try:
                feature_json = json.loads(feature_json)
            except ValueError:
                feature_json = {}
        plan = feature_json.get("plan") or {}
        evaluation_present = row.get("evaluation_row_id") is not None
        t1_state = _evaluation_state(
            mature=horizons["t1_mature"],
            row_present=evaluation_present,
            value=row.get("next_1d_return"),
            missing_reason=row.get("missing_reason"),
        )
        t3_state = _evaluation_state(
            mature=horizons["t3_mature"],
            row_present=evaluation_present,
            value=row.get("next_3d_return"),
            missing_reason=row.get("t3_missing_reason"),
        )
        facts.append({
            "signal_id": row.get("signal_id"),
            "decision_id": row.get("decision_id"),
            "source_run_id": row.get("source_run_id"),
            "code": row.get("code"),
            "name": row.get("name"),
            "strategy": row.get("strategy"),
            "final_layer": row.get("canonical_final_layer") or row.get("final_decision_layer"),
            "primary_direction": row.get("primary_direction"),
            "market_context": {
                "status": row.get("market_status"),
                "score": row.get("market_score"),
                "trade_mode": row.get("trade_mode"),
                "position_cap": row.get("position_cap"),
                "sentiment_score": row.get("sentiment_score"),
                "sentiment_stage": row.get("sentiment_stage"),
            },
            "signal_facts": {
                "close_price": row.get("close_price"),
                "pct_chg": row.get("pct_chg"),
                "pct_5d": row.get("pct_5d"),
                "pct_20d": row.get("pct_20d"),
                "volume_ratio": row.get("volume_ratio"),
                "turnover": row.get("turnover"),
                "ma5": row.get("ma5"),
                "ma10": row.get("ma10"),
                "ma20": row.get("ma20"),
            },
            "decision": {
                "base_layer": plan.get("base_layer"),
                "final_layer": plan.get("final_layer") or row.get("canonical_final_layer"),
                "display_reason": plan.get("display_reason"),
                "correction_level": plan.get("correction_level"),
                "correction_tags": plan.get("correction_tags") or [],
                "entry_reason": row.get("entry_reason"),
                "risk_reasons": row.get("risk_reasons"),
                "observe_low": row.get("observe_low"),
                "observe_high": row.get("observe_high"),
                "pressure_price": row.get("pressure_price"),
                "invalid_price": row.get("invalid_price"),
            },
            "evaluation": {
                "schema_version": row.get("evaluation_schema_version"),
                "t1": {
                    "target_date": horizons.get("t1_date"),
                    "mature": horizons["t1_mature"],
                    "state": t1_state,
                    "return": row.get("next_1d_return"),
                    "missing_reason": row.get("missing_reason"),
                    "feedback_label": row.get("feedback_label"),
                    "attribution_text": row.get("attribution_text"),
                },
                "t3": {
                    "target_date": horizons.get("t3_date"),
                    "mature": horizons["t3_mature"],
                    "state": t3_state,
                    "return": row.get("next_3d_return"),
                    "max_return": row.get("max_3d_return"),
                    "max_drawdown": row.get("max_3d_drawdown"),
                    "missing_reason": row.get("t3_missing_reason"),
                    "feedback_label": row.get("feedback_label_3d"),
                    "attribution_text": row.get("attribution_text_3d"),
                },
            },
            "evidence_refs": [
                f"stock_signal:{row.get('signal_id')}",
                f"candidate_feature_snapshot:{row.get('snapshot_row_id')}",
                f"watchlist_evaluation_result:{row.get('evaluation_row_id')}"
                if evaluation_present else "watchlist_evaluation_result:pending",
            ],
        })
    return facts


def _evaluation_data_status(
    signals: list[dict[str, Any]], horizons: dict[str, Any], as_of_date: str,
) -> dict[str, Any]:
    eligible = len(signals)
    evaluated_t1 = sum(
        1 for item in signals
        if item["evaluation"]["t1"]["state"] == "success"
    )
    evaluated_t3 = sum(
        1 for item in signals
        if item["evaluation"]["t3"]["state"] == "success"
    )
    return {
        "t1": resolve_evaluation_status(
            mature=horizons["t1_mature"],
            target_date=horizons.get("t1_date"),
            as_of_date=as_of_date,
            eligible_count=eligible,
            evaluated_count=evaluated_t1,
            execution_status="success" if evaluated_t1 else "unknown",
        ),
        "t3": resolve_evaluation_status(
            mature=horizons["t3_mature"],
            target_date=horizons.get("t3_date"),
            as_of_date=as_of_date,
            eligible_count=eligible,
            evaluated_count=evaluated_t3,
            execution_status="success" if evaluated_t3 else "unknown",
        ),
    }


def _status_and_limitations(
    *, trade_date: str, as_of_date: str, signal_rows: list[dict[str, Any]],
    signals: list[dict[str, Any]], report: dict[str, Any], quality: dict[str, Any],
    artifact_summary: dict[str, Any], evaluation_status: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    limitations = []
    raw_count = len(signal_rows)
    snapshot_count = sum(1 for row in signal_rows if row.get("snapshot_row_id") is not None)
    if raw_count == 0:
        limitations.append({"code": "signals_missing", "severity": "blocking"})
    if snapshot_count != raw_count:
        limitations.append({
            "code": "snapshot_identity_gap", "severity": "blocking",
            "signal_count": raw_count, "snapshot_count": snapshot_count,
        })
    if not report:
        limitations.append({"code": "canonical_report_missing", "severity": "blocking"})
    ma_missing = quality.get("ma_missing_ratio")
    if ma_missing is not None and float(ma_missing) >= 0.5:
        limitations.append({
            "code": "universe_ma_coverage_limited", "severity": "warning",
            "missing_ratio": float(ma_missing),
        })
    unavailable_t1 = sum(
        1 for item in signals if item["evaluation"]["t1"]["state"] == "unavailable_price"
    )
    unavailable_t3 = sum(
        1 for item in signals if item["evaluation"]["t3"]["state"] == "unavailable_price"
    )
    if unavailable_t1 or unavailable_t3:
        limitations.append({
            "code": "mature_evaluation_price_unavailable", "severity": "warning",
            "t1_count": unavailable_t1, "t3_count": unavailable_t3,
        })
    for horizon, evaluation in (evaluation_status or {}).items():
        if evaluation.get("status") == "degraded":
            limitations.append({
                "code": f"{horizon}_evaluation_low_coverage",
                "severity": "warning",
                "coverage": evaluation.get("coverage"),
                "threshold": evaluation.get("threshold"),
                "missing_count": evaluation.get("missing_count"),
                "reason_code": evaluation.get("reason_code"),
            })
        elif evaluation.get("status") in {"missing", "failed"}:
            limitations.append({
                "code": f"{horizon}_evaluation_unavailable",
                "severity": "blocking",
                "coverage": evaluation.get("coverage"),
                "missing_count": evaluation.get("missing_count"),
                "reason_code": evaluation.get("reason_code"),
            })
    if artifact_summary.get("status") != "available":
        limitations.append({
            "code": "daily_summary_artifact_unavailable", "severity": "warning",
            "reason": artifact_summary.get("reason"),
        })
    if trade_date != as_of_date:
        limitations.append({
            "code": "historical_as_of_view", "severity": "info",
            "message": "Evaluation maturity is evaluated at as_of_date, not report generation time.",
        })
    status = "blocked" if any(x["severity"] == "blocking" for x in limitations) else (
        "degraded" if any(x["severity"] == "warning" for x in limitations) else "ready"
    )
    return status, limitations


def _canonical_hash(payload: dict[str, Any]) -> str:
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_fact_pack(
    trade_date: str,
    as_of_date: str | None = None,
    *,
    conn=None,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    trade_text = normalize_trade_date(trade_date)
    as_of_text = normalize_trade_date(as_of_date or date.today())
    horizons = resolve_evaluation_horizons(trade_text, as_of_text)
    sql_date = f"{trade_text[:4]}-{trade_text[4:6]}-{trade_text[6:]}"
    own_conn = conn is None
    db = conn or psycopg2.connect(DATABASE_DSN)
    try:
        cur = db.cursor(cursor_factory=RealDictCursor)
        rows = _fetch_all(cur, """
            SELECT l.signal_id, l.decision_id, l.source_run_id, l.code, l.name,
                   l.strategy, l.final_decision_layer, l.snapshot_row_id,
                   l.evaluation_row_id, c.canonical_final_layer,
                   c.primary_direction, c.market_status, c.market_score,
                   c.trade_mode, c.position_cap, c.sentiment_score,
                   c.sentiment_stage, c.data_confidence, c.close_price,
                   c.pct_chg, c.pct_5d, c.pct_20d, c.volume_ratio, c.turnover,
                   c.ma5, c.ma10, c.ma20, c.entry_reason, c.risk_reasons,
                   c.observe_low, c.observe_high, c.pressure_price,
                   c.invalid_price, c.feature_json,
                   r.evaluation_schema_version, r.next_1d_return,
                   r.next_3d_return, r.max_3d_return, r.max_3d_drawdown,
                   r.missing_reason, r.t3_missing_reason, r.feedback_label,
                   r.feedback_label_3d, r.attribution_text,
                   r.attribution_text_3d
            FROM canonical_signal_lineage l
            LEFT JOIN candidate_feature_snapshot c ON c.id=l.snapshot_row_id
            LEFT JOIN canonical_daily_evaluation_result r ON r.id=l.evaluation_row_id
            WHERE l.trade_date=%s
            ORDER BY l.code, l.strategy
        """, (sql_date,))
        report = _fetch_one(cur, """
            SELECT id, report_mode, report_type, confidence_score, created_at,
                   content
            FROM daily_report WHERE trade_date=%s
            ORDER BY CASE WHEN report_mode='unified' THEN 0 ELSE 1 END,
                     created_at DESC LIMIT 1
        """, (sql_date,))
        report_content = report.pop("content", None)
        if report_content is not None:
            report["content_sha256"] = hashlib.sha256(
                report_content.encode("utf-8")
            ).hexdigest()
        quality = _fetch_one(cur, """
            SELECT id, stock_count, industry_count, concept_count,
                   has_board_amount_ratio, has_stock_board_map,
                   has_3d_history, has_5d_history, ma_missing_ratio,
                   confidence_score, issues, created_at
            FROM data_quality_log WHERE trade_date=%s
            ORDER BY created_at DESC, id DESC LIMIT 1
        """, (sql_date,))
        reconciliation = _fetch_one(cur, """
            SELECT * FROM daily_reconciliation WHERE trade_date=%s
        """, (sql_date,))
        evaluation_summary = _fetch_one(cur, """
            SELECT * FROM canonical_daily_evaluation_summary
            WHERE signal_date=%s
        """, (trade_text,))
        strategy_feedback = _fetch_all(cur, """
            SELECT strategy, window_days, sample_count, win_rate_1d,
                   avg_next_1d_return, avg_max_3d_return,
                   avg_max_3d_drawdown, strong_rate, failed_rate,
                   feedback_score, status, reason, updated_at
            FROM strategy_feedback_stats WHERE trade_date=%s
            ORDER BY strategy, window_days
        """, (sql_date,))
        job_runs = _fetch_all(cur, """
            SELECT run_id, run_schema_version, job_name, status, started_at,
                   finished_at, duration_seconds, error_message,
                   parent_run_id, trigger_type, attempt_no, idempotency_key
            FROM job_run_log WHERE trade_date=%s
            ORDER BY started_at, id
        """, (sql_date,))
        cur.close()
    finally:
        if own_conn:
            db.close()

    signals = _signal_facts(rows, horizons)
    evaluation_status = _evaluation_data_status(signals, horizons, as_of_text)
    artifact_summary = _load_daily_summary(trade_text, Path(report_dir or REPORT_DIR))
    try:
        correction_raw = build_correction_effectiveness(
            as_of=as_of_text, min_coverage=0.80, window_days=5, save=False,
        )
        correction = {
            "status": "available",
            "as_of_date": correction_raw.get("as_of_date"),
            "window_dates": correction_raw.get("window_dates") or [],
            "summary": correction_raw.get("summary") or {},
            "by_reason": correction_raw.get("by_reason") or [],
        }
    except Exception as exc:
        correction = {"status": "unavailable", "reason": str(exc)}

    status, limitations = _status_and_limitations(
        trade_date=trade_text, as_of_date=as_of_text, signal_rows=rows,
        signals=signals, report=report, quality=quality,
        artifact_summary=artifact_summary, evaluation_status=evaluation_status,
    )
    facts = {
        "trade_date": trade_text,
        "as_of_date": as_of_text,
        "horizons": horizons,
        "market": signals[0]["market_context"] if signals else {},
        "data_quality": quality,
        "report": report,
        "artifact_summary": artifact_summary,
        "signals": signals,
        "evaluation_status": evaluation_status,
        "evaluation_summary": evaluation_summary,
        "strategy_feedback": strategy_feedback,
        "correction_effectiveness": correction,
        "pipeline": {
            "reconciliation": reconciliation,
            "job_runs": job_runs,
        },
    }
    content_hash = _canonical_hash(facts)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "schema_version": FACT_PACK_SCHEMA_VERSION,
        "fact_pack_id": f"llmfp:{trade_text}:{as_of_text}:{content_hash[:16]}",
        "content_sha256": content_hash,
        "generated_at": generated_at,
        "meta": {
            "schema_version": FACT_PACK_SCHEMA_VERSION,
            "trade_date": trade_text,
            "as_of_date": as_of_text,
            "generated_at": generated_at,
            "report_mode": report.get("report_mode"),
            "signal_grain": "trade_date+code+strategy",
        },
        "status": status,
        "policy": {
            "mode": "read_only_sidecar",
            "allowed_tasks": ["explain", "summarize", "compare", "diagnose"],
            "forbidden_tasks": [
                "select_new_stocks", "change_score", "change_layer",
                "change_position", "write_trading_tables",
            ],
        },
        "definitions": {
            "signal_grain": "one row per trade_date + stock code + strategy",
            "stock_count_is_not_signal_count": True,
            "pending": "target trading date has not matured at as_of_date",
            "unavailable_price": "evaluation record exists but a required market price is unavailable",
            "success": "mature evaluation return is present",
            "degraded": "evaluation is mature but coverage is below the governed threshold",
        },
        "limitations": limitations,
        "facts": facts,
        "evidence_catalog": {
            "signal": "stock_signal + candidate_feature_snapshot via canonical_signal_lineage",
            "evaluation": "canonical_daily_evaluation_summary/result",
            "quality": "data_quality_log",
            "pipeline": "daily_reconciliation + job_run_log",
            "report": "daily_report",
        },
        "source_manifest": {
            "signals": {"source": "canonical_signal_lineage", "rows": len(rows)},
            "snapshots": {
                "source": "candidate_feature_snapshot",
                "rows": sum(1 for row in rows if row.get("snapshot_row_id") is not None),
            },
            "evaluation": {
                "source": "canonical_daily_evaluation_result",
                "rows": sum(1 for row in rows if row.get("evaluation_row_id") is not None),
            },
            "report": {"source": "daily_report", "rows": 1 if report else 0},
            "quality": {"source": "data_quality_log", "rows": 1 if quality else 0},
            "pipeline": {"source": "daily_reconciliation+job_run_log", "rows": len(job_runs)},
        },
    }


def save_fact_pack(pack: dict[str, Any], out_dir: Path | None = None) -> Path:
    target_dir = Path(out_dir or FACT_PACK_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / (
        f"fact_pack_{pack['facts']['trade_date']}_asof_{pack['facts']['as_of_date']}.json"
    )
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="Build a read-only LLM fact pack")
    parser.add_argument("--date", required=True, help="Signal/report date YYYYMMDD")
    parser.add_argument("--as-of", help="Evaluation maturity date YYYYMMDD")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    pack = build_fact_pack(args.date, args.as_of)
    if args.save:
        path = save_fact_pack(pack)
        print(json.dumps({
            "status": pack["status"], "fact_pack_id": pack["fact_pack_id"],
            "path": str(path), "limitations": pack["limitations"],
        }, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(pack, ensure_ascii=False, indent=2, default=str))
    if pack["status"] == "blocked":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
