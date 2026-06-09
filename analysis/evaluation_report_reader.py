"""
只读 evaluation 结果，供日报展示 T+1 复盘。
不计算、不写库、不调行情 API、不 import watchlist_evaluation。
"""
import json
import logging
from pathlib import Path

from data.config import DATABASE_DSN, REPORT_DIR

logger = logging.getLogger(__name__)

EVAL_DIR = REPORT_DIR / "evaluation"


def _infer_signal_date(as_of_date):
    """从 stock_signal 推断上一个交易日"""
    if not DATABASE_DSN:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_DSN)
        cur = conn.cursor()
        sql_date = f"{as_of_date[:4]}-{as_of_date[4:6]}-{as_of_date[6:8]}"
        cur.execute("SELECT MAX(trade_date) FROM stock_signal WHERE trade_date < %s", (sql_date,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            td = row[0]
            return td.strftime("%Y%m%d") if hasattr(td, "strftime") else str(td).replace("-", "")[:8]
    except Exception:
        pass
    return None


def _try_db(as_of_date):
    """从 watchlist_evaluation_summary 读取最新 daily evaluation"""
    if not DATABASE_DSN:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_DSN)
        cur = conn.cursor()
        cur.execute(
            "SELECT signal_date, as_of_date, total_signals, evaluated_1d, coverage_1d, "
            "evaluated_3d, coverage_3d, avg_next_1d_return, win_rate_1d, "
            "confidence_level, conclusion_level, layer_inversion_warning, risk_warning, "
            "diagnostics_json, summary_json "
            "FROM watchlist_evaluation_summary "
            "WHERE eval_mode = 'daily' AND as_of_date = %s "
            "ORDER BY generated_at DESC LIMIT 1",
            (as_of_date,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return dict(zip([
                "signal_date", "as_of_date", "total_signals", "evaluated_1d",
                "coverage_1d", "evaluated_3d", "coverage_3d",
                "avg_next_1d_return", "win_rate_1d",
                "confidence_level", "conclusion_level",
                "layer_inversion_warning", "risk_warning",
                "diagnostics_json", "summary_json",
            ], row))
    except Exception:
        pass
    return None


def _try_file(as_of_date):
    """降级：读取 evaluation JSON 文件"""
    candidates = sorted(EVAL_DIR.glob(f"daily_watchlist_evaluation_*_{as_of_date}.json"), reverse=True)
    if not candidates:
        # 尝试不带 daily_ 前缀的文件
        candidates = sorted(EVAL_DIR.glob(f"watchlist_evaluation_*_{as_of_date}.json"), reverse=True)
    if not candidates:
        return None
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
        s = data.get("summary", {})
        o = data.get("overall", {}).get("__all__", {})
        d = data.get("diagnostics", {})
        return {
            "signal_date": data.get("signal_date", ""),
            "as_of_date": data.get("as_of_date", as_of_date),
            "total_signals": s.get("total_signals", 0),
            "evaluated_1d": s.get("evaluated_1d", 0),
            "coverage_1d": s.get("coverage_1d", 0),
            "evaluated_3d": s.get("evaluated_3d", 0),
            "coverage_3d": s.get("coverage_3d", 0),
            "avg_next_1d_return": o.get("avg_next_1d_return"),
            "win_rate_1d": o.get("win_rate_1d"),
            "confidence_level": d.get("confidence_level", ""),
            "conclusion_level": d.get("conclusion_level", ""),
            "layer_inversion_warning": d.get("layer_diagnostics", {}).get("layer_inversion_warning", False),
            "risk_warning": d.get("risk_diagnostics", {}).get("risk_warning", False),
            "diagnostics_json": json.dumps(d, ensure_ascii=False),
            "summary_json": json.dumps(s, ensure_ascii=False),
        }
    except Exception:
        return None


def _try_top_bottom(as_of_date, signal_date):
    """读取 Top 3 / Bottom 3 表现明细"""
    if not DATABASE_DSN:
        return [], []
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_DSN)
        cur = conn.cursor()
        # Top 3 by 1d return
        cur.execute(
            "SELECT name, watchlist_layer, next_1d_return "
            "FROM watchlist_evaluation_result "
            "WHERE eval_mode = 'daily' AND as_of_date = %s "
            "AND next_1d_return IS NOT NULL "
            "ORDER BY next_1d_return DESC LIMIT 3",
            (as_of_date,),
        )
        top = [{"name": r[0], "layer": r[1], "ret": r[2]} for r in cur.fetchall()]
        # Bottom 3
        cur.execute(
            "SELECT name, watchlist_layer, next_1d_return "
            "FROM watchlist_evaluation_result "
            "WHERE eval_mode = 'daily' AND as_of_date = %s "
            "AND next_1d_return IS NOT NULL "
            "ORDER BY next_1d_return ASC LIMIT 3",
            (as_of_date,),
        )
        bottom = [{"name": r[0], "layer": r[1], "ret": r[2]} for r in cur.fetchall()]
        cur.close()
        conn.close()
        return top, bottom
    except Exception:
        return [], []


def load_t1_evaluation_summary(as_of_date):
    """
    读取 T+1 evaluation 摘要。
    返回 {"available": bool, ...} 或 {"available": False, "status": "missing/defer/error"}
    """
    # 1. DB summary
    row = _try_db(as_of_date)
    # 2. evaluation result JSON
    if not row:
        row = _try_file(as_of_date)
    # 3. status file (defer 时写入) → 尝试快照降级
    kline_insufficient = False
    status_signal_date = None
    if not row:
        status_path = EVAL_DIR / f"evaluation_status_{as_of_date}.json"
        if status_path.exists():
            try:
                sf = json.loads(status_path.read_text(encoding="utf-8"))
                status_signal_date = sf.get("signal_date", "")
                kline_cov = sf.get("price_cache_coverage", 0)
                # K 线不足时，尝试快照复盘
                if kline_cov < 0.8 and status_signal_date:
                    kline_insufficient = True
                else:
                    # K 线足够但不是 coverage issue，直接返回 defer
                    return {
                        "available": False,
                        "status": sf.get("status", "defer"),
                        "message": sf.get("message", "今日 T+1 复盘暂缓。"),
                        "signal_date": status_signal_date,
                        "as_of_date": sf.get("as_of_date", as_of_date),
                        "total_signals": sf.get("total_signals", 0),
                        "evaluated_1d": 0, "coverage_1d": kline_cov,
                        "avg_return_1d": None, "win_rate_1d": None,
                        "inversion": False, "risk_warning": False,
                        "confidence_level": "", "conclusion_level": "",
                        "top_winners": [], "top_losers": [], "messages": [],
                    }
            except Exception:
                pass

    # 4. 快照复盘降级（正式复盘不存在 + K 线覆盖不足）
    if not row:
        signal_date_guess = status_signal_date or _infer_signal_date(as_of_date)
        if signal_date_guess:
            from analysis.evaluation_snapshot_recap import build_snapshot_t1_recap
            snap = build_snapshot_t1_recap(signal_date_guess, as_of_date)
            if snap:
                return snap
        # 快照也不足，返回 defer（复用 status 信息）
        if kline_insufficient:
            return {
                "available": False, "status": "defer",
                "message": "今日 T+1 复盘因 K 线和快照覆盖均不足暂缓。",
                "signal_date": signal_date_guess or "",
                "as_of_date": as_of_date,
                "total_signals": 0, "evaluated_1d": 0, "coverage_1d": 0,
                "avg_return_1d": None, "win_rate_1d": None,
                "inversion": False, "risk_warning": False,
                "confidence_level": "", "conclusion_level": "",
                "top_winners": [], "top_losers": [], "messages": [],
            }
        return {"available": False, "status": "missing", "message": "今日 T+1 复盘尚未生成。"}

    signal_date = row.get("signal_date", "")
    top, bottom = _try_top_bottom(as_of_date, signal_date)

    # Parse diagnostics
    diag = {}
    if row.get("diagnostics_json"):
        try:
            diag = json.loads(row["diagnostics_json"]) if isinstance(row["diagnostics_json"], str) else row["diagnostics_json"]
        except Exception:
            pass

    evaluated_1d = row.get("evaluated_1d") or 0
    cov1d = row.get("coverage_1d") or 0
    confidence_level = str(row.get("confidence_level", ""))
    conclusion_level = str(row.get("conclusion_level", ""))

    # 只有明确标记 defer 时才是 defer
    is_defer = (
        "defer" in confidence_level.lower()
        or "defer" in conclusion_level.lower()
    )

    if is_defer:
        status = "defer"
        msg = "今日 T+1 复盘因行情缓存不足暂缓。"
    elif evaluated_1d == 0:
        status = "insufficient"
        msg = "今日 T+1 复盘覆盖不足，暂不下结论。"
    elif cov1d < 0.8:
        status = "partial"
        msg = "今日 T+1 覆盖率偏低，结果仅供观察。"
    else:
        status = "ok"
        msg = None

    return {
        "available": True,
        "status": status,
        "message": msg,
        "signal_date": signal_date,
        "as_of_date": row.get("as_of_date", as_of_date),
        "total_signals": row.get("total_signals", 0),
        "evaluated_1d": row.get("evaluated_1d", 0),
        "coverage_1d": row.get("coverage_1d", 0),
        "avg_return_1d": row.get("avg_next_1d_return"),
        "win_rate_1d": row.get("win_rate_1d"),
        "inversion": row.get("layer_inversion_warning", False),
        "risk_warning": row.get("risk_warning", False),
        "confidence_level": row.get("confidence_level", ""),
        "conclusion_level": row.get("conclusion_level", ""),
        "top_winners": top,
        "top_losers": bottom,
        "messages": diag.get("diagnostic_messages", []),
    }
