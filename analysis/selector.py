import pandas as pd
import numpy as np
import argparse

from analysis.utils import fmt_pct


def _has_volume_ratio(df):
    """检测个股数据中是否有量比字段（Sina 数据源无量比）"""
    if "volume_ratio" not in df.columns:
        return False
    return df["volume_ratio"].notna().sum() > 100


def _vr_ge(df, threshold):
    """
    量比条件：量比 >= threshold。
    若量比字段缺失或全NaN（Sina数据源），视为条件通过。
    """
    if not _has_volume_ratio(df):
        return pd.Series(True, index=df.index)
    return df["volume_ratio"].fillna(threshold) >= threshold


def _vr_val(df, default=1.0):
    """获取量比值，缺失时返回默认值"""
    if not _has_volume_ratio(df):
        return pd.Series(default, index=df.index)
    return df["volume_ratio"].fillna(default)


def calc_trade_plan(row, style="short"):
    close = row["close"]

    if style == "aggressive":
        buy_low = close * 0.98
        buy_high = close * 1.02
        target = close * 1.10
        stop = close * 0.95
        hold_days = "2-5日"
    elif style == "latent":
        buy_low = close * 0.96
        buy_high = close * 1.00
        target = close * 1.15
        stop = close * 0.92
        hold_days = "5-10日"
    else:
        buy_low = close * 0.97
        buy_high = close * 1.01
        target = close * 1.10
        stop = close * 0.95
        hold_days = "3-5日"

    return {
        "buy_low": round(buy_low, 2),
        "buy_high": round(buy_high, 2),
        "target": round(target, 2),
        "stop_loss": round(stop, 2),
        "hold_days": hold_days,
    }


