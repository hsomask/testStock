"""
A 股每日分析报告主入口
运行：
  python -m analysis.daily_report
  python -m analysis.daily_report --mode beginner
  python -m analysis.daily_report --mode pro
  python -m analysis.daily_report --mode both
  python -m analysis.daily_report --force
"""
import argparse
import json
import logging
import time
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

from analysis.data_fetcher import (
    get_trade_date,
    is_trade_day,
    fetch_stock_spot,
    fetch_index_spot,
    fetch_industry_boards,
    fetch_concept_boards,
    enrich_stock_indicators,
    enrich_selected_stocks_indicators,
)
from analysis.account_filter import filter_tradeable_stocks
from analysis.trade_plan import generate_trade_plan, save_trade_plan
from analysis.data_sources.ths_hot import ths_hot_reasons_by_stock


def load_board_trend_summary(trade_date):
    path = REPORTS_DIR / f"board_trend_summary_{trade_date}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
from analysis.market import analyze_market
from analysis.board import analyze_boards
from analysis.sentiment import analyze_sentiment
from analysis.selector import run_all_selectors
from analysis.report_renderer import render_daily_report, save_report
from analysis.data_quality import check_data_quality
from analysis.theme_detector import detect_main_themes
from data.config import DATABASE_DSN

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily"


def get_board_ratio_changes():
    try:
        from analysis.board_history import get_all_ratio_changes
        changes = get_all_ratio_changes()
        has_data = any(
            v is not None and not (hasattr(v, 'empty') and v.empty)
            for v in changes.values()
        )
        return changes if has_data else None
    except Exception as e:
        logger.exception(f"板块历史读取失败：{e}")
        return None


def build_summary_json(trade_date, market_result, sentiment_result, themes,
                        quality, selector_result):
    """构建结构化摘要 JSON"""
    watchlists = {}
    for pool_name, pool_df in selector_result.items():
        if pool_df is None or pool_df.empty:
            watchlists[pool_name] = []
            continue
        stocks = []
        for _, row in pool_df.head(3).iterrows():
            stocks.append({
                "code": str(row.get("code", "")),
                "name": str(row.get("name", "")),
                "close": float(row.get("close", 0)) if row.get("close") is not None else None,
                "pct_chg": float(row.get("pct_chg", 0)) if row.get("pct_chg") is not None else None,
                "risk_level": str(row.get("risk_level", "")),
                "action_signal": str(row.get("action_signal", "")),
            })
        watchlists[pool_name] = stocks

    risk_directions = []
    if market_result.get("limit_down", 0) > 0:
        risk_directions.append(f"跌停{market_result['limit_down']}只")

    summary = {
        "trade_date": trade_date,
        "generated_at": datetime.now().isoformat(),
        "market": {
            "score": market_result.get("score"),
            "status": market_result.get("status"),
            "total_amount": market_result.get("total_amount"),
            "up_count": market_result.get("up_count"),
            "down_count": market_result.get("down_count"),
            "limit_up": market_result.get("limit_up"),
            "limit_down": market_result.get("limit_down"),
            "summary": market_result.get("summary", ""),
        },
        "sentiment": {
            "score": sentiment_result.get("score"),
            "stage": sentiment_result.get("stage"),
        },
        "themes": [{
            "name": t.get("name"),
            "level": t.get("level"),
            "score": t.get("score"),
            "reasons": t.get("reasons", []),
            "beginner_explain": t.get("beginner_explain", ""),
            "sustainability_risk": t.get("sustainability_risk", ""),
        } for t in (themes or [])],
        "quality": {
            "confidence_score": quality.get("confidence_score"),
            "issues": quality.get("issues", []),
        },
        "watchlists": watchlists,
        "risk_directions": risk_directions,
    }
    return summary


def save_summary_json(summary, trade_date):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"daily_summary_{trade_date}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"摘要已保存：{path}")


