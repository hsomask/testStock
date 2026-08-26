"""
Backfill recent low-coverage daily evaluations.

The tool scans recent watchlist_evaluation_summary rows, maximizes K-line
coverage for low-coverage days, and optionally reruns formal evaluation.

Examples:
  python -m analysis.evaluation_backfill_low_coverage --days 5
  python -m analysis.evaluation_backfill_low_coverage --days 5 --execute
  python -m analysis.evaluation_backfill_low_coverage --as-of 20260702 --execute
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psycopg2

from data.config import DATABASE_DSN, REPORT_DIR
from analysis.ensure_signal_kline_coverage import ensure_signal_kline_coverage
from analysis.evaluation_time import resolve_evaluation_horizons
from analysis.evaluation_status import (
    resolve_evaluation_status,
    should_backfill_evaluation,
)


EVAL_DIR = REPORT_DIR / "evaluation"


def _connect():
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    return psycopg2.connect(DATABASE_DSN)


def _run_module(module, args):
    cmd = [sys.executable, "-m", module] + list(args)
    proc = subprocess.run(cmd, text=True, capture_output=True)
    return {
        "cmd": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def _select_repair_horizon(
    *, signal_date, run_as_of, signal_count, evaluated_1d=0,
    coverage_1d=0, evaluated_3d=0, coverage_3d=0, threshold=0.90,
):
    horizons = resolve_evaluation_horizons(signal_date, run_as_of)
    candidates = []
    for horizon, evaluated, coverage in (
        ("t1", evaluated_1d, coverage_1d),
        ("t3", evaluated_3d, coverage_3d),
    ):
        state = resolve_evaluation_status(
            mature=bool(horizons.get(f"{horizon}_mature")),
            target_date=horizons.get(f"{horizon}_date"),
            as_of_date=run_as_of,
            eligible_count=int(signal_count or 0),
            evaluated_count=int(evaluated or 0),
            coverage=float(coverage or 0),
            execution_status="success" if int(evaluated or 0) else "unknown",
            minimum_coverage=threshold,
        )
        if should_backfill_evaluation(state):
            candidates.append((horizon, state))
    return candidates[-1] if candidates else None


def _fetch_targets(days, as_of, threshold, exclude_signal_date=None):
    conn = _connect()
    try:
        cur = conn.cursor()
        run_as_of = str(as_of or datetime.now().strftime("%Y%m%d")).replace("-", "")[:8]
        cur.execute(
            """
            WITH recent AS (
                SELECT trade_date, COUNT(*) AS signal_count
                FROM stock_signal
                WHERE trade_date < %s
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT %s
            )
            SELECT r.trade_date, r.signal_count,
                   s.evaluated_1d, s.coverage_1d,
                   s.evaluated_3d, s.coverage_3d
            FROM recent r
            LEFT JOIN canonical_daily_evaluation_summary s
              ON s.signal_date=TO_CHAR(r.trade_date, 'YYYYMMDD')
            ORDER BY r.trade_date DESC
            """,
            (f"{run_as_of[:4]}-{run_as_of[4:6]}-{run_as_of[6:]}", int(days)),
        )
        targets = []
        for signal_date, signal_count, evaluated_1d, coverage_1d, evaluated_3d, coverage_3d in cur.fetchall():
            signal_key = signal_date.strftime("%Y%m%d") if hasattr(signal_date, "strftime") else str(signal_date).replace("-", "")[:8]
            candidate = _select_repair_horizon(
                signal_date=signal_key,
                run_as_of=run_as_of,
                signal_count=signal_count,
                evaluated_1d=evaluated_1d,
                coverage_1d=coverage_1d,
                evaluated_3d=evaluated_3d,
                coverage_3d=coverage_3d,
                threshold=threshold,
            )
            if not candidate:
                continue
            # A T+3 rerun also preserves/fills T+1, so one signal date enters
            # the queue only once at its latest repairable horizon.
            horizon, state = candidate
            targets.append({
                "signal_date": signal_key,
                "as_of_date": state["target_date"],
                "horizon": horizon,
                "total_signals": state["eligible_count"],
                "evaluated_count": state["evaluated_count"],
                "coverage": state["coverage"],
                "coverage_1d": float(coverage_1d or 0),
                "coverage_3d": float(coverage_3d or 0),
                "reason_code": state["reason_code"],
                "missing_evaluation": state["evaluated_count"] == 0,
            })
        excluded = str(exclude_signal_date or "").replace("-", "")[:8]
        if excluded:
            targets = [
                item for item in targets
                if str(item["signal_date"]).replace("-", "")[:8] != excluded
            ]
        cur.close()
        return sorted(targets, key=lambda item: str(item["as_of_date"]), reverse=True)
    finally:
        conn.close()


def _write_report(result, suffix):
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    json_path = EVAL_DIR / f"evaluation_backfill_{suffix}.json"
    md_path = EVAL_DIR / f"evaluation_backfill_{suffix}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Evaluation 低覆盖回补 - {suffix}",
        "",
        f"- 执行模式：{'execute' if result.get('execute') else 'dry-run'}",
        f"- 覆盖门槛：{result.get('threshold'):.1%}",
        f"- 回补后重跑门槛：{result.get('rerun_min_coverage'):.1%}",
        f"- 目标数量：{len(result.get('items', []))}",
        "",
        "| as_of | signal | horizon | 原覆盖 | 补后覆盖 | 质量层级 | 动作 |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for item in result.get("items", []):
        lines.append(
            f"| {item.get('as_of_date')} | {item.get('signal_date')} | {item.get('horizon')} | "
            f"{item.get('before_coverage', 0):.1%} | {item.get('after_coverage', 0):.1%} | "
            f"{item.get('coverage_level')} | {item.get('action')} |"
        )
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    result["json_path"] = str(json_path)
    result["md_path"] = str(md_path)


def backfill_low_coverage(
    days=5,
    as_of=None,
    threshold=0.90,
    rerun_min_coverage=0.90,
    time_budget=1800,
    deep=True,
    execute=False,
    exclude_signal_date=None,
):
    targets = _fetch_targets(
        days=days,
        as_of=as_of,
        threshold=threshold,
        exclude_signal_date=exclude_signal_date,
    )
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "execute": execute,
        "days": days,
        "as_of": as_of,
        "threshold": threshold,
        "rerun_min_coverage": rerun_min_coverage,
        "time_budget": time_budget,
        "deep": deep,
        "exclude_signal_date": exclude_signal_date,
        "items": [],
    }

    for target in targets:
        signal_date = target["signal_date"]
        as_of_date = target["as_of_date"]
        coverage = ensure_signal_kline_coverage(
            signal_date,
            as_of_date,
            time_budget=time_budget,
            deep=deep,
            min_coverage=0.80,
        )
        after_cov = float(coverage.get("coverage") or 0)
        item = {
            **target,
            "before_coverage": target.get("coverage", 0),
            "after_coverage": after_cov,
            "coverage_status": coverage.get("status"),
            "coverage_level": coverage.get("coverage_level"),
            "quality_weight": coverage.get("quality_weight"),
            "attempted_fill": coverage.get("attempted_fill", 0),
            "fill_success": coverage.get("fill_success", 0),
            "missing_codes": coverage.get("missing_codes", []),
            "upstream_lag_codes": coverage.get("upstream_lag_codes", []),
            "action": "skip",
            "commands": [],
        }

        # A completely missing Evaluation should still be materialized once the
        # operational 80% floor is met; its data status remains ``degraded``
        # until the governed 90% completeness threshold is reached.
        effective_rerun_coverage = 0.80 if target.get("missing_evaluation") else rerun_min_coverage
        item["effective_rerun_coverage"] = effective_rerun_coverage
        if after_cov >= effective_rerun_coverage:
            if execute:
                item["action"] = "rerun_evaluation"
                evaluation_command = _run_module(
                    "analysis.watchlist_evaluation",
                    [
                        "--mode", "daily",
                        "--signal-date", signal_date,
                        "--as-of", as_of_date,
                        "--save-db",
                    ],
                )
                item["commands"].append(evaluation_command)
                if evaluation_command.get("returncode") != 0:
                    item["action"] = "rerun_failed"
                    result["items"].append(item)
                    continue
                item["commands"].append(
                    _run_module("analysis.strategy_feedback", ["--date", as_of_date, "--window", "20"])
                )
                item["commands"].append(
                    _run_module("analysis.context_feedback", ["--as-of", as_of_date, "--window", "20"])
                )
                item["commands"].append(
                    _run_module("analysis.snapshot_integrity_check", ["--date", signal_date])
                )
                item["commands"].append(
                    _run_module("analysis.ml_dataset_builder", ["--as-of", as_of_date, "--min-coverage", "0.9"])
                )
                item["commands"].append(
                    _run_module("analysis.correction_effectiveness", ["--as-of", as_of_date, "--min-coverage", "0.8"])
                )
            else:
                item["action"] = "would_rerun_evaluation"
        elif after_cov >= 0.80:
            item["action"] = "keep_low_weight"
        else:
            item["action"] = "keep_deferred"

        result["items"].append(item)

    result["status"] = (
        "failed"
        if any(item.get("action") == "rerun_failed" for item in result["items"])
        else "success"
    )

    suffix = as_of or datetime.now().strftime("%Y%m%d_%H%M%S")
    _write_report(result, suffix)
    return result


def main():
    parser = argparse.ArgumentParser(description="Backfill recent low-coverage daily evaluation rows")
    parser.add_argument("--days", type=int, default=5, help="Recent low-coverage rows to inspect")
    parser.add_argument("--as-of", type=str, default=None, help="Only backfill one as_of date YYYYMMDD")
    parser.add_argument("--threshold", type=float, default=0.90, help="Scan rows below this coverage")
    parser.add_argument("--rerun-min-coverage", type=float, default=0.90, help="Rerun formal eval at/above this coverage")
    parser.add_argument("--time-budget", type=int, default=1800, help="Seconds spent filling K-lines per target")
    parser.add_argument("--deep", action="store_true", default=False, help="Use deeper K-line fetch rounds")
    parser.add_argument("--execute", action="store_true", default=False, help="Actually rerun formal evaluation")
    parser.add_argument("--json", action="store_true", default=False, dest="json_output")
    parser.add_argument("--exclude-signal-date", type=str, default=None)
    args = parser.parse_args()

    result = backfill_low_coverage(
        days=args.days,
        as_of=args.as_of,
        threshold=args.threshold,
        rerun_min_coverage=args.rerun_min_coverage,
        time_budget=args.time_budget,
        deep=args.deep,
        execute=args.execute,
        exclude_signal_date=args.exclude_signal_date,
    )
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"targets: {len(result['items'])}")
        print(f"json: {result['json_path']}")
        print(f"md: {result['md_path']}")
        for item in result["items"]:
            print(
                f"{item['as_of_date']} {item['signal_date']}: "
                f"{item['before_coverage']:.1%} -> {item['after_coverage']:.1%}, {item['action']}"
            )
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
