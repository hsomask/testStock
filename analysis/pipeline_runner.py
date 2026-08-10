"""Lightweight DAG runner that orchestrates existing business entrypoints."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from analysis.task_ledger import finish_task, start_task
from analysis.trade_calendar import get_calendar_status
from data.config import DATABASE_DSN


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Step:
    name: str
    command: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    timeout: int = 3600
    retries: int = 0
    always_run: bool = False


def daily_steps(trade_date):
    py = sys.executable
    return (
        Step("evaluation", ("bash", "scripts/evaluation_entrypoint.sh"), timeout=3600, retries=1),
        Step("daily_report", ("bash", "entrypoint.sh"), timeout=5400),
        Step("daily_email", (py, "-m", "analysis.email_sender", "--date", trade_date), ("daily_report",), timeout=900),
        Step(
            "daily_reconcile",
            (py, "-m", "analysis.daily_reconciliation", "--days", "10", "--as-of", trade_date, "--apply"),
            ("evaluation", "daily_report", "daily_email"),
            retries=1,
            always_run=True,
            timeout=900,
        ),
    )


def validate_steps(steps):
    names = [step.name for step in steps]
    if len(names) != len(set(names)):
        raise ValueError("duplicate DAG step name")
    known = set(names)
    for step in steps:
        unknown = set(step.depends_on) - known
        if unknown:
            raise ValueError(f"unknown dependency for {step.name}: {sorted(unknown)}")
    visited, active = set(), set()
    mapping = {step.name: step for step in steps}
    def visit(name):
        if name in active: raise ValueError(f"DAG cycle at {name}")
        if name in visited: return
        active.add(name)
        for dep in mapping[name].depends_on: visit(dep)
        active.remove(name); visited.add(name)
    for name in names: visit(name)
    return True


def _evaluation_status(trade_date, returncode, started_at=0):
    path = ROOT / "reports" / "evaluation" / f"evaluation_scheduler_check_{trade_date}.json"
    if path.exists() and path.stat().st_mtime >= started_at:
        try:
            status = json.loads(path.read_text(encoding="utf-8")).get("status")
            if status in {"defer", "skip", "error"}:
                return {"defer": "deferred", "skip": "skipped", "error": "failed"}[status]
        except (OSError, ValueError, TypeError):
            pass
    return "success" if returncode == 0 else "failed"


def _email_already_sent(trade_date):
    if not DATABASE_DSN:
        return False
    import psycopg2
    conn = psycopg2.connect(DATABASE_DSN)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM job_run_log WHERE trade_date=%s AND job_name='daily_email' AND status='success')",
            (f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}",),
        )
        value = bool(cur.fetchone()[0]); cur.close(); return value
    finally:
        conn.close()


def _pipeline_already_completed(trade_date):
    if not DATABASE_DSN:
        return False
    import psycopg2
    conn = psycopg2.connect(DATABASE_DSN)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM job_run_log WHERE trade_date=%s AND job_name='daily_pipeline' AND status IN ('success','deferred'))",
            (f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}",),
        )
        value = bool(cur.fetchone()[0]); cur.close(); return value
    finally:
        conn.close()


def run_daily(trade_date, *, dry_run=False, executor=None, force_email=False, force=False, calendar_status_getter=None):
    steps = daily_steps(trade_date)
    validate_steps(steps)
    if dry_run:
        return {"status": "dry_run", "trade_date": trade_date, "steps": [s.name for s in steps]}
    calendar_status = (calendar_status_getter or get_calendar_status)(trade_date)
    if calendar_status == "closed":
        return {"status": "skipped", "trade_date": trade_date, "reason": "non_trading_day", "steps": []}
    if not force and _pipeline_already_completed(trade_date):
        return {"status": "skipped", "trade_date": trade_date, "reason": "pipeline_already_completed", "steps": []}
    execute = executor or subprocess.run
    parent = start_task("daily_pipeline", trade_date, trigger_type="dag", required=True)
    statuses, details = {}, []
    env = os.environ.copy()
    env.update({"TRADE_DATE": trade_date, "AS_OF_DATE": trade_date, "SEND_DAILY_EMAIL": "0", "SEND_EVAL_EMAIL": "0"})
    try:
        for step in steps:
            blocked = any(statuses.get(dep) not in {"success", "deferred"} for dep in step.depends_on)
            if blocked and not step.always_run:
                statuses[step.name] = "blocked"
                details.append({"step": step.name, "status": "blocked"})
                continue
            if step.name == "daily_email" and not force_email and _email_already_sent(trade_date):
                statuses[step.name] = "skipped"
                details.append({"step": step.name, "status": "skipped", "reason": "already_sent"})
                continue
            child = start_task(f"pipeline_step:{step.name}", trade_date, parent_run_id=parent["run_id"], trigger_type="dag", required=True)
            outcome, error = "failed", None
            for attempt in range(step.retries + 1):
                try:
                    started_at = time.time()
                    proc = execute(step.command, cwd=ROOT, env=env, timeout=step.timeout, text=True)
                    outcome = _evaluation_status(trade_date, proc.returncode, started_at) if step.name == "evaluation" else ("success" if proc.returncode == 0 else "failed")
                    if outcome != "failed": break
                    error = f"exit_code={proc.returncode}"
                except subprocess.TimeoutExpired:
                    error = f"timeout={step.timeout}"
                except Exception as exc:
                    error = f"executor_error={exc}"
            finish_task(child, outcome, error_message=error, required=True)
            statuses[step.name] = outcome
            details.append({"step": step.name, "status": outcome, "error": error})
        failed = any(value in {"failed", "blocked"} for key, value in statuses.items() if key != "daily_reconcile")
        final = "failed" if failed else ("deferred" if "deferred" in statuses.values() else "success")
        finish_task(parent, final, metadata={"steps": details}, required=True)
        return {"status": final, "trade_date": trade_date, "steps": details}
    except Exception as exc:
        finish_task(parent, "failed", error_message=str(exc))
        raise


def main():
    parser = argparse.ArgumentParser(description="Run the existing daily workflow as a lightweight DAG")
    parser.add_argument("--date", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-email", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_daily(args.date.replace("-", "")[:8], dry_run=args.dry_run, force_email=args.force_email, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "failed": raise SystemExit(1)


if __name__ == "__main__":
    main()
