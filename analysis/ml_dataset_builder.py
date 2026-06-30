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
    "strategy_feedback_score", "strategy_feedback_status",
    "strategy_feedback_win_rate_1d", "strategy_feedback_failed_rate",
    "strategy_feedback_sample_count",
]


TARGET_COLUMNS = [
    "next_1d_return", "next_3d_return", "max_3d_return", "max_3d_drawdown",
    "feedback_label", "feedback_score", "attribution_text",
    "success_label", "strong_label", "weak_label", "failed_label",
]


QUALITY_COLUMNS = [
    "coverage_1d", "evaluated_1d", "total_signals", "quality_weight",
    "train_eligible", "confidence_level", "conclusion_level",
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
    df["train_eligible"] = (df["coverage_1d"].fillna(0).astype(float) >= float(min_coverage)).astype(int)

    ret = pd.to_numeric(df["next_1d_return"], errors="coerce")
    df["success_label"] = (ret >= 0).astype(int)
    df["strong_label"] = (ret >= 0.02).astype(int)
    df["weak_label"] = (ret <= -0.02).astype(int)
    df["failed_label"] = (ret <= -0.03).astype(int)

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
