"""Check candidate_feature_snapshot completeness for ML/correction fields.

Run:
  python -m analysis.snapshot_integrity_check --date 20260703
"""
import argparse
import json
from datetime import datetime

import psycopg2

from data.config import DATABASE_DSN, REPORT_DIR


EVAL_DIR = REPORT_DIR / "evaluation"

REQUIRED_PLAN_FIELDS = [
    "base_layer",
    "final_layer",
    "decision_score",
    "direction_fit_score",
    "entry_quality",
    "correction_level",
    "correction_tags",
    "display_reason",
    "correction_engine_version",
]

REQUIRED_CONTEXT_FIELDS = [
    "market_status",
    "market_score",
    "trade_mode",
    "data_confidence",
    "correction_engine_version",
]


def _sql_date(date_text):
    text = str(date_text or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid date: {date_text}")
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return bool(cur.fetchone()[0])


def _field_expr(path):
    # Postgres JSON path text extraction for feature_json #>> '{plan,key}'.
    return "feature_json #>> '{" + ",".join(path) + "}'"


def run_snapshot_integrity_check(date=None, save=True):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    date = str(date or datetime.now().strftime("%Y%m%d")).replace("-", "")[:8]
    sql_date = _sql_date(date)
    conn = psycopg2.connect(DATABASE_DSN)
    try:
        cur = conn.cursor()
        if not _table_exists(cur, "candidate_feature_snapshot"):
            raise RuntimeError("candidate_feature_snapshot table does not exist")

        cur.execute(
            "SELECT COUNT(*) FROM candidate_feature_snapshot WHERE trade_date = %s",
            (sql_date,),
        )
        total = int(cur.fetchone()[0] or 0)

        field_results = []
        for scope, fields in (("plan", REQUIRED_PLAN_FIELDS), ("context", REQUIRED_CONTEXT_FIELDS)):
            for field in fields:
                expr = _field_expr([scope, field])
                cur.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM candidate_feature_snapshot
                    WHERE trade_date = %s
                      AND NULLIF({expr}, '') IS NOT NULL
                    """,
                    (sql_date,),
                )
                present = int(cur.fetchone()[0] or 0)
                field_results.append({
                    "scope": scope,
                    "field": field,
                    "present": present,
                    "missing": max(total - present, 0),
                    "coverage": present / total if total else 0,
                })
        cur.close()
    finally:
        conn.close()

    min_coverage = min((x["coverage"] for x in field_results), default=0)
    status = "ok" if total > 0 and min_coverage >= 0.95 else ("empty" if total == 0 else "warning")
    result = {
        "date": date,
        "total_snapshots": total,
        "status": status,
        "min_field_coverage": min_coverage,
        "fields": field_results,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if save:
        save_report(result)
    return result


def save_report(result):
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    date = result.get("date") or datetime.now().strftime("%Y%m%d")
    json_path = EVAL_DIR / f"snapshot_integrity_{date}.json"
    md_path = EVAL_DIR / f"snapshot_integrity_{date}.md"
    latest_path = EVAL_DIR / "snapshot_integrity_latest.json"
    text = json.dumps(result, ensure_ascii=False, indent=2)
    json_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path


def render_markdown(result):
    lines = [
        f"# 快照完整性检查 - {result.get('date')}",
        "",
        f"- 快照数: {result.get('total_snapshots', 0)}",
        f"- 状态: {result.get('status')}",
        f"- 最低字段覆盖: {result.get('min_field_coverage', 0):.1%}",
        "",
        "| 范围 | 字段 | 覆盖 | 缺失 |",
        "|------|------|------|------|",
    ]
    for item in result.get("fields", []):
        lines.append(
            f"| {item['scope']} | {item['field']} | {item['coverage']:.1%} | {item['missing']} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_snapshot_integrity_check(date=args.date, save=not args.no_save)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"snapshot integrity: date={result['date']} total={result['total_snapshots']} "
            f"status={result['status']} min_coverage={result['min_field_coverage']:.1%}"
        )


if __name__ == "__main__":
    main()
