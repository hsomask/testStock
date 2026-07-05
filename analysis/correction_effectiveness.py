"""Audit whether correction downgrades avoided risk or killed opportunity.

This is a sidecar quality detector. It does not affect recommendations.

Run:
  python -m analysis.correction_effectiveness --as-of 20260703
"""
import argparse
import json
from datetime import datetime

import pandas as pd
import psycopg2

from data.config import DATABASE_DSN, REPORT_DIR


EVAL_DIR = REPORT_DIR / "evaluation"


def _connect():
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    return psycopg2.connect(DATABASE_DSN)


def _yyyymmdd(value):
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")[:8]


def _table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return bool(cur.fetchone()[0])


def _quality_tier(coverage):
    try:
        cov = float(coverage or 0)
    except Exception:
        cov = 0
    if cov >= 0.95:
        return "gold"
    if cov >= 0.90:
        return "silver"
    if cov >= 0.80:
        return "bronze"
    return "invalid"


def _downgrade_reason_group(tags):
    text = str(tags or "")
    if "非今日主线" in text:
        return "non_mainline"
    if any(x in text for x in ("高位追强", "短线偏高", "量能过热", "波段偏高")):
        return "entry_risk"
    if "策略反馈" in text:
        return "strategy_feedback"
    if "场景反馈" in text:
        return "context_feedback"
    if "数据可信度不足" in text:
        return "data_quality"
    return "other"


def _correction_result(ret, was_downgraded):
    if not was_downgraded:
        return "not_downgraded"
    try:
        value = float(ret)
    except Exception:
        return "unknown"
    if value <= -0.03:
        return "pit_avoided_strong"
    if value < 0:
        return "pit_avoided"
    if value >= 0.03:
        return "false_negative_strong"
    if value > 0:
        return "false_negative"
    return "neutral"


def _load_rows(as_of=None, min_coverage=0.80):
    conn = _connect()
    try:
        cur = conn.cursor()
        required = [
            "candidate_feature_snapshot",
            "watchlist_evaluation_result",
            "watchlist_evaluation_summary",
        ]
        missing = [name for name in required if not _table_exists(cur, name)]
        cur.close()
        if missing:
            raise RuntimeError(f"missing tables: {', '.join(missing)}")

        params = [float(min_coverage)]
        asof_filter = ""
        if as_of:
            asof_filter = "AND s.as_of_date <= %s"
            params.append(str(as_of).replace("-", "")[:8])

        sql = f"""
        WITH eligible_summary AS (
            SELECT
                signal_date,
                as_of_date,
                total_signals,
                evaluated_1d,
                coverage_1d,
                confidence_level,
                conclusion_level,
                generated_at
            FROM watchlist_evaluation_summary s
            WHERE eval_mode = 'daily'
              AND coverage_1d >= %s
              {asof_filter}
        ),
        latest_summary AS (
            SELECT DISTINCT ON (signal_date, as_of_date)
                signal_date, as_of_date, total_signals, evaluated_1d,
                coverage_1d, confidence_level, conclusion_level, generated_at
            FROM eligible_summary
            ORDER BY signal_date, as_of_date, generated_at DESC
        )
        SELECT
            c.trade_date,
            s.as_of_date,
            c.code,
            COALESCE(c.name, r.name) AS name,
            c.strategy,
            c.rule_layer,
            c.primary_direction,
            c.feature_json #>> '{{plan,base_layer}}' AS base_layer,
            c.feature_json #>> '{{plan,final_layer}}' AS final_layer,
            c.feature_json #>> '{{plan,decision_score}}' AS decision_score,
            c.feature_json #>> '{{plan,correction_level}}' AS correction_level,
            c.feature_json #>> '{{plan,correction_tags}}' AS correction_tags,
            c.feature_json #>> '{{plan,display_reason}}' AS display_reason,
            c.feature_json #>> '{{plan,correction_engine_version}}' AS correction_engine_version,
            r.next_1d_return,
            r.feedback_label,
            r.attribution_text,
            s.coverage_1d,
            s.evaluated_1d,
            s.total_signals,
            s.confidence_level,
            s.conclusion_level
        FROM candidate_feature_snapshot c
        JOIN latest_summary s
          ON s.signal_date = TO_CHAR(c.trade_date, 'YYYYMMDD')
        JOIN watchlist_evaluation_result r
          ON r.eval_mode = 'daily'
         AND r.signal_trade_date = s.signal_date
         AND r.as_of_date = s.as_of_date
         AND r.code = c.code
         AND COALESCE(r.strategy, '') = COALESCE(c.strategy, '')
        WHERE r.next_1d_return IS NOT NULL
          AND COALESCE(r.price_status, 'ok') = 'ok'
        ORDER BY c.trade_date, c.code, c.strategy, s.as_of_date
        """
        df = pd.read_sql(sql, conn, params=params)
    finally:
        conn.close()
    return df


