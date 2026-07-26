"""Regression checks for deterministic signal identity."""
import sys

from analysis.signal_identity import (
    SIGNAL_ID_SCHEMA_VERSION,
    build_signal_id,
    build_decision_id,
    normalize_signal_date,
    normalize_stock_code,
    signal_natural_key,
)


def run_checks():
    failures = []
    base = build_signal_id("2026-07-24", "000001", "N字异动")
    equivalents = [
        build_signal_id("20260724", "sz000001", "N字异动"),
        build_signal_id("2026/07/24", 1, "  N字异动  "),
    ]
    if any(value != base for value in equivalents):
        failures.append("equivalent natural keys produced different signal_id values")
    if build_signal_id("20260724", "000001", "二次起爆") == base:
        failures.append("different strategies produced the same signal_id")
    if build_signal_id("20260725", "000001", "N字异动") == base:
        failures.append("different dates produced the same signal_id")
    if build_decision_id("20260724", "000001") != build_decision_id(
        "2026-07-24", "sz000001"
    ):
        failures.append("equivalent stock decisions produced different decision_id")
    if build_decision_id("20260724", "000001") == build_decision_id(
        "20260724", "000002"
    ):
        failures.append("different stocks produced the same decision_id")
    if normalize_signal_date("2026-07-24") != "20260724":
        failures.append("date normalization failed")
    if normalize_stock_code("SH600000") != "600000":
        failures.append("code normalization failed")
    if not signal_natural_key("20260724", "000001", "N字异动").startswith(
        SIGNAL_ID_SCHEMA_VERSION + "|"
    ):
        failures.append("schema version missing from natural key")
    return failures


def main():
    failures = run_checks()
    if failures:
        print("[FAIL] signal identity regression check")
        for item in failures:
            print(f"- {item}")
        sys.exit(1)
    print("[OK] signal identity regression check")


if __name__ == "__main__":
    main()
