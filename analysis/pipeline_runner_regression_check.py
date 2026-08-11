"""Structural and status-propagation checks for the lightweight DAG."""
import subprocess
from types import SimpleNamespace
from analysis import pipeline_runner as runner
from analysis.pipeline_runner import Step, daily_steps, run_daily, validate_steps


def main():
    steps = daily_steps("20260810")
    assert validate_steps(steps)
    assert [s.name for s in steps] == ["bootstrap", "evaluation", "daily_report", "daily_email", "daily_reconcile"]
    assert next(step for step in steps if step.name == "evaluation").retries == 0
    assert next(step for step in steps if step.name == "bootstrap").retries == 1
    assert run_daily("20260810", dry_run=True)["status"] == "dry_run"
    try:
        validate_steps((Step("a", ("x",), ("b",)), Step("b", ("x",), ("a",))))
        raise AssertionError("cycle accepted")
    except ValueError:
        pass
    original_start, original_finish = runner.start_task, runner.finish_task
    original_email = runner._email_already_sent
    original_completed = runner._pipeline_already_completed
    original_eval = runner._evaluation_status
    original_stale = runner.fail_stale_pipeline_tasks
    events = []
    try:
        runner.start_task = lambda name, *_a, **_k: {"run_id": name, "job_name": name}
        runner.finish_task = lambda run, status, **_k: events.append((run["job_name"], status)) or True
        runner._email_already_sent = lambda _date: False
        runner._pipeline_already_completed = lambda _date: False
        runner._evaluation_status = lambda _date, code, _started=0: "deferred" if code == 0 else "failed"
        runner.fail_stale_pipeline_tasks = lambda *_a, **_k: 0
        runner._pipeline_already_completed = lambda _date: True
        active = run_daily("20260810", executor=lambda *_a, **_k: SimpleNamespace(returncode=0), calendar_status_getter=lambda _d: "open")
        assert active["status"] == "skipped" and active["reason"] == "pipeline_already_completed"
        runner._pipeline_already_completed = lambda _date: False
        result = run_daily("20260810", executor=lambda *_a, **_k: SimpleNamespace(returncode=0), calendar_status_getter=lambda _d: "open")
        assert result["status"] == "deferred"
        assert any(item["step"] == "evaluation" and item["status"] == "deferred" for item in result["steps"])

        calls = []
        def failing_executor(command, **_kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=1)
        runner._email_already_sent = lambda _date: True
        runner._evaluation_status = lambda _date, code, _started=0: "failed"
        result = run_daily("20260810", executor=failing_executor, calendar_status_getter=lambda _d: "open")
        assert result["status"] == "failed"
        assert result["steps"][-1]["step"] == "daily_reconcile"
        assert result["steps"][-1]["status"] == "failed"
        assert any(item["step"] == "daily_email" and item["status"] == "blocked" for item in result["steps"])

        runner._email_already_sent = lambda _date: True
        runner._evaluation_status = lambda _date, code, _started=0: "success"
        result = run_daily("20260810", executor=lambda *_a, **_k: SimpleNamespace(returncode=0), calendar_status_getter=lambda _d: "open")
        assert any(item["step"] == "daily_email" and item.get("reason") == "already_sent" for item in result["steps"])

        timeout_calls = []
        def timeout_executor(command, **_kwargs):
            timeout_calls.append(command)
            raise subprocess.TimeoutExpired(command, 1)
        result = run_daily("20260810", executor=timeout_executor, calendar_status_getter=lambda _d: "open")
        assert result["status"] == "failed"
        assert result["steps"][-1]["step"] == "daily_reconcile"
        assert len([cmd for cmd in timeout_calls if any("daily_reconciliation" in part for part in cmd)]) == 2
    finally:
        runner.start_task, runner.finish_task = original_start, original_finish
        runner._email_already_sent = original_email
        runner._pipeline_already_completed = original_completed
        runner._evaluation_status = original_eval
        runner.fail_stale_pipeline_tasks = original_stale
    print("[OK] pipeline runner regression check")


if __name__ == "__main__":
    main()
