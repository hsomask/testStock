"""Rolling strategy feedback stats based on watchlist evaluation results."""
import argparse
from datetime import datetime

import psycopg2

from data.config import DATABASE_DSN


DEFAULT_WINDOW_DAYS = 20


def _sql_date(date_text):
    text = str(date_text or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid date: {date_text}")
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _status_for(sample_count, win_rate, avg_return, failed_rate, avg_drawdown):
    if sample_count < 8:
        return "normal", "样本不足8条，暂不做强弱降级"

    win = win_rate or 0
    avg = avg_return or 0
    failed = failed_rate or 0
    dd = avg_drawdown or 0

    if failed >= 0.45 or (avg <= -0.015 and dd <= -0.05):
        return "blocked", f"失败率{failed:.1%}偏高，策略短期需要回避"
    if win < 0.45 or avg < -0.01:
        return "weak", f"胜率{win:.1%}或均值{avg:.2%}偏弱，候选需要降级"
    if win >= 0.60 and failed <= 0.25 and avg >= 0:
        return "hot", f"胜率{win:.1%}且失败率{failed:.1%}较低，策略反馈较好"
    return "normal", "策略反馈中性，暂不调整"


def _score_for(win_rate, avg_return, strong_rate, failed_rate, avg_drawdown):
    score = 50.0
    if win_rate is not None:
        score += (win_rate - 0.5) * 60
    if avg_return is not None:
        score += avg_return * 500
    if strong_rate is not None:
        score += strong_rate * 20
    if failed_rate is not None:
        score -= failed_rate * 35
    if avg_drawdown is not None:
        score += avg_drawdown * 150
    return round(max(0, min(100, score)), 1)


def ensure_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_feedback_stats (
            id SERIAL PRIMARY KEY,
            trade_date DATE NOT NULL,
            strategy TEXT NOT NULL,
            window_days INTEGER NOT NULL,
            sample_count INTEGER,
            win_rate_1d NUMERIC,
            avg_next_1d_return NUMERIC,
            avg_max_3d_return NUMERIC,
            avg_max_3d_drawdown NUMERIC,
            strong_rate NUMERIC,
            failed_rate NUMERIC,
            feedback_score NUMERIC,
            status TEXT,
            reason TEXT,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (trade_date, strategy, window_days)
        )
        """
    )


def compute_strategy_feedback(as_of_date=None, window_days=DEFAULT_WINDOW_DAYS, save_db=True):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")

    as_of_date = as_of_date or datetime.now().strftime("%Y%m%d")
    sql_as_of = _sql_date(as_of_date)

    conn = psycopg2.connect(DATABASE_DSN)
    cur = conn.cursor()
    ensure_table(cur)

    cur.execute(
        """
        WITH recent_dates AS (
            SELECT DISTINCT as_of_date
            FROM watchlist_evaluation_result
            WHERE eval_mode = 'daily'
              AND as_of_date <= %s
            ORDER BY as_of_date DESC
            LIMIT %s
        )
        SELECT
            strategy,
            COUNT(*) AS sample_count,
            AVG(CASE WHEN next_1d_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate_1d,
            AVG(next_1d_return) AS avg_next_1d_return,
            AVG(max_3d_return) AS avg_max_3d_return,
            AVG(max_3d_drawdown) AS avg_max_3d_drawdown,
            AVG(CASE
                WHEN feedback_label = 'strong_follow'
                     OR next_1d_return >= 0.03
                     OR max_3d_return >= 0.06
                THEN 1.0 ELSE 0.0
            END) AS strong_rate,
            AVG(CASE
                WHEN feedback_label = 'failed'
                     OR next_1d_return <= -0.03
                     OR max_3d_drawdown <= -0.05
                THEN 1.0 ELSE 0.0
            END) AS failed_rate
        FROM watchlist_evaluation_result
        WHERE eval_mode = 'daily'
          AND as_of_date IN (SELECT as_of_date FROM recent_dates)
          AND next_1d_return IS NOT NULL
          AND COALESCE(strategy, '') <> ''
        GROUP BY strategy
        ORDER BY strategy
        """,
        (sql_as_of, int(window_days)),
    )

    rows = cur.fetchall()
    stats = []
    for row in rows:
        strategy = row[0]
        sample_count = int(row[1] or 0)
        win_rate = float(row[2]) if row[2] is not None else None
        avg_return = float(row[3]) if row[3] is not None else None
        avg_max = float(row[4]) if row[4] is not None else None
        avg_dd = float(row[5]) if row[5] is not None else None
        strong_rate = float(row[6]) if row[6] is not None else None
        failed_rate = float(row[7]) if row[7] is not None else None
        status, reason = _status_for(sample_count, win_rate, avg_return, failed_rate, avg_dd)
        score = _score_for(win_rate, avg_return, strong_rate, failed_rate, avg_dd)

        item = {
            "trade_date": sql_as_of,
            "strategy": strategy,
            "window_days": int(window_days),
            "sample_count": sample_count,
            "win_rate_1d": win_rate,
            "avg_next_1d_return": avg_return,
            "avg_max_3d_return": avg_max,
            "avg_max_3d_drawdown": avg_dd,
            "strong_rate": strong_rate,
            "failed_rate": failed_rate,
            "feedback_score": score,
            "status": status,
            "reason": reason,
        }
        stats.append(item)

    if save_db:
        for item in stats:
            cur.execute(
                """
                INSERT INTO strategy_feedback_stats (
                    trade_date, strategy, window_days, sample_count,
                    win_rate_1d, avg_next_1d_return, avg_max_3d_return,
                    avg_max_3d_drawdown, strong_rate, failed_rate,
                    feedback_score, status, reason, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, NOW()
                )
                ON CONFLICT (trade_date, strategy, window_days)
                DO UPDATE SET
                    sample_count = EXCLUDED.sample_count,
                    win_rate_1d = EXCLUDED.win_rate_1d,
                    avg_next_1d_return = EXCLUDED.avg_next_1d_return,
                    avg_max_3d_return = EXCLUDED.avg_max_3d_return,
                    avg_max_3d_drawdown = EXCLUDED.avg_max_3d_drawdown,
                    strong_rate = EXCLUDED.strong_rate,
                    failed_rate = EXCLUDED.failed_rate,
                    feedback_score = EXCLUDED.feedback_score,
                    status = EXCLUDED.status,
                    reason = EXCLUDED.reason,
                    updated_at = NOW()
                """,
                (
                    item["trade_date"], item["strategy"], item["window_days"],
                    item["sample_count"], item["win_rate_1d"],
                    item["avg_next_1d_return"], item["avg_max_3d_return"],
                    item["avg_max_3d_drawdown"], item["strong_rate"],
                    item["failed_rate"], item["feedback_score"],
                    item["status"], item["reason"],
                ),
            )
        conn.commit()

    cur.close()
    conn.close()
    return stats


def load_latest_strategy_feedback(window_days=DEFAULT_WINDOW_DAYS):
    if not DATABASE_DSN:
        return {}
    try:
        conn = psycopg2.connect(DATABASE_DSN)
        cur = conn.cursor()
        ensure_table(cur)
        cur.execute(
            """
            SELECT strategy, sample_count, win_rate_1d, avg_next_1d_return,
                   failed_rate, feedback_score, status, reason, trade_date
            FROM strategy_feedback_stats
            WHERE window_days = %s
              AND trade_date = (
                  SELECT MAX(trade_date)
                  FROM strategy_feedback_stats
                  WHERE window_days = %s
              )
            """,
            (int(window_days), int(window_days)),
        )
        data = {}
        for row in cur.fetchall():
            data[row[0]] = {
                "sample_count": row[1],
                "win_rate_1d": float(row[2]) if row[2] is not None else None,
                "avg_next_1d_return": float(row[3]) if row[3] is not None else None,
                "failed_rate": float(row[4]) if row[4] is not None else None,
                "feedback_score": float(row[5]) if row[5] is not None else None,
                "status": row[6],
                "reason": row[7],
                "trade_date": row[8].strftime("%Y%m%d") if hasattr(row[8], "strftime") else str(row[8]),
            }
        cur.close()
        conn.close()
        return data
    except Exception:
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None, help="as-of date YYYYMMDD")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    stats = compute_strategy_feedback(
        as_of_date=args.date,
        window_days=args.window,
        save_db=not args.no_save,
    )
    print(f"strategy feedback rows: {len(stats)}")
    print("| strategy | sample | win_rate | avg_1d | failed | score | status | reason |")
    print("|----------|--------|----------|--------|--------|-------|--------|--------|")
    for item in sorted(stats, key=lambda x: x["feedback_score"], reverse=True):
        win = "-" if item["win_rate_1d"] is None else f"{item['win_rate_1d']:.1%}"
        avg = "-" if item["avg_next_1d_return"] is None else f"{item['avg_next_1d_return']:.2%}"
        failed = "-" if item["failed_rate"] is None else f"{item['failed_rate']:.1%}"
        print(
            f"| {item['strategy']} | {item['sample_count']} | {win} | {avg} | "
            f"{failed} | {item['feedback_score']} | {item['status']} | {item['reason']} |"
        )


if __name__ == "__main__":
    main()