def _safe_mean(series):
    if series.empty:
        return None
    return float(pd.to_numeric(series, errors="coerce").mean())


def _safe_rate(mask):
    if len(mask) == 0:
        return None
    return float(mask.mean())


def _build_summary(df):
    if df.empty:
        return {
            "total": 0,
            "downgraded": 0,
            "pit_avoided": 0,
            "false_negative": 0,
            "effectiveness": "no_data",
        }
    ret = pd.to_numeric(df["next_1d_return"], errors="coerce")
    downgraded = df[df["was_downgraded"]]
    kept_candidate = df[(~df["was_downgraded"]) & (df["final_layer"].fillna(df["rule_layer"]) == "候选低吸")]
    pit = downgraded[downgraded["correction_result"].isin(["pit_avoided", "pit_avoided_strong"])]
    false = downgraded[downgraded["correction_result"].isin(["false_negative", "false_negative_strong"])]
    down_avg = _safe_mean(downgraded["next_1d_return"]) if not downgraded.empty else None
    kept_avg = _safe_mean(kept_candidate["next_1d_return"]) if not kept_candidate.empty else None
    effectiveness = "sample_insufficient"
    if len(downgraded) >= 3:
        if down_avg is not None and kept_avg is not None and down_avg < kept_avg:
            effectiveness = "effective"
        elif down_avg is not None and kept_avg is not None and down_avg > kept_avg:
            effectiveness = "too_conservative"
        else:
            effectiveness = "neutral"
    return {
        "total": int(len(df)),
        "downgraded": int(len(downgraded)),
        "kept_candidate": int(len(kept_candidate)),
        "pit_avoided": int(len(pit)),
        "false_negative": int(len(false)),
        "downgraded_avg_return": down_avg,
        "kept_candidate_avg_return": kept_avg,
        "overall_avg_return": _safe_mean(ret),
        "effectiveness": effectiveness,
    }


def _group_summary(df):
    rows = []
    if df.empty:
        return rows
    for name, group in df.groupby("downgrade_reason_group", dropna=False):
        ret = pd.to_numeric(group["next_1d_return"], errors="coerce")
        rows.append({
            "reason_group": str(name or "unknown"),
            "sample_count": int(len(group)),
            "avg_next_1d_return": float(ret.mean()) if len(group) else None,
            "win_rate": _safe_rate(ret >= 0),
            "pit_avoided": int(group["correction_result"].isin(["pit_avoided", "pit_avoided_strong"]).sum()),
            "false_negative": int(group["correction_result"].isin(["false_negative", "false_negative_strong"]).sum()),
        })
    return sorted(rows, key=lambda x: (-x["sample_count"], x["reason_group"]))


