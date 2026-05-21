"""
信号追踪模块
读取历史 stock_signal，计算后续表现并写入 signal_performance 表
运行：python -m analysis.signal_tracker
"""
import psycopg2
import pandas as pd
import numpy as np
import logging
from datetime import datetime, date, timedelta

from data.config import DATABASE_DSN

logger = logging.getLogger(__name__)


def _get_db_conn():
    if not DATABASE_DSN:
        return None
    try:
        return psycopg2.connect(DATABASE_DSN)
    except Exception as e:
        print(f"[错误] 数据库连接失败：{e}")
        return None


def _fetch_hist_for_codes(codes, days=80):
    """批量获取历史K线"""
    from analysis.data_fetcher import get_stock_history
    result = {}
    for code in codes:
        hist = get_stock_history(code, days=days)
        if not hist.empty and "close" in hist.columns:
            result[code] = hist
    return result


def track_signals(lookback_days=10):
    """追踪过去 N 个交易日的信号表现"""
    conn = _get_db_conn()
    if conn is None:
        return

    cur = conn.cursor()

    # 确保表存在
    cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='signal_performance')")
    if not cur.fetchone()[0]:
        print("[错误] signal_performance 表不存在，请先运行 init_db")
        cur.close()
        conn.close()
        return

    # 读取过去 N 天的信号（trade_date 为 YYYYMMDD 格式 VARCHAR）
    start_date = (datetime.now() - timedelta(days=lookback_days + 5)).strftime("%Y%m%d")
    cur.execute(
        "SELECT DISTINCT trade_date, code, name, strategy, close_price, risk_level, action_signal "
        "FROM stock_signal WHERE trade_date >= %s ORDER BY trade_date",
        (start_date,)
    )
    signals = cur.fetchall()

    if not signals:
        print("没有需要追踪的信号")
        cur.close()
        conn.close()
        return

    # 按代码分组去重
    unique_codes = list(set(s[1] for s in signals))
    print(f"追踪 {len(signals)} 条信号，{len(unique_codes)} 只股票")

    # 批量取历史K线
    hist_map = _fetch_hist_for_codes(unique_codes)

    updated = 0
    skipped = 0

    for trade_date, code, name, strategy, signal_close, risk_level, action_signal in signals:
        signal_close = float(signal_close) if signal_close else 0
        hist = hist_map.get(code)
        if hist is None or hist.empty:
            skipped += 1
            continue

        # trade_date 统一为 YYYYMMDD（兼容 date / datetime / str）
        if isinstance(trade_date, (datetime, date)):
            td_str = trade_date.strftime("%Y%m%d")
        else:
            raw = str(trade_date).strip()
            td_str = raw.replace("-", "")[:8]
        td_dash = f"{td_str[:4]}-{td_str[4:6]}-{td_str[6:8]}"

        hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
        hist = hist.dropna(subset=["date"])
        if hist.empty:
            skipped += 1
            continue
        future = hist[hist["date"] > pd.Timestamp(td_dash)].copy()

        if len(future) < 1:
            skipped += 1
            continue

        close = pd.to_numeric(future["close"], errors="coerce").dropna()
        high = pd.to_numeric(future["high"], errors="coerce").dropna()
        low = pd.to_numeric(future["low"], errors="coerce").dropna()

        if len(close) < 1:
            skipped += 1
            continue

        next_td = future["date"].iloc[0]

        def _ret(n):
            if len(close) >= n and signal_close:
                return round(float((close.iloc[n - 1] / signal_close - 1) * 100), 2)
            return None

        close_t1 = round(float(close.iloc[0]), 2) if len(close) >= 1 else None
        close_t3 = round(float(close.iloc[2]), 2) if len(close) >= 3 else None
        close_t5 = round(float(close.iloc[4]), 2) if len(close) >= 5 else None

        return_t1 = _ret(1)
        return_t3 = _ret(3)
        return_t5 = _ret(5)

        # 5日内最高/最低/最大回撤
        max_high_5d = round(float(high.head(5).max()), 2) if len(high) >= 1 else None
        max_return_5d = round(float((max_high_5d / signal_close - 1) * 100), 2) if max_high_5d and signal_close else None
        min_low_5d = round(float(low.head(5).min()), 2) if len(low) >= 1 else None
        max_drawdown_5d = round(float((min_low_5d / signal_close - 1) * 100), 2) if min_low_5d and signal_close else None

        # 是否触及压力位/失效位
        hit_pressure = False
        hit_invalid = False

        cur.execute(
            "SELECT pressure_price, invalid_price FROM stock_signal WHERE trade_date=%s AND code=%s AND strategy=%s",
            (td_str, code, strategy)
        )
        row = cur.fetchone()
        if row:
            pp, ip = row
            if pp and max_high_5d and max_high_5d >= float(pp):
                hit_pressure = True
            if ip and min_low_5d and min_low_5d <= float(ip):
                hit_invalid = True

        try:
            cur.execute("""
                INSERT INTO signal_performance (
                    trade_date, code, name, strategy,
                    signal_close, next_trade_date,
                    close_t1, close_t3, close_t5,
                    return_t1, return_t3, return_t5,
                    max_high_5d, max_return_5d, min_low_5d, max_drawdown_5d,
                    risk_level, action_signal,
                    hit_pressure, hit_invalid
                ) VALUES (%s,%s,%s,%s, %s,%s, %s,%s,%s, %s,%s,%s, %s,%s,%s,%s, %s,%s, %s,%s)
                ON CONFLICT (trade_date, code, strategy) DO UPDATE SET
                    close_t1=EXCLUDED.close_t1, close_t3=EXCLUDED.close_t3, close_t5=EXCLUDED.close_t5,
                    return_t1=EXCLUDED.return_t1, return_t3=EXCLUDED.return_t3, return_t5=EXCLUDED.return_t5,
                    max_high_5d=EXCLUDED.max_high_5d, max_return_5d=EXCLUDED.max_return_5d,
                    min_low_5d=EXCLUDED.min_low_5d, max_drawdown_5d=EXCLUDED.max_drawdown_5d,
                    risk_level=EXCLUDED.risk_level, action_signal=EXCLUDED.action_signal,
                    hit_pressure=EXCLUDED.hit_pressure, hit_invalid=EXCLUDED.hit_invalid
            """, (
                td_str, code, name, strategy, signal_close, next_td,
                close_t1, close_t3, close_t5,
                return_t1, return_t3, return_t5,
                max_high_5d, max_return_5d, min_low_5d, max_drawdown_5d,
                risk_level, action_signal,
                hit_pressure, hit_invalid
            ))
            updated += 1
        except Exception as e:
            print(f"[错误] 写入 signal_performance 失败：{code} {e}")

    conn.commit()
    cur.close()
    conn.close()

    print(f"信号追踪完成：更新 {updated} 条，跳过 {skipped} 条")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    track_signals()


if __name__ == "__main__":
    main()
