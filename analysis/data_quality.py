"""
数据质量检查模块
每次生成日报前检查数据完整性，计算报告可信度评分
"""
import pandas as pd
import numpy as np
from data.config import DATABASE_DSN, get_db_conn


def check_data_quality(trade_date, stock_df, industry_df, concept_df, db_conn=None, selector_result=None):
    """
    检查数据完整性，返回质量报告和可信度评分。

    返回：
        {
            "confidence_score": int,       # 0-100
            "items": [...],                # 每项检查结果
            "issues": [...],               # 问题列表
            "has_3d_history": bool,
            "has_5d_history": bool,
            "has_board_amount_ratio": bool,
            "has_stock_board_map": bool,
            "stock_board_map_days_old": int or None,
            "ma_missing_ratio": float,
            "obs_ma_coverage": float,      # 观察池均线覆盖率
        }
    """
    score = 100
    items = []
    issues = []

    # 1. 个股数据
    stock_count = len(stock_df) if stock_df is not None else 0
    if stock_count >= 5000:
        items.append({"item": "个股数据", "status": "正常", "detail": f"今日获取 {stock_count} 只股票"})
    elif stock_count >= 4000:
        items.append({"item": "个股数据", "status": "正常", "detail": f"今日获取 {stock_count} 只股票"})
    elif stock_count > 0:
        score -= 20
        items.append({"item": "个股数据", "status": "偏少", "detail": f"今日仅获取 {stock_count} 只股票"})
        issues.append("个股数据量偏少，可能影响分析准确性。")
    else:
        score -= 50
        items.append({"item": "个股数据", "status": "异常", "detail": "未获取到个股数据"})
        issues.append("个股数据获取失败，报告可能不完整。")

    # 2. 行业板块
    industry_count = len(industry_df) if industry_df is not None else 0
    if industry_count >= 80:
        items.append({"item": "行业板块", "status": "正常", "detail": f"今日获取 {industry_count} 个行业板块"})
    elif industry_count >= 50:
        score -= 10
        items.append({"item": "行业板块", "status": "偏少", "detail": f"今日获取 {industry_count} 个行业板块"})
        issues.append("行业板块数量偏少。")
    elif industry_count > 0:
        score -= 15
        items.append({"item": "行业板块", "status": "偏少", "detail": f"今日仅获取 {industry_count} 个行业板块"})
        issues.append("行业板块数据不足，板块分析可能不准确。")
    else:
        score -= 20
        items.append({"item": "行业板块", "status": "异常", "detail": "未获取到行业板块数据"})
        issues.append("行业板块数据缺失。")

    # 3. 概念板块
    concept_count = len(concept_df) if concept_df is not None else 0
    if concept_count >= 350:
        items.append({"item": "概念板块", "status": "正常", "detail": f"今日获取 {concept_count} 个概念板块"})
    elif concept_count >= 200:
        score -= 5
        items.append({"item": "概念板块", "status": "正常", "detail": f"今日获取 {concept_count} 个概念板块"})
    elif concept_count > 0:
        score -= 15
        items.append({"item": "概念板块", "status": "偏少", "detail": f"今日仅获取 {concept_count} 个概念板块"})
        issues.append("概念板块数据不足。")
    else:
        score -= 20
        items.append({"item": "概念板块", "status": "异常", "detail": "未获取到概念板块数据"})
        issues.append("概念板块数据缺失。")

    # 4. 板块行情数据是否可用
    has_board_data = False
    if industry_df is not None and not industry_df.empty:
        pct_col = "pct_chg" if "pct_chg" in industry_df.columns else None
        if pct_col and industry_df[pct_col].notna().sum() > 10:
            has_board_data = True

    if has_board_data:
        items.append({"item": "板块行情数据", "status": "正常", "detail": "板块涨跌幅、换手率等数据可用"})
    else:
        score -= 20
        items.append({"item": "板块行情数据", "status": "降级", "detail": "板块仅获取名称，无涨跌幅等行情数据（当前使用同花顺数据源）"})
        issues.append("板块行情数据缺失（东方财富数据源不可用），板块分析和情绪分布不完整。")

    # 5-8: 数据库相关检查
    has_board_amount_ratio = False
    has_3d_history = False
    has_5d_history = False
    has_stock_board_map = False
    stock_board_map_days_old = None
    ma_missing_ratio = 0.0

    # 确保连接可用，断开则重连
    if DATABASE_DSN:
        if db_conn is None or (hasattr(db_conn, 'closed') and db_conn.closed):
            try:
                db_conn = get_db_conn()
            except Exception:
                db_conn = None

    if db_conn is not None:
        try:
            cur = db_conn.cursor()

            # 板块成交占比表是否存在且有当日数据
            cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='board_amount_ratio')")
            if cur.fetchone()[0]:
                cur.execute("SELECT COUNT(*) FROM board_amount_ratio")
                ba_count = cur.fetchone()[0]
                if ba_count > 0:
                    cur.execute("SELECT COUNT(DISTINCT trade_date) FROM board_amount_ratio")
                    date_count = cur.fetchone()[0]
                    has_board_amount_ratio = True

                    if date_count >= 3:
                        has_3d_history = True
                    if date_count >= 5:
                        has_5d_history = True

                    items.append({
                        "item": "板块历史数据",
                        "status": "可用",
                        "detail": f"已有 {date_count} 个交易日数据" +
                                  ("，可计算 3日/5日变化" if has_5d_history else
                                   "，可计算 3日变化" if has_3d_history else
                                   "，暂不足以计算成交占比变化")
                    })
                else:
                    items.append({"item": "板块历史数据", "status": "暂无", "detail": "board_amount_ratio 表为空"})
            else:
                items.append({"item": "板块历史数据", "status": "未建表", "detail": "board_amount_ratio 表不存在"})

            # 个股板块映射
            cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='stock_board_map')")
            if cur.fetchone()[0]:
                cur.execute("SELECT COUNT(*) FROM stock_board_map")
                sm_count = cur.fetchone()[0]
                if sm_count > 0:
                    cur.execute("SELECT MAX(updated_at) FROM stock_board_map")
                    last_update = cur.fetchone()[0]
                    if last_update:
                        days_old = (pd.Timestamp.now() - pd.Timestamp(last_update)).days
                        stock_board_map_days_old = days_old
                    has_stock_board_map = True
                    items.append({"item": "个股板块映射", "status": "正常", "detail": f"共 {sm_count} 条映射记录"})
                else:
                    items.append({"item": "个股板块映射", "status": "暂无", "detail": "stock_board_map 表为空"})
            else:
                items.append({"item": "个股板块映射", "status": "未建表", "detail": "stock_board_map 表不存在"})

            cur.close()
        except Exception:
            items.append({"item": "数据库连接", "status": "异常", "detail": "数据库连接失败"})
            score -= 15
            issues.append("数据库连接失败，板块历史数据和个股映射不可用。")
    else:
        items.append({"item": "数据库", "status": "未连接", "detail": "未提供数据库连接"})

    # 扣分：历史数据不足
    if not has_board_amount_ratio:
        score -= 15
        issues.append("缺少板块成交占比历史数据，无法展示成交占比变化。")
    else:
        if not has_3d_history:
            score -= 10
            issues.append("板块历史数据不足 3 日，3日成交占比变化暂不展示。")
        if not has_5d_history:
            score -= 10
            issues.append("板块历史数据不足 5 日，5日成交占比变化暂不展示。")

    if not has_stock_board_map:
        score -= 10
        issues.append("缺少个股-板块映射表，板块联动选股使用降级方案。")
    elif stock_board_map_days_old and stock_board_map_days_old > 7:
        score -= 10
        issues.append(f"个股板块映射 {stock_board_map_days_old} 天未更新，可能不准确。")

    # 9. 均线数据
    if stock_df is not None and not stock_df.empty and "ma5" in stock_df.columns:
        total = len(stock_df)
        ma_missing = stock_df["ma5"].isna().sum()
        ma_missing_ratio = ma_missing / max(total, 1)
        if ma_missing_ratio < 0.1:
            items.append({"item": "均线数据", "status": "正常", "detail": "大部分个股均线数据可用"})
        elif ma_missing_ratio < 0.3:
            score -= 10
            items.append({"item": "均线数据", "status": "部分缺失", "detail": f"{ma_missing_ratio:.0%} 个股缺少均线数据"})
            issues.append("部分个股均线数据缺失，选股结果可能偏少。")
        else:
            score -= 20
            items.append({"item": "均线数据", "status": "大量缺失", "detail": f"{ma_missing_ratio:.0%} 个股缺少均线数据"})
            issues.append("大量个股均线数据缺失，选股策略参考价值下降。")
    else:
        ma_missing_ratio = 1.0
        items.append({"item": "均线数据", "status": "不可用", "detail": "无均线数据字段"})

    # 10. 数据源检测
    has_volume_ratio = True
    if stock_df is not None and not stock_df.empty and "data_source" in stock_df.columns:
        sources = stock_df["data_source"].unique().tolist()
        source_str = ",".join(sources)
        if "eastmoney" in sources:
            items.append({"item": "数据源", "status": "完整", "detail": f"主数据源：东方财富"})
        else:
            items.append({"item": "数据源", "status": "降级", "detail": f"当前使用：{source_str}（部分字段缺失）"})
    else:
        items.append({"item": "数据源", "status": "未知", "detail": "无法确定数据源"})

    # 11. 量比字段检测
    if stock_df is not None and not stock_df.empty:
        if "volume_ratio" not in stock_df.columns or stock_df["volume_ratio"].notna().sum() < 100:
            has_volume_ratio = False
            score -= 10
            items.append({"item": "量比字段", "status": "降级", "detail": "当前数据源缺少量比字段，量能筛选已降级"})
            issues.append("当前数据源缺少量比字段，量比相关筛选已自动降级，观察池可信度下降。")
        else:
            items.append({"item": "量比字段", "status": "正常", "detail": "量比数据可用"})
    else:
        has_volume_ratio = False
        items.append({"item": "量比字段", "status": "不可用", "detail": "无个股数据"})

    # 12. 观察池均线覆盖率
    obs_ma_coverage = 0.0
    obs_total = 0
    obs_has_ma = 0
    if selector_result:
        obs_total = 0
        obs_has_ma = 0
        for pool_df in selector_result.values():
            if pool_df is None or pool_df.empty:
                continue
            for _, row in pool_df.iterrows():
                obs_total += 1
                if pd.notna(row.get("ma5")) and pd.notna(row.get("ma20")):
                    obs_has_ma += 1
        obs_ma_coverage = obs_has_ma / max(obs_total, 1) if obs_total > 0 else 0.0

    if obs_total > 0:
        if obs_ma_coverage >= 0.7:
            items.append({"item": "观察池均线", "status": "正常", "detail": f"观察池均线覆盖率 {obs_ma_coverage:.0%}（{obs_has_ma}/{obs_total}）"})
        elif obs_ma_coverage >= 0.4:
            score -= 5
            items.append({"item": "观察池均线", "status": "部分缺失", "detail": f"观察池均线覆盖率 {obs_ma_coverage:.0%}（{obs_has_ma}/{obs_total}），部分股票缺少历史数据"})
            issues.append(f"观察池均线覆盖率仅 {obs_ma_coverage:.0%}。")
        elif obs_total > 0:
            score -= 10
            items.append({"item": "观察池均线", "status": "大量缺失", "detail": f"观察池均线覆盖率 {obs_ma_coverage:.0%}（{obs_has_ma}/{obs_total}）"})
            issues.append(f"观察池均线覆盖率仅 {obs_ma_coverage:.0%}，报告可读性下降。")

    # 数据质量说明
    items.append({
        "item": "数据说明",
        "status": "提示",
        "detail": "报告可信度主要反映基础行情和板块数据可用性；由于全市场均线缺失比例较高，依赖均线的选股结果需降低权重。"
    })

    # 确保分数在 0-100（所有检查完成后再计算）
    confidence_score = max(0, min(100, score))

    return {
        "confidence_score": confidence_score,
        "items": items,
        "issues": issues,
        "has_3d_history": has_3d_history,
        "has_5d_history": has_5d_history,
        "has_board_amount_ratio": has_board_amount_ratio,
        "has_stock_board_map": has_stock_board_map,
        "stock_board_map_days_old": stock_board_map_days_old,
        "ma_missing_ratio": ma_missing_ratio,
        "obs_ma_coverage": obs_ma_coverage,
        "has_volume_ratio": has_volume_ratio,
    }