def add_common_fields(df, strategy_name, style="short", market_score=None):
    rows = []

    for _, row in df.iterrows():
        plan = calc_trade_plan(row, style=style)

        reason_parts = []

        pct = row.get("pct_chg", 0)
        if pd.notna(pct) and pct > 5:
            reason_parts.append(f"今日涨幅{fmt_pct(pct)}，短线资金关注")
        elif pd.notna(pct) and pct > 0:
            reason_parts.append(f"今日涨幅{fmt_pct(pct)}")

        vol_ratio = row.get("volume_ratio", 0)
        if pd.notna(vol_ratio) and vol_ratio > 1.5:
            reason_parts.append(f"量比{vol_ratio:.2f}，存在放量")
        elif pd.notna(vol_ratio) and vol_ratio > 1.0:
            reason_parts.append(f"量比{vol_ratio:.2f}")

        close_val = row.get("close", 0)
        ma5_val = row.get("ma5", np.nan)
        ma10_val = row.get("ma10", np.nan)
        ma20_val = row.get("ma20", np.nan)

        if pd.notna(ma5_val) and close_val > ma5_val:
            reason_parts.append("收盘价站上MA5")
        if pd.notna(ma20_val) and close_val > ma20_val:
            reason_parts.append("趋势保持在MA20上方")
        if (
            pd.notna(ma5_val)
            and pd.notna(ma10_val)
            and pd.notna(ma20_val)
            and ma5_val > ma10_val > ma20_val
        ):
            reason_parts.append("均线多头排列")

        pct_20d = row.get("pct_20d", 0)
        if pd.notna(pct_20d) and pct_20d > 10:
            reason_parts.append(f"20日涨幅{fmt_pct(pct_20d)}，趋势活跃")

        pct_5d = row.get("pct_5d", 0)
        if pd.notna(pct_5d) and pct_5d > 8:
            reason_parts.append(f"5日涨幅{fmt_pct(pct_5d)}，短期强势确认")

        if "hot_board_hits" in row and row.get("hot_board_hit_count", 0) > 0:
            hits = row.get("hot_board_hits", [])
            if isinstance(hits, list) and hits:
                reason_parts.append(f"命中强势板块：{'、'.join(hits[:3])}")

        if not reason_parts:
            reason_parts.append("技术形态符合策略筛选条件")

        entry_reason = "，".join(reason_parts)

        # 风险评价
        risk_info = {}
        if market_score is not None:
            from analysis.risk_engine import evaluate_stock_risk
            board_ctx = None
            if hasattr(row, 'get'):
                hot_hits = row.get("hot_board_hits", [])
                if isinstance(hot_hits, list) and hot_hits:
                    board_ctx = {"hot_board_hit": True, "board_ratio_declining": False}
                elif "hot_board_hit_count" in row.index and row.get("hot_board_hit_count", 0) == 0:
                    board_ctx = {"hot_board_hit": False, "board_ratio_declining": False}
            risk_info = evaluate_stock_risk(row, market_score, board_ctx)

        row_dict = {
            "strategy": strategy_name,
            "code": row.get("code"),
            "name": row.get("name"),
            "close": round(row.get("close", np.nan), 2),
            "pct_chg": round(row.get("pct_chg", np.nan), 2),
            "volume_ratio": round(row.get("volume_ratio", np.nan), 2),
            "turnover": round(row.get("turnover", np.nan), 2) if pd.notna(row.get("turnover", np.nan)) else np.nan,
            "ma5": round(row.get("ma5", np.nan), 2) if pd.notna(row.get("ma5", np.nan)) else np.nan,
            "ma10": round(row.get("ma10", np.nan), 2) if pd.notna(row.get("ma10", np.nan)) else np.nan,
            "ma20": round(row.get("ma20", np.nan), 2) if pd.notna(row.get("ma20", np.nan)) else np.nan,
            "pct_5d": round(row.get("pct_5d", np.nan), 1) if pd.notna(row.get("pct_5d", np.nan)) else np.nan,
            "pct_20d": round(row.get("pct_20d", np.nan), 1) if pd.notna(row.get("pct_20d", np.nan)) else np.nan,
            "observe_low": plan["buy_low"],
            "observe_high": plan["buy_high"],
            "pressure_price": plan["target"],
            "invalid_price": plan["stop_loss"],
            "buy_low": plan["buy_low"],       # 保留旧字段兼容
            "buy_high": plan["buy_high"],
            "target": plan["target"],
            "stop_loss": plan["stop_loss"],
            "hold_days": plan["hold_days"],
            "position": "1/5仓",
            "entry_reason": entry_reason,
            "reason": entry_reason,           # 保留旧字段兼容
            "risk_level": risk_info.get("risk_level", "数据不足") if risk_info else "数据不足",
            "action_signal": risk_info.get("action_signal", "数据不足") if risk_info else "数据不足",
            "risk_score_val": risk_info.get("risk_score", 8) if risk_info else 8,
            "risk_reasons": "\n".join(f"{i+1}. {r}" for i, r in enumerate(risk_info.get("risk_reasons", []))) if risk_info else "",
            "industry_tags": row.get("industry_tags", []),
            "concept_tags": row.get("concept_tags", []),
            "hot_board_hits": row.get("hot_board_hits", []),
            "hot_board_hit_count": row.get("hot_board_hit_count", 0),
        }
        rows.append(row_dict)

    return pd.DataFrame(rows)


def filter_common_stock_pool(stock_df):
    df = stock_df.copy()

    df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
    df = df[~df["code"].astype(str).str.startswith(("8", "4"))]
    df = df[df["close"] > 2]
    df = df[df["amount"] > 100000000]

    return df


def select_first_breakout(stock_df, limit=5, market_score=None):
    """一次起爆：今日涨幅较高、放量、站上短期均线"""
    df = filter_common_stock_pool(stock_df)

    cond = (
        (df["pct_chg"] >= 3)
        & (df["pct_chg"] <= 15)
        & _vr_ge(df, 1.2)
        & (df["close"] >= df["ma5"].fillna(df["close"]))
        & (df["amount"] >= 200000000)
    )

    result = df[cond].copy()

    vr = _vr_val(result, 1.0)
    result["score"] = (
        result["pct_chg"].fillna(0) * 0.4
        + vr * 2
        + result["turnover"].fillna(0) * 0.2
        - result["pct_5d"].fillna(0).clip(lower=0) * 0.05
    )

    result = result.sort_values("score", ascending=False).head(limit)
    return add_common_fields(result, "一次起爆", style="aggressive", market_score=market_score)


