"""Fail-safe task ledger built on the existing ``job_run_log`` table."""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager

import psycopg2

from data.config import DATABASE_DSN


logger = logging.getLogger(__name__)
RUN_SCHEMA_VERSION = "task_ledger_v1"
VALID_STATUSES = {
    "pending", "running", "success", "deferred", "skipped", "failed", "blocked"
}


def _connect():
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    return psycopg2.connect(DATABASE_DSN)


def _normalize_status(status):
    value = str(status or "").strip().lower()
    if value not in VALID_STATUSES:
        raise ValueError(f"invalid task status: {status}")
    return value


def start_task(
    job_name,
    trade_date=None,
    *,
    parent_run_id=None,
    trigger_type="direct",
    attempt_no=1,
    idempotency_key=None,
    metadata=None,
    required=False,
):
    """Start one task run. Ledger failure is non-fatal unless required=True."""
    run_id = str(uuid.uuid4())
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO job_run_log (
                run_id, run_schema_version, job_name, trade_date, status,
                parent_run_id, trigger_type, attempt_no, idempotency_key,
                metadata_json
            ) VALUES (%s, %s, %s, %s, 'running', %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                run_id, RUN_SCHEMA_VERSION, job_name, trade_date,
                parent_run_id, trigger_type, int(attempt_no), idempotency_key,
                json.dumps(metadata or {}, ensure_ascii=False, default=str),
            ),
        )
        row_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return {"id": row_id, "run_id": run_id, "job_name": job_name}
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        if required:
            raise
        logger.warning("task ledger start failed for %s: %s", job_name, exc)
        return None
    finally:
        if conn is not None:
            conn.close()


def finish_task(task_run, status, *, error_message=None, metadata=None, required=False):
    """Finish a task run without changing the business task's outcome."""
    if not task_run:
        return False
    normalized = _normalize_status(status)
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE job_run_log
            SET status = %s,
                finished_at = CURRENT_TIMESTAMP,
                duration_seconds = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)),
                error_message = %s,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb
            WHERE run_id = %s
            """,
            (
                normalized, error_message,
                json.dumps(metadata or {}, ensure_ascii=False, default=str),
                task_run["run_id"],
            ),
        )
        updated = cur.rowcount == 1
        conn.commit()
        cur.close()
        return updated
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        if required:
            raise
        logger.warning("task ledger finish failed for %s: %s", task_run, exc)
        return False
    finally:
        if conn is not None:
            conn.close()


@contextmanager
def task_run(job_name, trade_date=None, **kwargs):
    run = start_task(job_name, trade_date, **kwargs)
    try:
        yield run
    except Exception as exc:
        finish_task(run, "failed", error_message=str(exc))
        raise
    else:
        finish_task(run, "success")
