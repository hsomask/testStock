"""
A 股每日分析报告主入口
运行：
  python -m analysis.daily_report
  python -m analysis.daily_report --mode beginner
  python -m analysis.daily_report --mode pro
  python -m analysis.daily_report --force
"""
import argparse
import logging
import psycopg2

logger = logging.getLogger(__name__)

from analysis.data_fetcher import (
    get_trade_date,
    is_trade_day,
    fetch_stock_spot,
    fetch_index_spot,
    fetch_industry_boards,
    fetch_concept_boards,
    enrich_stock_indicators,
)
from analysis.market import analyze_market
from analysis.board import analyze_boards
from analysis.sentiment import analyze_sentiment
from analysis.selector import run_all_selectors
from analysis.report_renderer import render_daily_report, save_report
from analysis.data_quality import check_data_quality
from analysis.theme_detector import detect_main_themes
from data.config import DATABASE_DSN


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


def main():
    parser = argparse.ArgumentParser(description="A 股每日分析报告")
    parser.add_argument("--mode", choices=["beginner", "pro"], default="beginner",
                        help="报告模式：beginner（小白友好版）或 pro（专业版）")
    parser.add_argument("--force", action="store_true",
                        help="强制执行（非交易日也运行）")
    args = parser.parse_args()

    force = args.force
    mode = args.mode

    trade_date = get_trade_date()

    if not force and not is_trade_day(trade_date):
        print(f"{trade_date} 非交易日，跳过分析（使用 --force 可强制执行）")
        return

    if force and not is_trade_day(trade_date):
        print(f"{trade_date} 非交易日，强制执行分析...")

    print(f"开始获取数据：{trade_date}（模式：{mode}）")

    # 数据获取
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

    # 数据分析
    market_result = analyze_market(stock_df, index_df)
    industry_result = analyze_boards(industry_df, board_type="行业")
    concept_result = analyze_boards(concept_df, board_type="概念")
    sentiment_result = analyze_sentiment(stock_df, industry_df, concept_df)

    market_score = market_result["score"]

    # 数据质量检查
    db_conn = None
    try:
        db_conn = psycopg2.connect(DATABASE_DSN)
    except Exception as e:
        logger.exception(f"数据库连接失败：{e}")

    quality = check_data_quality(trade_date, stock_df, industry_df, concept_df, db_conn)

    # 选股
    selector_result = run_all_selectors(
        stock_df=stock_df,
        industry_df=industry_df,
        concept_df=concept_df,
        market_score=market_score,
    )

    # 板块成交占比变化
    board_ratio_changes = get_board_ratio_changes()

    # 主线判断
    themes = detect_main_themes(
        industry_result=industry_result,
        concept_result=concept_result,
        board_ratio_changes=board_ratio_changes,
        stock_pools=selector_result,
    )

    # 关闭数据库连接
    if db_conn:
        try:
            db_conn.close()
        except Exception as e:
            logger.exception(f"关闭数据库连接失败：{e}")

    # 生成报告
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
    )

    path = save_report(report, trade_date, mode)
    try:
        print(report)
    except UnicodeEncodeError:
        print(report.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
    print(f"报告已保存：{path}")

    # 存入数据库
    if db_conn:
        try:
            db_conn2 = psycopg2.connect(DATABASE_DSN)
            cur = db_conn2.cursor()
            cur.execute(
                """INSERT INTO daily_report (trade_date, report_mode, report_type, content, confidence_score)
                   VALUES (%s, %s, %s, %s, %s)""",
                (trade_date, mode, "daily", report, quality["confidence_score"])
            )
            db_conn2.commit()
            cur.close()
            db_conn2.close()
        except Exception as e:
            logger.exception(f"日报写入失败：{e}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    main()
