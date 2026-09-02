"""Safely rerender the Evaluation section without rebuilding stock signals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2

from analysis.evaluation_report_reader import (
    load_correction_effectiveness_summary,
    load_t1_evaluation_summary,
)
from analysis.report_renderer import (
    append_compact_evaluation_section,
    append_evaluation_section,
)
from analysis.trade_calendar import normalize_trade_date
from data.config import DATABASE_DSN, REPORT_DIR


REPORT_DIR = Path(REPORT_DIR) / "daily"
SECTION_START = "## 1. 昨日观察池兑现复盘（T+1）"
SECTION_ENDS = ("## 2. 次日操作计划", "## 2. 市场与交易环境")


def replace_evaluation_section(report: str, t1_data: dict, *, compact=None) -> str:
    start = report.find(SECTION_START)
    candidates = [
        report.find(marker, start + len(SECTION_START)) for marker in SECTION_ENDS
    ]
    end = min(value for value in candidates if value >= 0) if any(
        value >= 0 for value in candidates
    ) else -1
    if start < 0 or end < 0 or end <= start:
        raise ValueError("canonical Evaluation section markers are missing")
    lines = []
    if compact is None:
        compact = report.find("## 2. 次日操作计划", start) == end
    if compact:
        append_compact_evaluation_section(lines, t1_data)
    else:
        append_evaluation_section(lines, t1_data)
    section = "\n".join(lines).rstrip() + "\n\n"
    return report[:start] + section + report[end:]


def _load_report(conn, trade_date: str) -> tuple[str, str]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT report_mode, content
        FROM daily_report
        WHERE trade_date=%s
        ORDER BY CASE WHEN report_mode='unified' THEN 0 ELSE 1 END,
                 created_at DESC
        LIMIT 1
        """,
        (f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}",),
    )
    row = cur.fetchone()
    cur.close()
    if not row or not row[1]:
        raise RuntimeError(f"canonical daily report is missing for {trade_date}")
    return str(row[0]), str(row[1])


def rerender_report(trade_date: str, *, conn=None) -> dict:
    date_text = normalize_trade_date(trade_date)
    own_conn = conn is None
    db = conn or psycopg2.connect(DATABASE_DSN)
    try:
        mode, old_report = _load_report(db, date_text)
        t1_data = load_t1_evaluation_summary(date_text)
        t1_data["correction_effectiveness"] = load_correction_effectiveness_summary(date_text)
        new_report = replace_evaluation_section(old_report, t1_data)
        changed = new_report != old_report
        updated_rows = 0
        path = REPORT_DIR / f"daily_report_{date_text}.md"
        appendix_path = REPORT_DIR / f"daily_report_{date_text}_appendix.md"
        if changed:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE daily_report
                SET content=%s, created_at=CURRENT_TIMESTAMP
                WHERE trade_date=%s AND report_mode=%s
                  AND content IS DISTINCT FROM %s
                """,
                (
                    new_report,
                    f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}",
                    mode,
                    new_report,
                ),
            )
            updated_rows = cur.rowcount
            cur.close()
            db.commit()
        else:
            db.rollback()
        file_changed = not path.exists() or path.read_text(encoding="utf-8") != new_report
        if file_changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_report, encoding="utf-8")
        appendix_changed = False
        appendix_source = None
        if appendix_path.exists():
            appendix_source = appendix_path.read_text(encoding="utf-8")
        elif "## 2. 市场与交易环境" in old_report:
            # Historical reports already contain the full audit detail.  On
            # their first safe rerender, preserve that document as the
            # appendix without rerunning selectors or rebuilding signals.
            appendix_source = old_report
        elif "recovery_mode: immutable_snapshot" in old_report:
            # Recovery may have been performed on another host sharing the
            # database but not its report filesystem. Rebuild only the audit
            # appendix from the same immutable snapshots on this host.
            from analysis.report_recovery import (
                _load_snapshot_rows,
                render_recovery_bundle,
            )
            rows = _load_snapshot_rows(db, date_text)
            _, appendix_source = render_recovery_bundle(date_text, rows, t1_data)
        if appendix_source is not None:
            new_appendix = replace_evaluation_section(
                appendix_source, t1_data, compact=False,
            )
            appendix_changed = (
                not appendix_path.exists() or new_appendix != appendix_source
            )
            if appendix_changed:
                appendix_path.write_text(new_appendix, encoding="utf-8")
        return {
            "status": "success",
            "trade_date": date_text,
            "mode": "rerender",
            "changed": changed,
            "updated_rows": updated_rows,
            "file_changed": file_changed,
            "appendix_changed": appendix_changed,
            "signal_tables_touched": [],
        }
    finally:
        if own_conn:
            db.close()


def main():
    parser = argparse.ArgumentParser(description="Rerender Evaluation without rebuilding signals")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    print(json.dumps(rerender_report(args.date), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