def select_n_latent(stock_df, limit=5, market_score=None):
    """N字异动：20日趋势有涨幅、近期回调不极端、价格在MA20附近"""
    df = filter_common_stock_pool(stock_df)

    cond = (
        (df["pct_20d"].fillna(0) >= 8)
        & (df["pct_5d"].fillna(0) <= 12)
        & (df["pct_chg"] > -4)
        & (df["close"] >= df["ma20"].fillna(df["close"]) * 0.97)
        & _vr_ge(df, 0.6)
    )

    result = df[cond].copy()

    vr = _vr_val(result, 1.0)
    result["score"] = (
        result["pct_20d"].fillna(0) * 0.35
        - result["pct_5d"].fillna(0) * 0.15
        + vr * 1.5
        + result["turnover"].fillna(0) * 0.1
    )

    result = result.sort_values("score", ascending=False).head(limit)
    return add_common_fields(result, "N字异动", style="latent", market_score=market_score)


def select_n_breakout(stock_df, limit=5, market_score=None):
    """二次起爆：前期有趋势、今日重新放量上涨、站上MA5/MA10"""
    df = filter_common_stock_pool(stock_df)

    cond = (
        (df["pct_chg"] >= 2)
        & _vr_ge(df, 1.3)
        & (df["pct_20d"].fillna(0) >= 10)
        & (df["close"] >= df["ma5"].fillna(df["close"]))
        & (df["close"] >= df["ma10"].fillna(df["close"]))
    )

    result = df[cond].copy()

    vr = _vr_val(result, 1.0)
    result["score"] = (
        result["pct_chg"].fillna(0) * 0.3
        + result["pct_20d"].fillna(0) * 0.3
        + vr * 2
        + result["turnover"].fillna(0) * 0.15
    )

    result = result.sort_values("score", ascending=False).head(limit)
    return add_common_fields(result, "二次起爆", style="aggressive", market_score=market_score)


def select_short_strong(stock_df, limit=5, market_score=None):
    """短线强势：今日涨幅强、量比高、成交额充足、均线多头排列"""
    df = filter_common_stock_pool(stock_df)

    cond = (
        (df["pct_chg"] >= 5)
        & _vr_ge(df, 1.5)
        & (df["amount"] >= 300000000)
        & (df["close"] >= df["ma5"].fillna(df["close"]))
        & (df["ma5"].fillna(0) >= df["ma10"].fillna(0))
    )

    result = df[cond].copy()

    vr = _vr_val(result, 1.0)
    result["score"] = (
        result["pct_chg"].fillna(0) * 0.5
        + vr * 2
        + result["turnover"].fillna(0) * 0.2
    )

    result = result.sort_values("score", ascending=False).head(limit)
    return add_common_fields(result, "短线强势", style="aggressive", market_score=market_score)


def select_board_linkage(stock_df, industry_df=None, concept_df=None, limit=5, market_score=None):
    """板块联动：优先使用数据库 stock_board_map 获取个股-板块映射；
    若不可用则降级为基于强势个股的近似筛选"""
    df = _select_board_linkage_db(stock_df, limit, market_score=market_score)
    if df is not None and not df.empty:
        return df

    return _select_board_linkage_fallback(stock_df, limit, market_score=market_score)


