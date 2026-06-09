"""
快照复盘：在正式 K 线覆盖不足时，使用当日行情快照生成降级 T+1 复盘。
数据源：fetch_stock_spot 东方财富全市场快照（与 K 线源分离）。
不写库、不改变 selector/trade_plan/evaluation 计算逻辑。
"""
import json
import logging
from pathlib import Path

from datetime import datetime

from data.config import DATABASE_DSN, REPORT_DIR
from analysis.data_fetcher import is_trade_day

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


def _volume_note(volume_ratio):
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
    使用当日行情快照（东方财富全市场）生成降级 T+1 复盘。
    数据源与 K 线分离：official 用 stock_hist_kline，snapshot 用 fetch_stock_spot。
    返回 dict 或 None（快照也不足时）。
    """
    try:
        import psycopg2

        # 1. 读取昨日观察池
        conn = psycopg2.connect(DATABASE_DSN) if DATABASE_DSN else None
        if not conn:
            return None
        cur = conn.cursor()
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
        cur.close()
        conn.close()

        total_signals = len(signal_stocks)
        if total_signals == 0:
            return None

        # 2. 读取当日全市场行情快照（东方财富，与 K 线源分离）
        # 保护：只允许 as_of_date 为当天交易日，避免历史重渲染错用今天行情
        today = datetime.now().strftime("%Y%m%d")
        if as_of_date != today and not is_trade_day(as_of_date):
            return None
        if as_of_date != today:
            # 非当天：检查是否有本地缓存，没有则降级
            cache_path = REPORT_DIR / "cache" / f"stock_spot_{as_of_date}.json"
            if not cache_path.exists():
                return None
            import pandas as pd
            spot_df = pd.read_json(cache_path, orient="records")
        else:
            from analysis.data_fetcher import fetch_stock_spot
            spot_df = fetch_stock_spot()
        if spot_df is None or spot_df.empty:
            return None

        # 构建 code → 快照数据的映射
        spot_map = {}
        for _, row in spot_df.iterrows():
            code = str(row.get("code", "")).strip()
            spot_map[code] = {
                "close": float(row["close"]) if row.get("close") else None,
                "pct_chg": float(row["pct_chg"]) if row.get("pct_chg") else None,
                "volume_ratio": float(row["volume_ratio"]) if row.get("volume_ratio") and not _is_nan(row.get("volume_ratio")) else None,
                "turnover": float(row["turnover"]) if row.get("turnover") and not _is_nan(row.get("turnover")) else None,
                "amount": float(row["amount"]) if row.get("amount") else None,
            }

        # 3. 匹配：昨日观察池 vs 今日快照
        evaluated = []
        for code, sig in signal_stocks.items():
            spot = spot_map.get(code, {})
            pct_chg = spot.get("pct_chg")
            vr = spot.get("volume_ratio")

            evaluated.append({
                "code": code,
                "name": sig["name"],
                "layer": sig["risk_level"],
                "strategy": sig["strategy"],
                "entry_close": sig.get("entry_close"),
                "asof_close": spot.get("close"),
                "pct_chg": round(pct_chg, 2) if pct_chg is not None else None,
                "volume_ratio": round(vr, 1) if vr is not None else None,
                "tag": _result_tag(pct_chg),
                "volume_note": _volume_note(vr),
            })

        snapshot_covered = sum(1 for e in evaluated if e["pct_chg"] is not None)
        snapshot_coverage = snapshot_covered / total_signals if total_signals > 0 else 0

        if snapshot_coverage < 0.8:
            return None

        # 4. 排序 Top 5 / Bottom 5
        evaluated.sort(key=lambda e: e["pct_chg"] if e["pct_chg"] is not None else -999, reverse=True)
        top5 = [e for e in evaluated if e["pct_chg"] is not None][:5]
        bottom5 = [e for e in evaluated if e["pct_chg"] is not None][-5:][::-1]

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


def _is_nan(val):
    try:
        import numpy as np
        return np.isnan(float(val))
    except Exception:
        return False
