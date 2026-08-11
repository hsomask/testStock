"""Failure-path contracts for the runtime closure correction phase.

These checks intentionally exercise behavior that happy-path regressions miss:
delivery truthfulness, historical required-date refresh, retry bookkeeping and
reconciliation failure propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from analysis import data_fetcher, email_sender, pipeline_runner


def _check_email_delivery_contract(failures):
    with (
        patch.object(email_sender, "SMTP_HOST", ""),
        patch.object(email_sender, "SMTP_USER", ""),
        patch.object(email_sender, "SMTP_PASSWORD", ""),
        patch.object(email_sender, "EMAIL_TO", ""),
    ):
        status = email_sender.send_email("subject", "body")
    if status != "skipped_config_missing":
        failures.append(
            f"missing SMTP configuration must be explicit skip, got {status!r}"
        )

    class FailingSMTP:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def login(self, *_args):
            raise RuntimeError("smtp fixture failure")

    with (
        patch.object(email_sender, "SMTP_HOST", "smtp.example.com"),
        patch.object(email_sender, "SMTP_USER", "sender@example.com"),
        patch.object(email_sender, "SMTP_PASSWORD", "secret"),
        patch.object(email_sender, "EMAIL_TO", "receiver@example.com"),
        patch.object(email_sender.smtplib, "SMTP_SSL", FailingSMTP),
    ):
        status = email_sender.send_email("subject", "body")
    if status != "failed":
        failures.append(f"SMTP exception must be failed, got {status!r}")


def _check_historical_required_date_contract(failures):
    cached = pd.DataFrame(
        [
            {
                "date": f"2026-08-{day:02d}",
                "open": 10.0,
                "close": 10.1,
                "high": 10.2,
                "low": 9.9,
                "volume": 1000,
            }
            for day in range(1, 11)
        ]
    )
    fetched = pd.DataFrame(
        [
            {
                "date": "2026-07-31",
                "open": 9.8,
                "close": 10.0,
                "high": 10.1,
                "low": 9.7,
                "volume": 900,
                "data_source": "sina",
            }
        ]
    )
    saved = []
    try:
        with (
            patch.object(data_fetcher, "_get_hist_from_db", return_value=cached),
            patch.object(
                data_fetcher,
                "_latest_expected_cache_date",
                return_value="2026-08-10",
            ),
            patch.object(data_fetcher, "fetch_sina_history", return_value=fetched),
            patch.object(
                data_fetcher,
                "fetch_tencent_history",
                side_effect=AssertionError("fallback must not run"),
            ),
            patch.object(
                data_fetcher,
                "enrich_limitup_flags",
                side_effect=lambda frame: frame,
            ),
            patch.object(
                data_fetcher,
                "_save_hist_to_db",
                side_effect=lambda _code, frame: saved.append(frame.copy()),
            ),
        ):
            result = data_fetcher.get_stock_history(
                "600000",
                days=10,
                required_dates={"2026-07-31"},
            )
    except TypeError as exc:
        failures.append(f"get_stock_history lacks required_dates contract: {exc}")
        return

    if "2026-07-31" not in set(result["date"].astype(str)):
        failures.append("historical required date was not returned")
    if not saved or "2026-07-31" not in set(saved[0]["date"].astype(str)):
        failures.append("historical required date was not persisted")


def _run_pipeline_with_executor(executor):
    with (
        patch.object(
            pipeline_runner,
            "start_task",
            side_effect=lambda name, *_a, **_k: {
                "run_id": name,
                "job_name": name,
            },
        ),
        patch.object(pipeline_runner, "finish_task", return_value=True),
        patch.object(pipeline_runner, "fail_stale_pipeline_tasks", return_value=0),
        patch.object(pipeline_runner, "_email_already_sent", return_value=False),
        patch.object(
            pipeline_runner,
            "_pipeline_already_completed",
            return_value=False,
        ),
        patch.object(
            pipeline_runner,
            "_evaluation_status",
            side_effect=lambda _date, code, _started=0: (
                "success" if code == 0 else "failed"
            ),
        ),
    ):
        return pipeline_runner.run_daily(
            "20260810",
            executor=executor,
            calendar_status_getter=lambda _date: "open",
        )


def _check_reconciliation_failure_contract(failures):
    def executor(command, **_kwargs):
        if any("daily_reconciliation" in part for part in command):
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    result = _run_pipeline_with_executor(executor)
    if result["status"] != "failed":
        failures.append(
            f"reconciliation failure must fail parent pipeline, got {result['status']}"
        )


def _check_retry_error_reset_contract(failures):
    bootstrap_calls = 0

    def executor(command, **_kwargs):
        nonlocal bootstrap_calls
        if any("pipeline_bootstrap" in part for part in command):
            bootstrap_calls += 1
            return SimpleNamespace(returncode=1 if bootstrap_calls == 1 else 0)
        return SimpleNamespace(returncode=0)

    result = _run_pipeline_with_executor(executor)
    bootstrap = next(item for item in result["steps"] if item["step"] == "bootstrap")
    if bootstrap["status"] != "success":
        failures.append(f"retry should recover bootstrap, got {bootstrap['status']}")
    if bootstrap.get("error") is not None:
        failures.append(
            f"successful retry must clear previous error, got {bootstrap.get('error')!r}"
        )


def _check_non_idempotent_evaluation_not_retried(failures):
    evaluation_calls = 0

    def executor(command, **_kwargs):
        nonlocal evaluation_calls
        if any("evaluation_entrypoint" in part for part in command):
            evaluation_calls += 1
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    result = _run_pipeline_with_executor(executor)
    if evaluation_calls != 1:
        failures.append(f"evaluation workflow executed {evaluation_calls} times after failure")
    evaluation = next(item for item in result["steps"] if item["step"] == "evaluation")
    if len(evaluation.get("attempts", [])) != 1:
        failures.append("evaluation workflow still has whole-script retries")


def main():
    failures = []
    _check_email_delivery_contract(failures)
    _check_historical_required_date_contract(failures)
    _check_reconciliation_failure_contract(failures)
    _check_retry_error_reset_contract(failures)
    _check_non_idempotent_evaluation_not_retried(failures)
    if failures:
        print("[FAIL] runtime contract regression check")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("[OK] runtime contract regression check")


if __name__ == "__main__":
    main()
