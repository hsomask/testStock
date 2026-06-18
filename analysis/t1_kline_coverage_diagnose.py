"""
Diagnose T+1 K-line coverage for a signal/as-of date pair.

Usage:
  python -m analysis.t1_kline_coverage_diagnose --as-of-date 20260616
  python -m analysis.t1_kline_coverage_diagnose --signal-date 20260615 --as-of-date 20260616
"""
import argparse

import psycopg2

from data.config import DATABASE_DSN


def _sql_date(date_str):
    text = str(date_str or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid date: {date_str}")
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _infer_signal_date(cur, as_of_date):
    cur.execute(
        "SELECT MAX(trade_date) FROM stock_signal WHERE trade_date < %s",
        (_sql_date(as_of_date),),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return None
    return row[0].strftime("%Y%m%d")


def diagnose(signal_date=None, as_of_date=None, limit=30):
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN 未配置")
    if not as_of_date:
        raise ValueError("--as-of-date is required")

    conn = psycopg2.connect(DATABASE_DSN)
    cur = conn.cursor()

    if not signal_date:
        signal_date = _infer_signal_date(cur, as_of_date)
    if not signal_date:
        raise RuntimeError("无法推断 signal_date")

    sql_signal = _sql_date(signal_date)
    sql_asof = _sql_date(as_of_date)

    cur.execute(
        """
        SELECT DISTINCT code, name, strategy, risk_level
        FROM stock_signal
        WHERE trade_date = %s
        ORDER BY code
        """,
        (sql_signal,),
    )
    signals = cur.fetchall()
    codes = [row[0] for row in signals]

    if not codes:
        print(f"signal_date={signal_date}, as_of_date={as_of_date}, signals=0")
        cur.close()
        conn.close()
        return

    cur.execute(
        """
        SELECT
            code,
            BOOL_OR(trade_date = %s) AS has_signal_date,
            BOOL_OR(trade_date = %s) AS has_asof_date,
            MAX(trade_date) AS max_trade_date,
            COUNT(*) AS cached_rows
        FROM stock_hist_kline
        WHERE code = ANY(%s)
        GROUP BY code
        """,
        (sql_signal, sql_asof, codes),
    )
    cache = {
        row[0]: {
            "has_signal_date": bool(row[1]),
            "has_asof_date": bool(row[2]),
            "max_trade_date": row[3],
            "cached_rows": row[4],
        }
        for row in cur.fetchall()
    }

    details = []
    covered = 0
    for code, name, strategy, risk_level in signals:
        item = cache.get(code, {})
        has_signal = item.get("has_signal_date", False)
        has_asof = item.get("has_asof_date", False)
        ok = has_signal and has_asof
        covered += 1 if ok else 0
        reason = []
        if not has_signal:
            reason.append("缺signal日K线")
        if not has_asof:
            reason.append("缺as_of日K线")
        details.append({
            "code": code,
            "name": name,
            "strategy": strategy,
            "risk_level": risk_level,
            "ok": ok,
            "reason": "、".join(reason) if reason else "OK",
            "max_trade_date": item.get("max_trade_date"),
            "cached_rows": item.get("cached_rows", 0),
        })

    total = len(signals)
    coverage = covered / total if total else 0
    print(f"signal_date={signal_date}, as_of_date={as_of_date}")
    print(f"signals={total}, covered={covered}, coverage={coverage:.1%}")
    print("")
    print("| code | name | strategy | risk | reason | max_trade_date | cached_rows |")
    print("|------|------|----------|------|--------|----------------|-------------|")
    for item in [d for d in details if not d["ok"]][:limit]:
        print(
            f"| {item['code']} | {item['name']} | {item['strategy']} | {item['risk_level']} | "
            f"{item['reason']} | {item['max_trade_date']} | {item['cached_rows']} |"
        )

    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-date", type=str, default=None)
    parser.add_argument("--as-of-date", type=str, required=True)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    diagnose(args.signal_date, args.as_of_date, args.limit)


if __name__ == "__main__":
    main()