def _get_db_conn():
    """获取独立数据库连接"""
    if not DATABASE_DSN:
        return None
    try:
        return psycopg2.connect(DATABASE_DSN)
    except Exception as e:
        logger.exception(f"数据库连接失败：{e}")
        return None


def _num_or_none(x):
    """NaN 安全转 float，NaN 返回 None"""
    try:
        if pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None


def save_stock_signals(selector_result, trade_date, db_conn=None):
    """写入观察池股票信号到 stock_signal 表"""
    conn = db_conn if db_conn and not db_conn.closed else _get_db_conn()
    if conn is None:
        print("[错误] stock_signal 写入跳过：数据库不可用")
        return

    total_candidates = sum(
        len(df) for df in selector_result.values()
        if df is not None and not df.empty
    )
    print(f"准备写入 stock_signal：{total_candidates} 条候选")

    cur = conn.cursor()
    written = 0
    failed = 0

    for pool_name, pool_df in selector_result.items():
        if pool_df is None or pool_df.empty:
            continue
        for _, row in pool_df.iterrows():
            code = str(row.get("code", ""))
            name = str(row.get("name", ""))
            try:
                cur.execute("""
                    INSERT INTO stock_signal (
                        trade_date, code, name, strategy, signal_type,
                        hot_board_hits,
                        close_price, pct_chg, volume_ratio, turnover,
                        ma5, ma10, ma20, pct_5d, pct_20d,
                        observe_low, observe_high, pressure_price, invalid_price,
                        risk_level, action_signal, entry_reasons, risk_reasons
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    ON CONFLICT (trade_date, code, strategy)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        signal_type = EXCLUDED.signal_type,
                        hot_board_hits = EXCLUDED.hot_board_hits,
                        close_price = EXCLUDED.close_price,
                        pct_chg = EXCLUDED.pct_chg,
                        volume_ratio = EXCLUDED.volume_ratio,
                        turnover = EXCLUDED.turnover,
                        ma5 = EXCLUDED.ma5,
                        ma10 = EXCLUDED.ma10,
                        ma20 = EXCLUDED.ma20,
                        pct_5d = EXCLUDED.pct_5d,
                        pct_20d = EXCLUDED.pct_20d,
                        observe_low = EXCLUDED.observe_low,
                        observe_high = EXCLUDED.observe_high,
                        pressure_price = EXCLUDED.pressure_price,
                        invalid_price = EXCLUDED.invalid_price,
                        risk_level = EXCLUDED.risk_level,
                        action_signal = EXCLUDED.action_signal,
                        entry_reasons = EXCLUDED.entry_reasons,
                        risk_reasons = EXCLUDED.risk_reasons
                """, (
                    trade_date,
                    code,
                    name,
                    str(pool_name),
                    str(row.get("action_signal", "")),
                    json.dumps(row.get("hot_board_hits", []), ensure_ascii=False) if row.get("hot_board_hits") else None,
                    _num_or_none(row.get("close")),
                    _num_or_none(row.get("pct_chg")),
                    _num_or_none(row.get("volume_ratio")),
                    _num_or_none(row.get("turnover")),
                    _num_or_none(row.get("ma5")),
                    _num_or_none(row.get("ma10")),
                    _num_or_none(row.get("ma20")),
                    _num_or_none(row.get("pct_5d")),
                    _num_or_none(row.get("pct_20d")),
                    _num_or_none(row.get("observe_low")),
                    _num_or_none(row.get("observe_high")),
                    _num_or_none(row.get("pressure_price")),
                    _num_or_none(row.get("invalid_price")),
                    str(row.get("risk_level", "")),
                    str(row.get("action_signal", "")),
                    str(row.get("entry_reason", "")),
                    str(row.get("risk_reasons", "")),
                ))
                written += 1
            except Exception as e:
                failed += 1
                print(f"[错误] 写入 stock_signal 失败：{code} {name} {e}")
                logger.exception(f"写入 stock_signal 失败：{code} {name}")

    conn.commit()
    cur.close()
    if conn is not db_conn:
        conn.close()

    if total_candidates > 0 and written == 0:
        print("[警告] selector_result 有数据，但 stock_signal 未写入任何记录，请检查表结构和数据库权限。")
    else:
        print(f"stock_signal 写入完成：成功 {written} 条，失败 {failed} 条")


