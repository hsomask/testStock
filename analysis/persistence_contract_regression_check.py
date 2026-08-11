"""Static persistence contracts that must survive runtime refactors."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _normalized(path):
    return path.read_text(encoding="utf-8").lower()


def main():
    failures = []
    schema = _normalized(ROOT / "sql" / "schema.sql")
    report_source = _normalized(ROOT / "analysis" / "daily_report.py")
    reconciliation_source = _normalized(
        ROOT / "analysis" / "daily_reconciliation.py"
    )

    daily_report_unique = re.search(
        r"unique\s+(?:index[^\n]*\s+on\s+daily_report\s*)?"
        r"\(\s*trade_date\s*,\s*report_mode\s*,\s*report_type\s*\)",
        schema,
        re.DOTALL,
    )
    if not daily_report_unique:
        failures.append("daily_report lacks canonical unique key")

    insert_at = report_source.find("insert into daily_report")
    insert_window = report_source[insert_at : insert_at + 900] if insert_at >= 0 else ""
    if "on conflict" not in insert_window:
        failures.append("daily_report persistence is not an upsert")

    if not re.search(
        r"unique\s+index[^\n]*idempotency[^\n]*\s+on\s+job_run_log",
        schema,
    ):
        failures.append("job_run_log idempotency_key is not database-unique")

    if "canonical_signal_lineage" not in reconciliation_source:
        failures.append("reconciliation does not use canonical signal identity")
    if "count(distinct s.code)" in reconciliation_source:
        failures.append("reconciliation mixes code-grain coverage with signal rows")

    if failures:
        print("[FAIL] persistence contract regression check")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("[OK] persistence contract regression check")


if __name__ == "__main__":
    main()
