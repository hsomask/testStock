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
LAYER_RANK = {
    "候选低吸": 0,
    "只观察": 1,
    "交易条件不满足": 2,
    "高风险回避": 3,
    "不可交易过滤": 4,
}


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


def _has_text(value):
    return value is not None and not pd.isna(value) and bool(str(value).strip())


def _eligible_correction_rows(df):
    if df.empty:
        return df.copy()
    mask = (
        df["correction_engine_version"].map(_has_text)
        & df["base_layer"].map(_has_text)
        & df["final_layer"].map(_has_text)
    )
    return df.loc[mask].copy()


def _limit_to_latest_dates(df, window_days):
    if df.empty or not window_days:
        return df.copy(), []
    dates = sorted({_yyyymmdd(value) for value in df["as_of_date"] if _yyyymmdd(value)})
    selected = dates[-int(window_days):]
    keys = df["as_of_date"].map(_yyyymmdd)
    return df.loc[keys.isin(selected)].copy(), selected


def _best_layer(values):
    layers = [str(value) for value in values if _has_text(value)]
    return min(layers, key=lambda value: LAYER_RANK.get(value, 99)) if layers else None


def _stock_level_rows(df):
    if df.empty:
        return df.copy()
    rows = []
    for (_, _, _), group in df.groupby(["trade_date", "as_of_date", "code"], dropna=False):
        first = group.iloc[0]
        base_layer = _best_layer(group["base_layer"])
        final_layer = _best_layer(group["final_layer"])
        tags = []
        for value in group["correction_tags"]:
            text = str(value or "")
            for tag in ("非今日主线", "高位追强", "短线偏高", "量能过热", "波段偏高",
                        "策略反馈", "场景反馈", "数据可信度不足"):
                if tag in text and tag not in tags:
                    tags.append(tag)
        strategies = sorted({str(value) for value in group["strategy"] if _has_text(value)})
        versions = sorted({
            str(value) for value in group["correction_engine_version"] if _has_text(value)
        })
        was_downgraded = (
            _has_text(base_layer)
            and _has_text(final_layer)
            and LAYER_RANK.get(final_layer, 99) > LAYER_RANK.get(base_layer, 99)
        )
        item = first.to_dict()
        item.update({
            "strategy": " / ".join(strategies),
            "base_layer": base_layer,
            "final_layer": final_layer,
            "correction_tags": " / ".join(tags),
            "correction_engine_version": " / ".join(versions),
            "was_downgraded": bool(was_downgraded),
        })
        item["downgrade_reason_group"] = _downgrade_reason_group(item["correction_tags"])
        item["correction_result"] = _correction_result(
            item.get("next_1d_return"), item["was_downgraded"]
        )
        rows.append(item)
    return pd.DataFrame(rows)


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
    kept_candidate = df[
        (~df["was_downgraded"])
        & (df["base_layer"] == "候选低吸")
        & (df["final_layer"] == "候选低吸")
    ]
    pit = downgraded[downgraded["correction_result"].isin(["pit_avoided", "pit_avoided_strong"])]
    false = downgraded[downgraded["correction_result"].isin(["false_negative", "false_negative_strong"])]
    down_avg = _safe_mean(downgraded["next_1d_return"]) if not downgraded.empty else None
    kept_avg = _safe_mean(kept_candidate["next_1d_return"]) if not kept_candidate.empty else None
    effectiveness = "sample_insufficient"
    if len(downgraded) >= 3 and down_avg is not None and kept_avg is not None:
        if down_avg < kept_avg:
            effectiveness = "effective"
        elif down_avg > kept_avg:
            effectiveness = "too_conservative"
        else:
            effectiveness = "neutral"
    pit_rate = _safe_rate(
        downgraded["correction_result"].isin(["pit_avoided", "pit_avoided_strong"])
    )
    false_rate = _safe_rate(
        downgraded["correction_result"].isin(["false_negative", "false_negative_strong"])
    )
    net_benefit = kept_avg - down_avg if kept_avg is not None and down_avg is not None else None
    sample_status = "可信" if len(df) >= 100 else ("观察期" if len(df) >= 30 else "样本不足")
    return {
        "total": int(len(df)),
        "downgraded": int(len(downgraded)),
        "kept_candidate": int(len(kept_candidate)),
        "pit_avoided": int(len(pit)),
        "false_negative": int(len(false)),
        "downgraded_avg_return": down_avg,
        "kept_candidate_avg_return": kept_avg,
        "overall_avg_return": _safe_mean(ret),
        "pit_avoid_rate": pit_rate,
        "false_negative_rate": false_rate,
        "correction_net_benefit": net_benefit,
        "sample_status": sample_status,
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


def _version_summary(df):
    rows = []
    if df.empty:
        return rows
    for version, group in df.groupby("correction_engine_version", dropna=False):
        summary = _build_summary(group)
        rows.append({
            "version": str(version or "unknown"),
            "sample_count": summary.get("total", 0),
            "downgraded": summary.get("downgraded", 0),
            "pit_avoid_rate": summary.get("pit_avoid_rate"),
            "false_negative_rate": summary.get("false_negative_rate"),
            "downgraded_avg_return": summary.get("downgraded_avg_return"),
        })
    return sorted(rows, key=lambda item: item["version"])


def build_correction_effectiveness(as_of=None, min_coverage=0.80, window_days=5, save=True):
    loaded_df = _load_rows(as_of=as_of, min_coverage=min_coverage)
    eligible_df = _eligible_correction_rows(loaded_df)
    eligible_df, window_dates = _limit_to_latest_dates(eligible_df, window_days)
    if window_dates:
        loaded_keys = loaded_df["as_of_date"].map(_yyyymmdd)
        loaded_df = loaded_df.loc[loaded_keys.isin(window_dates)].copy()
    df = _stock_level_rows(eligible_df)
    as_of_date = str(as_of or datetime.now().strftime("%Y%m%d")).replace("-", "")[:8]
    if not df.empty:
        df["trade_date"] = df["trade_date"].map(_yyyymmdd)
        df["as_of_date"] = df["as_of_date"].map(_yyyymmdd)
        df["sample_quality_tier"] = df["coverage_1d"].map(_quality_tier)

    downgraded_df = df[df["was_downgraded"]] if not df.empty else df
    result = {
        "as_of_date": as_of_date,
        "min_coverage": float(min_coverage),
        "window_days": int(window_days),
        "window_dates": window_dates,
        "source_rows": int(len(loaded_df)),
        "eligible_rows": int(len(df)),
        "eligible_strategy_rows": int(len(eligible_df)),
        "excluded_legacy_rows": int(len(loaded_df) - len(eligible_df)),
        "summary": _build_summary(df),
        "by_reason": _group_summary(downgraded_df),
        "by_version": _version_summary(df),
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
        f"- 来源记录：{result.get('source_rows', summary.get('total', 0))}",
        f"- 统计窗口：最近 {result.get('window_days', 5)} 个评价日",
        f"- 有效股票样本：{result.get('eligible_rows', summary.get('total', 0))}",
        f"- 策略明细行：{result.get('eligible_strategy_rows', summary.get('total', 0))}",
        f"- 排除旧格式记录：{result.get('excluded_legacy_rows', 0)}",
        f"- 总样本：{summary.get('total', 0)}",
        f"- 被纠偏降级：{summary.get('downgraded', 0)}",
        f"- 避坑：{summary.get('pit_avoided', 0)}",
        f"- 误杀：{summary.get('false_negative', 0)}",
        f"- 避坑率：{_fmt_pct(summary.get('pit_avoid_rate'))}",
        f"- 误杀率：{_fmt_pct(summary.get('false_negative_rate'))}",
        f"- 降级组平均T+1：{_fmt_pct(summary.get('downgraded_avg_return'))}",
        f"- 保留候选平均T+1：{_fmt_pct(summary.get('kept_candidate_avg_return'))}",
        f"- 纠偏净收益：{_fmt_pct(summary.get('correction_net_benefit'))}",
        f"- 样本状态：{summary.get('sample_status')}",
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
    lines.extend([
        "",
        "## 3. 按版本拆分",
        "",
        "| 引擎版本 | 股票样本 | 降级 | 避坑率 | 误杀率 | 降级组T+1 |",
        "|----------|----------|------|--------|--------|-----------|",
    ])
    for row in result.get("by_version", []):
        lines.append(
            f"| {row['version']} | {row['sample_count']} | {row['downgraded']} | "
            f"{_fmt_pct(row.get('pit_avoid_rate'))} | {_fmt_pct(row.get('false_negative_rate'))} | "
            f"{_fmt_pct(row.get('downgraded_avg_return'))} |"
        )
    lines.extend(["", "## 4. 明细", ""])
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
    parser.add_argument("--window-days", type=int, default=5)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = build_correction_effectiveness(
        as_of=args.as_of,
        min_coverage=args.min_coverage,
        window_days=args.window_days,
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
