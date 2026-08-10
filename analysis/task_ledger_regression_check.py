"""Regression checks for task-ledger status and failure isolation."""
from __future__ import annotations

import sys

from analysis import task_ledger


def run_checks():
    failures = []
    for status in sorted(task_ledger.VALID_STATUSES):
        if task_ledger._normalize_status(status.upper()) != status:
            failures.append(f"status normalization failed: {status}")
    try:
        task_ledger._normalize_status("unknown")
        failures.append("invalid status was accepted")
    except ValueError:
        pass

    original_connect = task_ledger._connect
    try:
        task_ledger._connect = lambda: (_ for _ in ()).throw(RuntimeError("fixture"))
        if task_ledger.start_task("fixture", "20260810") is not None:
            failures.append("non-required ledger failure was not isolated")
        try:
            task_ledger.start_task("fixture", "20260810", required=True)
            failures.append("required ledger failure did not propagate")
        except RuntimeError:
            pass
    finally:
        task_ledger._connect = original_connect
    return failures


def main():
    failures = run_checks()
    if failures:
        print("[FAIL] task ledger regression check")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)
    print("[OK] task ledger regression check")


if __name__ == "__main__":
    main()