def save_data_quality_log(trade_date, quality, data_status, db_conn=None):
    """写入数据质量日志到 data_quality_log 表"""
    conn = db_conn if db_conn and not db_conn.closed else _get_db_conn()
    if conn is None:
        return
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO data_quality_log (
                trade_date, stock_count, industry_count, concept_count,
                has_board_amount_ratio, has_stock_board_map,
                has_3d_history, has_5d_history,
                ma_missing_ratio, confidence_score, issues
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            str(trade_date),
            int(data_status.get("stock_count", 0)),
            int(data_status.get("industry_count", 0)),
            int(data_status.get("concept_count", 0)),
            bool(quality.get("has_board_amount_ratio", False)),
            bool(quality.get("has_stock_board_map", False)),
            bool(quality.get("has_3d_history", False)),
            bool(quality.get("has_5d_history", False)),
            float(quality.get("ma_missing_ratio", 0)),
            int(quality.get("confidence_score", 0)),
            str("\n".join(quality.get("issues", []))),
        ))
        conn.commit()
        print("data_quality_log 写入完成")
    except Exception as e:
        print(f"[错误] data_quality_log 写入失败：{e}")
        logger.exception("data_quality_log 写入失败")
    finally:
        cur.close()
        if conn is not db_conn:
            conn.close()


def log_job_start(job_name, trade_date):
    """记录任务开始，返回记录 ID"""
    conn = _get_db_conn()
    if conn is None:
        return None
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO job_run_log (job_name, trade_date, status) VALUES (%s, %s, 'running') RETURNING id",
        (job_name, trade_date)
    )
    job_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return job_id


