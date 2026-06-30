"""
Ensure stock_hist_kline coverage for a signal/as-of pair before formal evaluation.

Examples:
  python -m analysis.ensure_signal_kline_coverage --signal-date 20260626 --as-of 20260629
  python -m analysis.ensure_signal_kline_coverage --signal-date 20260626 --as-of 20260629 --json
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime

import psycopg2

from data.config import DATABASE_DSN
from analysis.data_fetcher import get_stock_history


DEFAULT_ROUNDS = [80, 250, 500]
DEEP_ROUNDS = [80, 250, 500, 1000]


def _sql_date(yyyymmdd):
    if not yyyymmdd:
        return None
    s = str(yyyymmdd).replace("-", "")[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _compact_date(value):
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return bool(cur.fetchone()[0])


def _connect():
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    return psycopg2.connect(DATABASE_DSN)


def _fetch_signals(cur, signal_date):
    sql_signal = _sql_date(signal_date)
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'stock_signal'"
    )
    columns = {row[0] for row in cur.fetchall()}
    wanted = ["code", "name", "strategy", "risk_level", "watchlist_layer", "action_signal"]
    select_exprs = []
    for col in wanted:
        if col in columns:
            select_exprs.append(col)
        else:
            select_exprs.append(f"NULL AS {col}")
    col_sql = ", ".join(select_exprs)
    cur.execute(
        f"""
        SELECT DISTINCT {col_sql}
        FROM stock_signal
        WHERE trade_date = %s
        ORDER BY code
        """,
        (sql_signal,),
    )
    rows = []
    seen_codes = set()
    for row in cur.fetchall():
        code = str(row[0]).strip()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        rows.append({
            "code": code,
            "name": row[1] or "",
            "strategy": row[2] or "unknown",
            "risk_level": row[3] or "unknown",
            "watchlist_layer": row[4] or "unknown",
            "action_signal": row[5] or "",
        })
    return rows


def _inspect_code(cur, code, signal_sql, asof_sql):
    cur.execute(
        """
        SELECT trade_date
        FROM stock_hist_kline
        WHERE code = %s AND trade_date IN (%s, %s)
        """,
        (code, signal_sql, asof_sql),
    )
    dates = {_compact_date(r[0]) for r in cur.fetchall()}
    cur.execute(
        "SELECT MAX(trade_date), COUNT(*) FROM stock_hist_kline WHERE code = %s",
        (code,),
    )
    max_dt, cached_rows = cur.fetchone()
    has_signal = signal_sql in dates
    has_asof = asof_sql in dates
    ok = has_signal and has_asof
    reason = "ok"
    max_date = _compact_date(max_dt)

    if not ok:
        if not has_signal and not has_asof:
            reason = "missing_both"
        elif not has_signal:
            reason = "missing_signal_date"
        else:
            reason = "missing_as_of_date"

        if max_date and max_date < asof_sql:
            reason = "upstream_lag"
        elif max_date and max_date > signal_sql and not has_asof:
            reason = "suspended_or_no_trade"

    return {
        "ok": ok,
        "reason": reason,
        "has_signal_date": has_signal,
        "has_as_of_date": has_asof,
        "max_trade_date": max_date,
        "cached_rows": cached_rows or 0,
    }


def _summarize_details(signals, details, signal_date, as_of_date, attempted, fill_success, rounds_used, errors):
    total = len(signals)
    covered = sum(1 for item in details if item["ok"])
    coverage = covered / total if total else 0

    reason_counts = defaultdict(int)
    strategy_stats = defaultdict(lambda: {"total": 0, "covered": 0})
    risk_stats = defaultdict(lambda: {"total": 0, "covered": 0})
    layer_stats = defaultdict(lambda: {"total": 0, "covered": 0})

    by_code = {item["code"]: item for item in details}
    for sig in signals:
        detail = by_code.get(sig["code"])
        ok = bool(detail and detail["ok"])
        reason_counts[(detail or {}).get("reason", "unknown")] += 1
        for key, bucket in [
            (sig.get("strategy") or "unknown", strategy_stats),
            (sig.get("risk_level") or "unknown", risk_stats),
            (sig.get("watchlist_layer") or "unknown", layer_stats),
        ]:
            bucket[key]["total"] += 1
            if ok:
                bucket[key]["covered"] += 1

    def finalize_group(stats):
        rows = []
        for key, value in sorted(stats.items()):
            total_n = value["total"]
            covered_n = value["covered"]
            rows.append({
                "name": key,
                "total": total_n,
                "covered": covered_n,
                "coverage": covered_n / total_n if total_n else 0,
            })
        return rows

    if coverage >= 0.95:
        quality_weight = 1.0
        quality_level = "high"
    elif coverage >= 0.90:
        quality_weight = 0.8
        quality_level = "usable"
    elif coverage >= 0.80:
        quality_weight = 0.5
        quality_level = "low_weight"
    else:
        quality_weight = 0.0
        quality_level = "defer"

    status = "ready" if coverage >= 0.80 else "defer"
    warnings = []
    if 0.80 <= coverage < 0.90:
        warnings.append("coverage_between_80_and_90_use_low_weight")
    if coverage < 0.80:
        warnings.append("coverage_below_80_defer_formal_evaluation")

    return {
        "status": status,
        "signal_date": signal_date,
        "as_of_date": as_of_date,
        "signal_count": total,
        "covered_count": covered,
        "coverage": coverage,
        "coverage_level": quality_level,
        "quality_weight": quality_weight,
        "attempted_fill": attempted,
        "fill_success": fill_success,
        "rounds_used": rounds_used,
        "reason_counts": dict(sorted(reason_counts.items())),
        "strategy_coverage": finalize_group(strategy_stats),
        "risk_coverage": finalize_group(risk_stats),
        "layer_coverage": finalize_group(layer_stats),
        "missing_codes": [item["code"] for item in details if not item["ok"]],
        "upstream_lag_codes": [item["code"] for item in details if item["reason"] == "upstream_lag"],
        "suspended_or_no_trade_codes": [
            item["code"] for item in details if item["reason"] == "suspended_or_no_trade"
        ],
        "errors": errors[:20],
        "warnings": warnings,
        "details": details,
    }


def ensure_signal_kline_coverage(signal_date, as_of_date, time_budget=300, deep=False, min_coverage=0.80):
    signal_sql = _sql_date(signal_date)
    asof_sql = _sql_date(as_of_date)
    started = time.monotonic()
    attempted = 0
    fill_success = 0
    rounds_used = []
    errors = []

    conn = _connect()
    try:
        cur = conn.cursor()
        if not _table_exists(cur, "stock_signal"):
            return {
                "status": "error",
                "signal_date": signal_date,
                "as_of_date": as_of_date,
                "message": "stock_signal table does not exist",
            }
        if not _table_exists(cur, "stock_hist_kline"):
            return {
                "status": "error",
                "signal_date": signal_date,
                "as_of_date": as_of_date,
                "message": "stock_hist_kline table does not exist",
            }

        signals = _fetch_signals(cur, signal_date)
        if not signals:
            return {
                "status": "skip",
                "signal_date": signal_date,
                "as_of_date": as_of_date,
                "signal_count": 0,
                "covered_count": 0,
                "coverage": 0,
                "message": "no stock_signal rows for signal_date",
            }

        details = []
        for sig in signals:
            status = _inspect_code(cur, sig["code"], signal_sql, asof_sql)
            details.append({**sig, **status})

        rounds = DEEP_ROUNDS if deep else DEFAULT_ROUNDS
        for days in rounds:
            missing = [item for item in details if not item["ok"]]
            if not missing:
                break
            if time.monotonic() - started >= time_budget:
                errors.append({"code": "_budget", "error": "time_budget_exceeded"})
                break
            current_coverage = (len(details) - len(missing)) / len(details)
            if current_coverage >= min_coverage and days != rounds[0]:
                break

            rounds_used.append(days)
            for item in missing:
                if time.monotonic() - started >= time_budget:
                    errors.append({"code": "_budget", "error": "time_budget_exceeded"})
                    break
                code = item["code"]
                before = _inspect_code(cur, code, signal_sql, asof_sql)
                try:
                    get_stock_history(code, days=days, name=item.get("name", ""), require_fresh=True, allow_api=True)
                except Exception as exc:
                    errors.append({"code": code, "error": str(exc)[:160]})
                attempted += 1
                conn.rollback()
                after = _inspect_code(cur, code, signal_sql, asof_sql)
                if not before["ok"] and after["ok"]:
                    fill_success += 1

            details = []
            for sig in signals:
                status = _inspect_code(cur, sig["code"], signal_sql, asof_sql)
                details.append({**sig, **status})

        result = _summarize_details(
            signals, details, signal_date, as_of_date, attempted, fill_success, rounds_used, errors
        )
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        return result
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Ensure signal pool K-line coverage before evaluation")
    parser.add_argument("--signal-date", required=True, help="Signal date YYYYMMDD")
    parser.add_argument("--as-of", required=True, help="Evaluation date YYYYMMDD")
    parser.add_argument("--time-budget", type=int, default=300, help="Max seconds spent filling K-lines")
    parser.add_argument("--deep", action="store_true", default=False, help="Use deeper fetch rounds")
    parser.add_argument("--min-coverage", type=float, default=0.80, help="Minimum coverage for READY")
    parser.add_argument("--json", action="store_true", default=False, dest="json_output")
    args = parser.parse_args()

    try:
        result = ensure_signal_kline_coverage(
            args.signal_date,
            args.as_of,
            time_budget=args.time_budget,
            deep=args.deep,
            min_coverage=args.min_coverage,
        )
    except Exception as exc:
        result = {"status": "error", "message": str(exc), "signal_date": args.signal_date, "as_of_date": args.as_of}

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("=== Signal K-line Coverage ===")
    print(f"signal_date: {result.get('signal_date')}")
    print(f"as_of_date:  {result.get('as_of_date')}")
    print(f"status:      {result.get('status')}")
    print(f"coverage:    {result.get('covered_count', 0)}/{result.get('signal_count', 0)} = {result.get('coverage', 0):.1%}")
    print(f"quality:     {result.get('coverage_level')} weight={result.get('quality_weight')}")
    print(f"fill:        {result.get('fill_success', 0)}/{result.get('attempted_fill', 0)}")
    print(f"rounds:      {result.get('rounds_used', [])}")
    print(f"reasons:     {result.get('reason_counts', {})}")
    missing = result.get("details", [])
    missing = [item for item in missing if not item.get("ok")]
    if missing:
        print("")
        print("| code | name | reason | max_trade_date | strategy | risk | layer |")
        print("|------|------|--------|----------------|----------|------|-------|")
        for item in missing[:30]:
            print(
                f"| {item.get('code')} | {item.get('name')} | {item.get('reason')} | "
                f"{item.get('max_trade_date')} | {item.get('strategy')} | "
                f"{item.get('risk_level')} | {item.get('watchlist_layer')} |"
            )


if __name__ == "__main__":
    main()
