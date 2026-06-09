"""
快照复盘：在正式 K 线覆盖不足时，使用当日行情快照生成降级 T+1 复盘。
不写库、不改变 selector/trade_plan/evaluation 计算逻辑。
"""
import json
import logging
from pathlib import Path

from data.config import DATABASE_DSN, REPORT_DIR

logger = logging.getLogger(__name__)

EVAL_DIR = REPORT_DIR / "evaluation"


def _load_kline_status(as_of_date):
    """读取 evaluation_status 文件中的 K 线覆盖率"""
    status_path = EVAL_DIR / f"evaluation_status_{as_of_date}.json"
    if not status_path.exists():
        return None
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _result_tag(pct_chg):
    """根据涨跌幅返回结果标签"""
    if pct_chg is None:
        return "数据不足"
    if pct_chg >= 10:
        return "大涨"
    elif pct_chg >= 5:
        return "走强"
    elif pct_chg >= 2:
        return "小涨"
    elif pct_chg > -2:
        return "震荡"
    elif pct_chg > -5:
        return "走弱"
    else:
        return "大跌"


def _volume_short_note(pct_chg, volume):
    """快照复盘量价简评"""
    if volume is None:
        return "数据不足"
    up = (pct_chg or 0) > 0
    if up and volume > 1e8:
        return "放量上涨"
    elif up:
        return "上涨"
    elif not up and pct_chg is not None and volume > 1e8:
        return "放量下跌"
    elif pct_chg is not None:
        return "下跌"
    return "数据不足"


def _volume_note(volume_ratio):
    """根据量比返回量价表现"""
    if volume_ratio is None:
        return "量价数据不足"
    try:
        vr = float(volume_ratio)
    except (TypeError, ValueError):
        return "量价数据不足"
    if vr >= 3:
        return f"{vr:.1f}x放量过强"
    elif vr >= 1.3:
        return f"{vr:.1f}x健康放量"
    elif vr >= 0.8:
        return f"{vr:.1f}x正常"
    else:
        return f"{vr:.1f}x缩量"


def build_snapshot_t1_recap(signal_date, as_of_date):
    """
    使用当日行情快照生成降级 T+1 复盘。
    数据来源：stock_signal（昨日观察池）+ 当日行情快照。

    返回 dict 或 None（快照也不足时）。
    """
    if not DATABASE_DSN:
        return None

    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_DSN)
        cur = conn.cursor()

        # 1. 读取昨日观察池
        sql_signal = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}"
        cur.execute(
            "SELECT DISTINCT code, name, close_price, risk_level, action_signal, strategy "
            "FROM stock_signal WHERE trade_date = %s",
            (sql_signal,),
        )
        signal_stocks = {}
        for row in cur.fetchall():
            code = row[0]
            signal_stocks[code] = {
                "code": code, "name": row[1], "entry_close": float(row[2]) if row[2] else None,
                "risk_level": row[3] or "", "action_signal": row[4] or "", "strategy": row[5] or "",
            }

        total_signals = len(signal_stocks)
        if total_signals == 0:
            cur.close()
            conn.close()
            return None

        # 2. 读取 as_of_date 行情快照（从 stock_hist_kline）
        sql_asof = f"{as_of_date[:4]}-{as_of_date[4:6]}-{as_of_date[6:8]}"
        codes_list = list(signal_stocks.keys())
        placeholders = ",".join(["%s"] * len(codes_list))
        cur.execute(
            f"SELECT code, close, volume FROM stock_hist_kline "
            f"WHERE code IN ({placeholders}) AND trade_date = %s",
            (*codes_list, sql_asof),
        )
        asof_data = {}
        for row in cur.fetchall():
            code = row[0]
            asof_data[code] = {
                "close": float(row[1]) if row[1] else None,
                "volume": float(row[2]) if row[2] else None,
            }

        cur.close()
        conn.close()

        # 3. 匹配结果
        evaluated = []
        for code, sig in signal_stocks.items():
            ad = asof_data.get(code, {})
            entry_close = sig.get("entry_close")
            asof_close = ad.get("close")
            vr = ad.get("volume")

            pct_chg = None
            if entry_close and asof_close and entry_close > 0:
                pct_chg = (asof_close / entry_close - 1) * 100

            evaluated.append({
                "code": code,
                "name": sig["name"],
                "layer": sig["risk_level"],
                "strategy": sig["strategy"],
                "entry_close": entry_close,
                "asof_close": asof_close,
                "pct_chg": round(pct_chg, 2) if pct_chg is not None else None,
                "volume": round(vr, 0) if vr is not None else None,
                "tag": _result_tag(pct_chg),
                "volume_note": _volume_short_note(vr, ad.get("volume")),
            })

        snapshot_covered = sum(1 for e in evaluated if e["pct_chg"] is not None)
        snapshot_coverage = snapshot_covered / total_signals if total_signals > 0 else 0

        if snapshot_coverage < 0.8:
            return None

        # 4. 排序，取 Top 5 / Bottom 5
        evaluated.sort(key=lambda e: e["pct_chg"] if e["pct_chg"] is not None else -999, reverse=True)
        top5 = [e for e in evaluated if e["pct_chg"] is not None][:5]
        bottom5 = [e for e in evaluated if e["pct_chg"] is not None][-5:][::-1]

        # K 线覆盖率
        kline_status = _load_kline_status(as_of_date)
        kline_cov = kline_status.get("price_cache_coverage") if kline_status else None

        return {
            "available": True,
            "status": "snapshot",
            "recap_mode": "snapshot",
            "message": "K线覆盖不足，使用当日行情快照生成降级复盘，仅供观察。",
            "signal_date": signal_date,
            "as_of_date": as_of_date,
            "total_signals": total_signals,
            "snapshot_covered": snapshot_covered,
            "snapshot_coverage": snapshot_coverage,
            "kline_coverage": kline_cov,
            "top_winners": top5,
            "top_losers": bottom5,
        }

    except Exception:
        return None
