"""
Build ML-ready training datasets from candidate snapshots and formal evaluation.

This is a sidecar exporter only. It does not train a model and does not affect
recommendations.

Examples:
  python -m analysis.ml_dataset_builder
  python -m analysis.ml_dataset_builder --as-of 20260630
  python -m analysis.ml_dataset_builder --min-coverage 0.9
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2

from data.config import DATABASE_DSN, REPORT_DIR


ML_DIR = REPORT_DIR / "ml"


FEATURE_COLUMNS = [
    "trade_date", "as_of_date", "code", "name", "strategy", "rule_layer",
    "primary_direction", "risk_level", "action_signal",
    "market_status", "market_score", "trade_mode", "position_cap",
    "sentiment_score", "sentiment_stage", "data_confidence",
    "close_price", "pct_chg", "pct_5d", "pct_20d", "volume_ratio",
    "turnover", "ma5", "ma10", "ma20",
    "observe_low", "observe_high", "pressure_price", "invalid_price",
    "base_layer", "final_layer", "decision_score",
    "direction_fit_score", "entry_quality", "correction_level",
    "correction_tags", "display_reason",
    "correction_engine_version", "strategy_feedback_version", "context_feedback_version",
    "strategy_feedback_score", "strategy_feedback_status",
    "strategy_feedback_win_rate_1d", "strategy_feedback_failed_rate",
    "strategy_feedback_sample_count",
]


TARGET_COLUMNS = [
    "next_1d_return", "next_3d_return", "max_3d_return", "max_3d_drawdown",
    "feedback_label", "feedback_score", "attribution_text",
    "failure_reason_group",
    "success_label", "strong_label", "weak_label", "failed_label",
    "was_downgraded", "downgrade_reason_group", "correction_result",
    "correction_effective_label", "false_negative_label",
]


QUALITY_COLUMNS = [
    "coverage_1d", "evaluated_1d", "total_signals", "quality_weight",
    "sample_quality_tier", "train_eligible", "confidence_level", "conclusion_level",
]


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


def _quality_weight(coverage):
    try:
        cov = float(coverage or 0)
    except Exception:
        cov = 0
    if cov >= 0.95:
        return 1.0
    if cov >= 0.90:
        return 0.8
    if cov >= 0.80:
        return 0.5
    return 0.0


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


def _as_bool_downgraded(row):
    base = str(row.get("base_layer") or "")
    final = str(row.get("final_layer") or row.get("rule_layer") or "")
    return bool(base and final and base != final)


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
    return "none"


def _correction_result(row):
    if not _as_bool_downgraded(row):
        return "not_downgraded"
    ret = row.get("next_1d_return")
    try:
        ret = float(ret)
    except Exception:
        return "unknown"
    if ret <= -0.03:
        return "pit_avoided_strong"
    if ret < 0:
        return "pit_avoided"
    if ret >= 0.03:
        return "false_negative_strong"
    if ret > 0:
        return "false_negative"
    return "neutral"


def _failure_reason_group(text):
    value = str(text or "")
    if "非今日主线" in value or "承接不足" in value:
        return "non_mainline_no_support"
    if "追高" in value or "涨幅接近涨停" in value or "涨幅偏高" in value:
        return "high_position_pullback"
    if "策略近期反馈偏弱" in value or "短线形态策略" in value:
        return "strategy_decay"
    if "量比过高" in value or "短线高潮" in value:
        return "market_emotion_reversal"
    if "跌破关键均线" in value:
        return "ma_breakdown"
    if "K线覆盖不足" in value or "数据不足" in value:
        return "data_insufficient"
    if value:
        return "other"
    return "unknown"


def _load_dataset(as_of=None, min_coverage=0.90):
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

        params = [min_coverage]
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
            COALESCE(c.risk_level, r.risk_level) AS risk_level,
            COALESCE(c.action_signal, r.action_signal) AS action_signal,
            c.market_status,
            c.market_score,
            c.trade_mode,
            c.position_cap,
            c.sentiment_score,
            c.sentiment_stage,
            c.data_confidence,
            c.close_price,
            c.pct_chg,
            c.pct_5d,
            c.pct_20d,
            c.volume_ratio,
            c.turnover,
            c.ma5,
            c.ma10,
            c.ma20,
            c.observe_low,
            c.observe_high,
            c.pressure_price,
            c.invalid_price,
            c.feature_json #>> '{{plan,base_layer}}' AS base_layer,
            c.feature_json #>> '{{plan,final_layer}}' AS final_layer,
            c.feature_json #>> '{{plan,decision_score}}' AS decision_score,
            c.feature_json #>> '{{plan,direction_fit_score}}' AS direction_fit_score,
            c.feature_json #>> '{{plan,entry_quality}}' AS entry_quality,
            c.feature_json #>> '{{plan,correction_level}}' AS correction_level,
            c.feature_json #>> '{{plan,correction_tags}}' AS correction_tags,
            c.feature_json #>> '{{plan,display_reason}}' AS display_reason,
            c.feature_json #>> '{{plan,correction_engine_version}}' AS correction_engine_version,
            c.feature_json #>> '{{plan,strategy_feedback_version}}' AS strategy_feedback_version,
            c.feature_json #>> '{{plan,context_feedback_version}}' AS context_feedback_version,
            c.strategy_feedback_score,
            c.strategy_feedback_status,
            c.strategy_feedback_win_rate_1d,
            c.strategy_feedback_failed_rate,
            c.strategy_feedback_sample_count,
            r.next_1d_return,
            r.next_3d_return,
            r.max_3d_return,
            r.max_3d_drawdown,
            r.feedback_label,
            r.feedback_score,
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

    if df.empty:
        return df

    df["trade_date"] = df["trade_date"].map(_yyyymmdd)
    df["as_of_date"] = df["as_of_date"].map(_yyyymmdd)
    df["quality_weight"] = df["coverage_1d"].map(_quality_weight)
    df["sample_quality_tier"] = df["coverage_1d"].map(_quality_tier)
    df["train_eligible"] = (df["coverage_1d"].fillna(0).astype(float) >= float(min_coverage)).astype(int)

    ret = pd.to_numeric(df["next_1d_return"], errors="coerce")
    df["success_label"] = (ret >= 0).astype(int)
    df["strong_label"] = (ret >= 0.02).astype(int)
    df["weak_label"] = (ret <= -0.02).astype(int)
    df["failed_label"] = (ret <= -0.03).astype(int)
    df["failure_reason_group"] = df["attribution_text"].map(_failure_reason_group)
    df["was_downgraded"] = df.apply(lambda row: 1 if _as_bool_downgraded(row) else 0, axis=1)
    df["downgrade_reason_group"] = df["correction_tags"].map(_downgrade_reason_group)
    df["correction_result"] = df.apply(_correction_result, axis=1)
    df["correction_effective_label"] = df["correction_result"].isin(["pit_avoided", "pit_avoided_strong"]).astype(int)
    df["false_negative_label"] = df["correction_result"].isin(["false_negative", "false_negative_strong"]).astype(int)

    ordered = [c for c in FEATURE_COLUMNS + TARGET_COLUMNS + QUALITY_COLUMNS if c in df.columns]
    extras = [c for c in df.columns if c not in ordered]
    return df[ordered + extras]


def _fmt_pct(value):
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "N/A"


def _fmt_num(value):
    try:
        return f"{float(value):.2f}"
    except Exception:
        return "N/A"


def _group_summary(df, key):
    if df.empty or key not in df.columns:
        return pd.DataFrame()
    rows = []
    for name, g in df.groupby(key, dropna=False):
        ret = pd.to_numeric(g["next_1d_return"], errors="coerce")
        rows.append({
            key: name if pd.notna(name) else "N/A",
            "samples": len(g),
            "win_rate": float((ret >= 0).mean()) if len(g) else 0,
            "strong_rate": float((ret >= 0.02).mean()) if len(g) else 0,
            "weak_rate": float((ret <= -0.02).mean()) if len(g) else 0,
            "avg_next_1d_return": float(ret.mean()) if len(g) else 0,
        })
    return pd.DataFrame(rows).sort_values(["samples", "avg_next_1d_return"], ascending=[False, False])


def _write_markdown(df, path, as_of, min_coverage):
    lines = []
    title_date = as_of or datetime.now().strftime("%Y%m%d")
    lines.append(f"# ML 数据集体检 - {title_date}")
    lines.append("")
    lines.append("## 样本概览")
    lines.append("")
    if df.empty:
        lines.append("- 可训练样本：0")
        lines.append("- 结论：样本不足，暂不训练。")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    ret = pd.to_numeric(df["next_1d_return"], errors="coerce")
    lines.append(f"- 样本数：{len(df)}")
    lines.append(f"- 覆盖率门槛：{_fmt_pct(min_coverage)}")
    lines.append(f"- 日期范围：{df['trade_date'].min()} ~ {df['trade_date'].max()}")
    lines.append(f"- 平均 T+1 收益：{_fmt_pct(ret.mean())}")
    lines.append(f"- T+1 胜率：{_fmt_pct((ret >= 0).mean())}")
    lines.append(f"- 强样本占比：{_fmt_pct((ret >= 0.02).mean())}")
    lines.append(f"- 弱样本占比：{_fmt_pct((ret <= -0.02).mean())}")
    lines.append("")

    lines.append("## 策略分布")
    lines.append("")
    by_strategy = _group_summary(df, "strategy")
    if by_strategy.empty:
        lines.append("- 无策略样本。")
    else:
        lines.append("| 策略 | 样本 | 胜率 | 强样本 | 弱样本 | 平均T+1 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for _, row in by_strategy.iterrows():
            lines.append(
                f"| {row['strategy']} | {int(row['samples'])} | "
                f"{_fmt_pct(row['win_rate'])} | {_fmt_pct(row['strong_rate'])} | "
                f"{_fmt_pct(row['weak_rate'])} | {_fmt_pct(row['avg_next_1d_return'])} |"
            )
    lines.append("")

    lines.append("## 风险等级")
    lines.append("")
    by_risk = _group_summary(df, "risk_level")
    if by_risk.empty:
        lines.append("- 无风险等级样本。")
    else:
        lines.append("| 风险 | 样本 | 胜率 | 强样本 | 弱样本 | 平均T+1 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for _, row in by_risk.iterrows():
            lines.append(
                f"| {row['risk_level']} | {int(row['samples'])} | "
                f"{_fmt_pct(row['win_rate'])} | {_fmt_pct(row['strong_rate'])} | "
                f"{_fmt_pct(row['weak_rate'])} | {_fmt_pct(row['avg_next_1d_return'])} |"
            )
    lines.append("")

    lines.append("## 数据提示")
    lines.append("")
    sparse = by_strategy[by_strategy["samples"] < 20] if not by_strategy.empty else pd.DataFrame()
    if not sparse.empty:
        names = "、".join(str(x) for x in sparse["strategy"].tolist())
        lines.append(f"- 样本不足策略：{names}")
    else:
        lines.append("- 主要策略样本量暂未发现明显不足。")

    missing_cols = []
    for col in ["volume_ratio", "ma5", "ma20", "pct_20d", "primary_direction"]:
        if col in df.columns:
            ratio = float(df[col].isna().mean())
            if ratio > 0.2:
                missing_cols.append(f"{col} 缺失 {_fmt_pct(ratio)}")
    if missing_cols:
        lines.append("- 特征缺失偏高：" + "；".join(missing_cols))
    else:
        lines.append("- 核心特征缺失率正常。")
    lines.append("")

    lines.append("## 结论")
    lines.append("")
    if len(df) < 200:
        lines.append("- 当前样本仍偏少，适合做数据体检和旁路观察，暂不建议影响推荐排序。")
    elif len(df) < 500:
        lines.append("- 样本量可支持旁路评分，暂不建议直接替代规则。")
    else:
        lines.append("- 样本量可支持轻量模型实验，建议先用小权重旁路验证。")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_ml_dataset(as_of=None, min_coverage=0.90, out_dir=None):
    out_dir = Path(out_dir) if out_dir else ML_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = as_of or datetime.now().strftime("%Y%m%d")

    df = _load_dataset(as_of=as_of, min_coverage=min_coverage)

    csv_path = out_dir / f"ml_dataset_{suffix}.csv"
    latest_path = out_dir / "ml_dataset_latest.csv"
    summary_path = out_dir / f"ml_dataset_summary_{suffix}.md"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_csv(latest_path, index=False, encoding="utf-8-sig")
    _write_markdown(df, summary_path, as_of=suffix, min_coverage=min_coverage)

    return {
        "rows": len(df),
        "csv_path": str(csv_path),
        "latest_path": str(latest_path),
        "summary_path": str(summary_path),
    }


def main():
    parser = argparse.ArgumentParser(description="Build ML dataset from formal evaluation results")
    parser.add_argument("--as-of", type=str, default=None, help="Use evaluations up to this date YYYYMMDD")
    parser.add_argument("--min-coverage", type=float, default=0.90, help="Minimum evaluation coverage")
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory")
    parser.add_argument("--json", action="store_true", default=False, dest="json_output")
    args = parser.parse_args()

    result = build_ml_dataset(args.as_of, args.min_coverage, args.out_dir)
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"rows: {result['rows']}")
        print(f"csv: {result['csv_path']}")
        print(f"latest: {result['latest_path']}")
        print(f"summary: {result['summary_path']}")


if __name__ == "__main__":
    main()