def log_job_end(job_id, status="success", error_message=None):
    """记录任务结束"""
    if job_id is None:
        return
    conn = _get_db_conn()
    if conn is None:
        return
    cur = conn.cursor()
    cur.execute(
        """UPDATE job_run_log
           SET status = %s, finished_at = CURRENT_TIMESTAMP,
               duration_seconds = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)),
               error_message = %s
           WHERE id = %s""",
        (status, error_message, job_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def generate_report_mode(trade_date, mode, data_status, market_result,
                         industry_result, concept_result, sentiment_result,
                         selector_result, board_ratio_changes, quality, themes,
                         trade_plan=None, board_trend_summary=None):
    """生成单个模式的报告并保存，返回报告文本"""
    report = render_daily_report(
        trade_date=trade_date,
        data_status=data_status,
        market=market_result,
        industry=industry_result,
        concept=concept_result,
        sentiment=sentiment_result,
        selectors=selector_result,
        board_ratio_changes=board_ratio_changes,
        mode=mode,
        quality=quality,
        themes=themes,
        trade_plan=trade_plan,
        board_trend_summary=board_trend_summary,
    )
    path = save_report(report, trade_date, mode)
    try:
        print(report)
    except UnicodeEncodeError:
        print(report.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
    print(f"报告已保存：{path}")

    # 写入数据库
    conn = _get_db_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO daily_report (trade_date, report_mode, report_type, content, confidence_score)
                   VALUES (%s, %s, %s, %s, %s)""",
                (trade_date, mode, "daily", report, quality["confidence_score"])
            )
            conn.commit()
            cur.close()
        except Exception as e:
            logger.exception(f"日报写入失败：{e}")
        finally:
            conn.close()

    return report


def main():
    parser = argparse.ArgumentParser(description="A 股每日分析报告")
    parser.add_argument("--mode", choices=["beginner", "pro", "both"], default="beginner",
                        help="报告模式：beginner / pro / both")
    parser.add_argument("--force", action="store_true",
                        help="强制执行（非交易日也运行）")
    args = parser.parse_args()

    force = args.force
    mode = args.mode
    modes = ["beginner", "pro"] if mode == "both" else [mode]

    trade_date = get_trade_date()

    if not force and not is_trade_day(trade_date):
        print(f"{trade_date} 非交易日，跳过分析（使用 --force 可强制执行）")
        return

    if force and not is_trade_day(trade_date):
        print(f"{trade_date} 非交易日，强制执行分析...")

    print(f"开始获取数据：{trade_date}（模式：{mode}）")

    # DB 连接
    db_conn = None
    try:
        db_conn = psycopg2.connect(DATABASE_DSN)
    except Exception as e:
        logger.exception(f"数据库连接失败：{e}")

    job_id = log_job_start("daily_report", trade_date)

    try:
        # 数据获取（只执行一次）
        stock_df = fetch_stock_spot()
        index_df = fetch_index_spot()
        industry_df = fetch_industry_boards()
        concept_df = fetch_concept_boards()
        stock_df = enrich_stock_indicators(stock_df)

        data_status = {
            "trade_date": trade_date,
            "stock_count": len(stock_df),
            "industry_count": len(industry_df),
            "concept_count": len(concept_df),
        }

        # 数据分析（只执行一次）
        market_result = analyze_market(stock_df, index_df)
        industry_result = analyze_boards(industry_df, board_type="行业")
        concept_result = analyze_boards(concept_df, board_type="概念")
        sentiment_result = analyze_sentiment(stock_df, industry_df, concept_df)

        market_score = market_result["score"]

        selector_result = run_all_selectors(
            stock_df=stock_df,
            industry_df=industry_df,
            concept_df=concept_df,
            market_score=market_score,
        )

        selector_result = enrich_selected_stocks_indicators(selector_result)

        # 同花顺热点股票级归因（按 code 精确匹配，失败不影响主流程）
        try:
            hot_data = ths_hot_reasons_by_stock()
            if hot_data:
                hot_map = {item["code"]: item["reason"] for item in hot_data}
                for pool_name, pool_df in selector_result.items():
                    if pool_df is None or pool_df.empty:
                        continue
                    pool_df["ths_reason"] = pool_df["code"].apply(
                        lambda c: hot_map.get(str(c).zfill(6), "")
                    )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"同花顺热点匹配失败：{e}")

        board_ratio_changes = get_board_ratio_changes()

        themes = detect_main_themes(
            industry_result=industry_result,
            concept_result=concept_result,
            board_ratio_changes=board_ratio_changes,
            stock_pools=selector_result,
        )

        quality = check_data_quality(trade_date, stock_df, industry_df, concept_df, db_conn, selector_result)

        save_data_quality_log(trade_date, quality, data_status, db_conn)

        # 板块资金趋势摘要
        board_trend_summary = load_board_trend_summary(trade_date)

        # 账户过滤
        filtered_result, excluded_result = filter_tradeable_stocks(selector_result)

        # 生成交易计划
        trade_plan = generate_trade_plan(
            trade_date, market_result, quality, themes,
            filtered_result, excluded_result
        )
        save_trade_plan(trade_plan, trade_date)

        # 生成结构化摘要 JSON
        summary = build_summary_json(trade_date, market_result, sentiment_result,
                                     themes, quality, selector_result)
        save_summary_json(summary, trade_date)

        # 写入 stock_signal
        save_stock_signals(selector_result, trade_date, db_conn)

        # 生成报告（每个 mode 一份）
        for m in modes:
            generate_report_mode(
                trade_date, m, data_status,
                market_result, industry_result, concept_result,
                sentiment_result, selector_result, board_ratio_changes,
                quality, themes,
                trade_plan=trade_plan,
                board_trend_summary=board_trend_summary,
            )

        log_job_end(job_id, "success")

    except Exception as e:
        logger.exception(f"日报生成失败：{e}")
        log_job_end(job_id, "failed", str(e))
        raise

    finally:
        if db_conn:
            try:
                db_conn.close()
            except Exception as e:
                logger.exception(f"关闭数据库连接失败：{e}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    main()