def build_correction_effectiveness(as_of=None, min_coverage=0.80, save=True):
    df = _load_rows(as_of=as_of, min_coverage=min_coverage)
    as_of_date = str(as_of or datetime.now().strftime("%Y%m%d")).replace("-", "")[:8]
    if not df.empty:
        df["trade_date"] = df["trade_date"].map(_yyyymmdd)
        df["as_of_date"] = df["as_of_date"].map(_yyyymmdd)
        df["sample_quality_tier"] = df["coverage_1d"].map(_quality_tier)
        df["final_layer"] = df["final_layer"].fillna(df["rule_layer"])
        df["was_downgraded"] = df.apply(
            lambda row: bool(row.get("base_layer") and row.get("final_layer") and row.get("base_layer") != row.get("final_layer")),
            axis=1,
        )
        df["downgrade_reason_group"] = df["correction_tags"].map(_downgrade_reason_group)
        df["correction_result"] = df.apply(
            lambda row: _correction_result(row.get("next_1d_return"), row.get("was_downgraded")),
            axis=1,
        )

    downgraded_df = df[df["was_downgraded"]] if not df.empty else df
    result = {
        "as_of_date": as_of_date,
        "min_coverage": float(min_coverage),
        "summary": _build_summary(df),
        "by_reason": _group_summary(downgraded_df),
        "details": _details(downgraded_df),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if save:
        save_report(result)
    return result


def _details(df):
    if df.empty:
        return []
    rows = []
    cols = [
        "trade_date", "as_of_date", "code", "name", "strategy", "base_layer", "final_layer",
        "primary_direction", "correction_level", "correction_tags", "display_reason",
        "next_1d_return", "correction_result", "downgrade_reason_group", "sample_quality_tier",
    ]
    for _, row in df[cols].head(200).iterrows():
        item = {}
        for col in cols:
            value = row.get(col)
            if hasattr(value, "item"):
                value = value.item()
            item[col] = value
        rows.append(item)
    return rows


def _fmt_pct(value):
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.2%}"
    except Exception:
        return "N/A"


def render_markdown(result):
    summary = result.get("summary", {})
    lines = [
        f"# 纠偏效果复盘 - {result.get('as_of_date')}",
        "",
        "## 1. 总览",
        "",
        f"- 总样本：{summary.get('total', 0)}",
        f"- 被纠偏降级：{summary.get('downgraded', 0)}",
        f"- 避坑：{summary.get('pit_avoided', 0)}",
        f"- 误杀：{summary.get('false_negative', 0)}",
        f"- 降级组平均T+1：{_fmt_pct(summary.get('downgraded_avg_return'))}",
        f"- 保留候选平均T+1：{_fmt_pct(summary.get('kept_candidate_avg_return'))}",
        f"- 判断：{summary.get('effectiveness')}",
        "",
        "## 2. 按原因拆分",
        "",
        "| 原因 | 样本 | 平均T+1 | 胜率 | 避坑 | 误杀 |",
        "|------|------|----------|------|------|------|",
    ]
    for row in result.get("by_reason", []):
        lines.append(
            f"| {row['reason_group']} | {row['sample_count']} | {_fmt_pct(row.get('avg_next_1d_return'))} | "
            f"{_fmt_pct(row.get('win_rate'))} | {row['pit_avoided']} | {row['false_negative']} |"
        )
    lines.extend(["", "## 3. 明细", ""])
    if result.get("details"):
        lines.append("| 日期 | 股票 | 策略 | 原始 | 最终 | 原因组 | T+1 | 结果 |")
        lines.append("|------|------|------|------|------|--------|-----|------|")
        for item in result["details"][:50]:
            lines.append(
                f"| {item.get('trade_date')} | {item.get('name')} | {item.get('strategy')} | "
                f"{item.get('base_layer')} | {item.get('final_layer')} | {item.get('downgrade_reason_group')} | "
                f"{_fmt_pct(item.get('next_1d_return'))} | {item.get('correction_result')} |"
            )
    else:
        lines.append("暂无纠偏降级样本。")
    return "\n".join(lines) + "\n"


def save_report(result):
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    as_of = result.get("as_of_date") or datetime.now().strftime("%Y%m%d")
    json_path = EVAL_DIR / f"correction_effectiveness_{as_of}.json"
    md_path = EVAL_DIR / f"correction_effectiveness_{as_of}.md"
    latest_path = EVAL_DIR / "correction_effectiveness_latest.json"
    text = json.dumps(result, ensure_ascii=False, indent=2)
    json_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=str, default=None)
    parser.add_argument("--min-coverage", type=float, default=0.80)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = build_correction_effectiveness(
        as_of=args.as_of,
        min_coverage=args.min_coverage,
        save=not args.no_save,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        s = result.get("summary", {})
        print(
            f"correction effectiveness: total={s.get('total', 0)}, "
            f"downgraded={s.get('downgraded', 0)}, "
            f"pit={s.get('pit_avoided', 0)}, false={s.get('false_negative', 0)}, "
            f"effectiveness={s.get('effectiveness')}"
        )


if __name__ == "__main__":
    main()
