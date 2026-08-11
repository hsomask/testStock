"""Regression checks for identity-grain daily reconciliation statuses."""

from analysis.daily_reconciliation import _email_status, _overall_status, _report_status


def main():
    errors = []
    if _report_status(0) != "missing" or _report_status(1) != "success" or _report_status(2) != "duplicate":
        errors.append("canonical report cardinality is not enforced")
    if _email_status(0, 0) != "unknown":
        errors.append("legacy date without an email ledger was falsely classified as missing")
    if _email_status(0, 1) != "missing" or _email_status(1, 1) != "success":
        errors.append("attempted email delivery is not classified truthfully")
    if _overall_status(("success", "unknown"), ("success",)) != "success":
        errors.append("historical unknown email incorrectly fails an otherwise complete day")
    if _overall_status(("success", "missing"), ("success",)) != "failed":
        errors.append("known missing email does not fail reconciliation")
    if _overall_status(("success",), ("deferred",)) != "deferred":
        errors.append("K-line deferral does not propagate")
    if _overall_status(("success", "deferred"), ("success", "deferred")) != "deferred":
        errors.append("mature T+3 low-coverage deferral does not propagate")
    if _overall_status(("duplicate",), ("success",)) != "failed":
        errors.append("duplicate canonical report does not fail reconciliation")

    if errors:
        print("[FAIL] daily reconciliation regression check")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("[OK] daily reconciliation regression check")


if __name__ == "__main__":
    main()
