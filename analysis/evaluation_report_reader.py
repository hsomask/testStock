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
    row = _try_db(as_of_date)
    if not row:
        row = _try_file(as_of_date)

    if not row:
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
