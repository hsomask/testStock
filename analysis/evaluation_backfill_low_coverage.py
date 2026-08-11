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


def _fetch_targets(days, as_of, threshold, exclude_signal_date=None):
    conn = _connect()
    try:
        cur = conn.cursor()
        params = [threshold]
        asof_filter = ""
        limit_clause = "LIMIT %s"
        if as_of:
            asof_filter = "AND as_of_date = %s"
            params.append(str(as_of).replace("-", "")[:8])
            limit_clause = ""
        else:
            params.append(days)

        cur.execute(
            f"""
            WITH latest AS (
                SELECT DISTINCT ON (signal_date, as_of_date)
                    signal_date, as_of_date, total_signals, evaluated_1d,
                    coverage_1d, generated_at
                FROM watchlist_evaluation_summary
                WHERE eval_mode = 'daily'
                  AND signal_date IS NOT NULL
                  AND as_of_date IS NOT NULL
                ORDER BY signal_date, as_of_date, generated_at DESC
            )
            SELECT signal_date, as_of_date, total_signals, evaluated_1d, coverage_1d
            FROM latest
            WHERE COALESCE(coverage_1d, 0) < %s
              {asof_filter}
            ORDER BY as_of_date DESC
            {limit_clause}
            """,
            params,
        )
        rows = cur.fetchall()
        targets = [
            {
                "signal_date": row[0],
                "as_of_date": row[1],
                "total_signals": row[2],
                "evaluated_1d": row[3],
                "coverage_1d": float(row[4] or 0),
                "missing_evaluation": False,
            }
            for row in rows
        ]

        # A summary-only scan can never discover a completely missing
        # Evaluation. Reconcile recent signal dates against their canonical T+1
        # anchor and add mature gaps to the same repair queue.
        run_as_of = str(as_of or datetime.now().strftime("%Y%m%d")).replace("-", "")[:8]
        cur.execute(
            """
            SELECT trade_date, COUNT(*)
            FROM stock_signal
            WHERE trade_date < %s
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT %s
            """,
            (f"{run_as_of[:4]}-{run_as_of[4:6]}-{run_as_of[6:]}", int(days)),
        )
        known = {
            (
                str(item["signal_date"]).replace("-", "")[:8],
                str(item["as_of_date"]).replace("-", "")[:8],
            )
            for item in targets
        }
        for signal_date, signal_count in cur.fetchall():
            signal_key = signal_date.strftime("%Y%m%d") if hasattr(signal_date, "strftime") else str(signal_date).replace("-", "")[:8]
            horizons = resolve_evaluation_horizons(signal_key, run_as_of)
            if not horizons.get("t1_mature") or not horizons.get("t1_date"):
                continue
            anchor = horizons["t1_date"]
            if (signal_key, anchor) in known:
                continue
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM watchlist_evaluation_summary
                    WHERE eval_mode = 'daily'
                      AND signal_date = %s
                      AND as_of_date = %s
                )
                """,
                (signal_key, anchor),
            )
            if cur.fetchone()[0]:
                continue
            targets.append({
                "signal_date": signal_key,
                "as_of_date": anchor,
                "total_signals": int(signal_count or 0),
                "evaluated_1d": 0,
                "coverage_1d": 0.0,
                "missing_evaluation": True,
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
        "| as_of | signal | 原覆盖 | 补后覆盖 | 质量层级 | 动作 |",
        "|---|---|---:|---:|---|---|",
    ]
    for item in result.get("items", []):
        lines.append(
            f"| {item.get('as_of_date')} | {item.get('signal_date')} | "
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
            "before_coverage": target.get("coverage_1d", 0),
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
