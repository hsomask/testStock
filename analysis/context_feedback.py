"""Context-aware feedback stats for rule correction.

This sidecar summarizes historical evaluation by strategy plus context
dimensions. It is intentionally report/JSON based so it can guide tomorrow's
trade plan without adding database schema during the first correction phase.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2

from data.config import DATABASE_DSN, REPORT_DIR


EVAL_DIR = REPORT_DIR / "evaluation"
DEFAULT_WINDOW_DAYS = 20
DEFAULT_MIN_SAMPLE = 8


def _yyyymmdd(value):
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")[:8]


def _sql_date(date_text):
    text = str(date_text or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid date: {date_text}")
    return text


def _table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return bool(cur.fetchone()[0])


def _num(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _bucket_direction(score):
    val = _num(score)
    if val is None:
        return "unknown"
    if val >= 80:
        return "mainline"
    return "non_mainline"


def _score(win_rate, avg_return, failed_rate):
    score = 50.0
    if win_rate is not None:
        score += (win_rate - 0.5) * 60
    if avg_return is not None:
        score += avg_return * 500
    if failed_rate is not None:
        score -= failed_rate * 35
    return round(max(0, min(100, score)), 1)


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


def _status(sample, win_rate, avg_return, failed_rate, min_sample):
    if sample < min_sample:
        return "normal", f"样本不足{min_sample}条，仅记录"
    win = win_rate or 0
    avg = avg_return or 0
    failed = failed_rate or 0
    if failed >= 0.45 or avg <= -0.015:
        return "blocked", "场景失败率/平均收益明显偏弱，需要强降级"
    if win < 0.45 or avg < 0:
        return "weak", "场景胜率或平均收益偏弱，需要降级"
    if win >= 0.60 and failed <= 0.25 and avg >= 0:
        return "hot", "场景反馈较好，可保留优先级"
    return "normal", "场景反馈中性，暂不调整"


def _load_rows(as_of_date, window_days):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")
    conn = psycopg2.connect(DATABASE_DSN)
    try:
        cur = conn.cursor()
        required = [
            "candidate_feature_snapshot",
            "watchlist_evaluation_result",
            "watchlist_evaluation_summary",
            "canonical_daily_evaluation_summary",
            "canonical_daily_evaluation_result",
        ]
        missing = [name for name in required if not _table_exists(cur, name)]
        cur.close()
        if missing:
            raise RuntimeError(f"missing tables: {', '.join(missing)}")

        sql_as_of = _sql_date(as_of_date)
        sql = """
        WITH recent_dates AS (
            SELECT DISTINCT as_of_date
            FROM canonical_daily_evaluation_summary
            WHERE eval_mode = 'daily'
              AND as_of_date <= %s
            ORDER BY as_of_date DESC
            LIMIT %s
        ),
        latest_summary AS (
            SELECT DISTINCT ON (signal_date, as_of_date)
                signal_date, as_of_date, coverage_1d, generated_at
            FROM canonical_daily_evaluation_summary
            WHERE eval_mode = 'daily'
              AND as_of_date IN (SELECT as_of_date FROM recent_dates)
            ORDER BY signal_date, as_of_date, generated_at DESC
        )
        SELECT
            c.trade_date,
            s.as_of_date,
            c.strategy,
            c.primary_direction,
            c.market_status,
            c.canonical_final_layer AS rule_layer,
            c.feature_json #>> '{plan,direction_fit_score}' AS direction_fit_score,
            c.feature_json #>> '{plan,entry_quality}' AS entry_quality,
            r.next_1d_return,
            r.feedback_label,
            s.coverage_1d
        FROM candidate_feature_snapshot c
        JOIN latest_summary s
          ON s.signal_date = TO_CHAR(c.trade_date, 'YYYYMMDD')
        JOIN canonical_daily_evaluation_result r
          ON r.signal_id = c.signal_id
         AND r.eval_mode = 'daily'
         AND r.signal_trade_date = s.signal_date
         AND r.as_of_date = s.as_of_date
        WHERE r.next_1d_return IS NOT NULL
          AND COALESCE(r.price_status, 'ok') = 'ok'
        """
        df = pd.read_sql(sql, conn, params=(sql_as_of, int(window_days)))
    finally:
        conn.close()
    if df.empty:
        return df
    df["trade_date"] = df["trade_date"].map(_yyyymmdd)
    df["as_of_date"] = df["as_of_date"].map(_yyyymmdd)
    df["direction_bucket"] = df["direction_fit_score"].map(_bucket_direction)
    df["entry_quality"] = df["entry_quality"].fillna("unknown")
    df["quality_weight"] = df["coverage_1d"].map(_quality_weight)
    df = df[df["quality_weight"] > 0].copy()
    return df


def _summarize_group(df, dimension, keys, min_sample):
    rows = []
    if df.empty:
        return rows
    for values, group in df.groupby(keys, dropna=False):
        if not isinstance(values, tuple):
            values = (values,)
        ret = pd.to_numeric(group["next_1d_return"], errors="coerce")
        sample = int(ret.notna().sum())
        if sample <= 0:
            continue
        weights = pd.to_numeric(group["quality_weight"], errors="coerce").fillna(0)
        valid = ret.notna() & (weights > 0)
        if not valid.any():
            continue
        ret_valid = ret[valid]
        weights_valid = weights[valid]
        weight_sum = float(weights_valid.sum())
        win_rate = float(((ret_valid > 0).astype(float) * weights_valid).sum() / weight_sum)
        avg_return = float((ret_valid * weights_valid).sum() / weight_sum)
        failed_rate = float(((ret_valid <= -0.03).astype(float) * weights_valid).sum() / weight_sum)
        status, reason = _status(weight_sum, win_rate, avg_return, failed_rate, min_sample)
        item = {
            "dimension": dimension,
            "sample_count": sample,
            "weighted_sample_count": round(weight_sum, 2),
            "win_rate_1d": win_rate,
            "avg_next_1d_return": avg_return,
            "failed_rate": failed_rate,
            "feedback_score": _score(win_rate, avg_return, failed_rate),
            "status": status,
            "reason": reason,
        }
        for key, value in zip(keys, values):
            item[key] = None if pd.isna(value) else str(value)
        rows.append(item)
    return rows


def compute_context_feedback(as_of_date=None, window_days=DEFAULT_WINDOW_DAYS, min_sample=DEFAULT_MIN_SAMPLE, save=True):
    as_of_date = as_of_date or datetime.now().strftime("%Y%m%d")
    df = _load_rows(as_of_date, window_days)
    stats = []
    if not df.empty:
        stats.extend(_summarize_group(df, "strategy_market", ["strategy", "market_status"], min_sample))
        stats.extend(_summarize_group(df, "strategy_direction", ["strategy", "direction_bucket"], min_sample))
        stats.extend(_summarize_group(df, "strategy_entry", ["strategy", "entry_quality"], min_sample))
        stats.extend(_summarize_group(df, "direction", ["primary_direction"], min_sample))

    result = {
        "as_of_date": str(as_of_date).replace("-", "")[:8],
        "window_days": int(window_days),
        "min_sample": int(min_sample),
        "row_count": int(len(df)),
        "stats": sorted(stats, key=lambda x: (x["dimension"], x.get("strategy") or "", x.get("feedback_score") or 0)),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if save:
        save_context_feedback(result)
    return result


def save_context_feedback(result):
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    as_of_date = result.get("as_of_date") or datetime.now().strftime("%Y%m%d")
    json_path = EVAL_DIR / f"context_feedback_{as_of_date}.json"
    latest_path = EVAL_DIR / "context_feedback_latest.json"
    md_path = EVAL_DIR / f"context_feedback_{as_of_date}.md"
    text = json.dumps(result, ensure_ascii=False, indent=2)
    json_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path


def render_markdown(result):
    lines = [
        "# 场景反馈纠偏统计",
        "",
        f"- as_of_date: {result.get('as_of_date')}",
        f"- window_days: {result.get('window_days')}",
        f"- row_count: {result.get('row_count')}",
        "",
        "| 维度 | 策略/方向 | 场景 | 样本 | 胜率 | 平均T+1 | 失败率 | 状态 |",
        "|------|-----------|------|------|------|--------|--------|------|",
    ]
    for item in sorted(result.get("stats", []), key=lambda x: (x.get("status") != "blocked", x.get("status") != "weak", x["dimension"], -(x.get("sample_count") or 0)))[:80]:
        name = item.get("strategy") or item.get("primary_direction") or "-"
        scene = item.get("market_status") or item.get("direction_bucket") or item.get("entry_quality") or "-"
        lines.append(
            f"| {item['dimension']} | {name} | {scene} | {item['sample_count']} | "
            f"{item['win_rate_1d']:.1%} | {item['avg_next_1d_return']:.2%} | "
            f"{item['failed_rate']:.1%} | {item['status']} |"
        )
    return "\n".join(lines) + "\n"


def load_latest_context_feedback():
    path = EVAL_DIR / "context_feedback_latest.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    lookup = {}
    for item in data.get("stats", []):
        dim = item.get("dimension")
        strategy = item.get("strategy") or ""
        scene = item.get("market_status") or item.get("direction_bucket") or item.get("entry_quality") or item.get("primary_direction") or ""
        lookup[(dim, strategy, scene)] = item
        if dim == "direction":
            lookup[(dim, "", scene)] = item
    return lookup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=str, default=None)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--min-sample", type=int, default=DEFAULT_MIN_SAMPLE)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    result = compute_context_feedback(
        as_of_date=args.as_of,
        window_days=args.window,
        min_sample=args.min_sample,
        save=not args.no_save,
    )
    print(f"context feedback rows: {len(result.get('stats', []))}, source rows: {result.get('row_count')}")
    weak = [x for x in result.get("stats", []) if x.get("status") in ("weak", "blocked")]
    for item in weak[:20]:
        scene = item.get("market_status") or item.get("direction_bucket") or item.get("entry_quality") or item.get("primary_direction") or "-"
        name = item.get("strategy") or item.get("primary_direction") or "-"
        print(
            f"- {item['dimension']} {name}/{scene}: sample={item['sample_count']} "
            f"win={item['win_rate_1d']:.1%} avg={item['avg_next_1d_return']:.2%} "
            f"failed={item['failed_rate']:.1%} status={item['status']}"
        )


if __name__ == "__main__":
    main()