def _select_board_linkage_db(stock_df, limit=5, market_score=None):
    """基于数据库 stock_board_map 和 board_amount_ratio 的真实板块联动选股"""
    try:
        import psycopg2
        from data.config import DATABASE_DSN

        conn = psycopg2.connect(DATABASE_DSN)
        cur = conn.cursor()

        cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='stock_board_map')")
        has_stock_map = cur.fetchone()[0]

        cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='board_amount_ratio')")
        has_board_ratio = cur.fetchone()[0]

        if not has_stock_map or not has_board_ratio:
            conn.close()
            return None

        # 读取当日强势板块
        sql_hot = """
        SELECT board_type, board_name, pct_chg, amount_ratio
        FROM board_amount_ratio
        WHERE trade_date = (SELECT MAX(trade_date) FROM board_amount_ratio)
        """
        hot_df = pd.read_sql(sql_hot, conn)
        hot_df["board_score"] = hot_df["pct_chg"].fillna(0) * 0.5 + hot_df["amount_ratio"].fillna(0) * 100 * 0.5
        hot_df = hot_df.sort_values("board_score", ascending=False).head(30)
        hot_board_names = set(hot_df["board_name"].tolist())

        # 读取个股-板块映射
        mp_df = pd.read_sql("SELECT code, board_type, board_name FROM stock_board_map", conn)
        conn.close()

        industry_map = (
            mp_df[mp_df["board_type"] == "行业"]
            .groupby("code")["board_name"]
            .apply(lambda x: list(set(x)))
            .to_dict()
        )
        concept_map = (
            mp_df[mp_df["board_type"] == "概念"]
            .groupby("code")["board_name"]
            .apply(lambda x: list(set(x)))
            .to_dict()
        )

        df = filter_common_stock_pool(stock_df)
        df["industry_tags"] = df["code"].map(industry_map).apply(lambda x: x if isinstance(x, list) else [])
        df["concept_tags"] = df["code"].map(concept_map).apply(lambda x: x if isinstance(x, list) else [])

        def calc_board_hit(row):
            tags = set(row["industry_tags"] + row["concept_tags"])
            hit = tags & hot_board_names
            return list(hit)

        df["hot_board_hits"] = df.apply(calc_board_hit, axis=1)
        df["hot_board_hit_count"] = df["hot_board_hits"].apply(len)

        cond = (
            (df["hot_board_hit_count"] >= 1)
            & (df["pct_chg"] >= 3)
            & _vr_ge(df, 1.2)
            & (df["amount"] >= 200000000)
        )

        result = df[cond].copy()

        result["linkage_score"] = (
            result["hot_board_hit_count"] * 20
            + result["pct_chg"].fillna(0) * 2
            + _vr_val(result, 1.0) * 5
            + result["turnover"].fillna(0)
        )

        result = result.sort_values("linkage_score", ascending=False).head(limit)
        return add_common_fields(result, "板块联动", style="short", market_score=market_score)

    except Exception:
        return None


def _select_board_linkage_fallback(stock_df, limit=5, market_score=None):
    """降级版板块联动：基于强势个股近似筛选"""
    df = filter_common_stock_pool(stock_df)

    cond = (
        (df["pct_chg"] >= 4)
        & _vr_ge(df, 1.2)
        & (df["amount"] >= 200000000)
    )

    result = df[cond].copy()

    result["score"] = (
        result["pct_chg"].fillna(0) * 0.45
        + _vr_val(result, 1.0) * 2
        + result["amount"].fillna(0) / 1e8 * 0.05
    )

    result = result.sort_values("score", ascending=False).head(limit)
    return add_common_fields(result, "板块联动", style="short", market_score=market_score)


def run_all_selectors(stock_df, industry_df=None, concept_df=None, market_score=None):
    first = select_first_breakout(stock_df, limit=5, market_score=market_score)
    n_latent = select_n_latent(stock_df, limit=5, market_score=market_score)
    n_breakout = select_n_breakout(stock_df, limit=5, market_score=market_score)
    board_linkage = select_board_linkage(stock_df, industry_df, concept_df, limit=5, market_score=market_score)
    short_strong = select_short_strong(stock_df, limit=5, market_score=market_score)

    return {
        "一次起爆": first,
        "N字异动": n_latent,
        "二次起爆": n_breakout,
        "板块联动": board_linkage,
        "短线强势": short_strong,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--indicator", type=str, default="n_latent")
    args = parser.parse_args()

    from analysis.data_fetcher import fetch_stock_spot, enrich_stock_indicators, fetch_index_spot
    from analysis.market import analyze_market

    stock_df = enrich_stock_indicators(fetch_stock_spot())
    index_df = fetch_index_spot()
    market_result = analyze_market(stock_df, index_df)
    market_score = market_result["score"]

    indicators = args.indicator.split(",")

    result_map = {}

    if "n_latent" in indicators:
        result_map["N字异动"] = select_n_latent(stock_df, market_score=market_score)
    if "n_breakout" in indicators:
        result_map["二次起爆"] = select_n_breakout(stock_df, market_score=market_score)
    if "short_strong" in indicators:
        result_map["短线强势"] = select_short_strong(stock_df, market_score=market_score)
    if "first_breakout" in indicators:
        result_map["一次起爆"] = select_first_breakout(stock_df, market_score=market_score)
    if "board_linkage" in indicators:
        result_map["板块联动"] = select_board_linkage(stock_df, market_score=market_score)

    for name, df in result_map.items():
        print(f"\n{name}")
        print(df.to_string(index=False))


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    main()
