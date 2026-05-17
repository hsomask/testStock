"""
板块成交占比历史模块
每个交易日收盘后运行，将当日板块数据写入 board_amount_ratio 表
"""
import pandas as pd
import numpy as np
import psycopg2
from datetime import datetime

import akshare as ak
from data.config import DATABASE_DSN


def fetch_total_market_amount():
    stock_df = ak.stock_zh_a_spot_em()
    stock_df["成交额"] = pd.to_numeric(stock_df["成交额"], errors="coerce")
    return stock_df["成交额"].sum()


def fetch_industry_board_today():
    df = ak.stock_board_industry_name_em()
    df["board_type"] = "行业"
    return df


def fetch_concept_board_today():
    df = ak.stock_board_concept_name_em()
    df["board_type"] = "概念"
    return df


def normalize_board_df(df, total_amount):
    rename_map = {
        "板块名称": "board_name",
        "板块代码": "board_code",
        "涨跌幅": "pct_chg",
        "成交额": "amount",
        "换手率": "turnover",
        "上涨家数": "up_count",
        "下跌家数": "down_count",
        "领涨股票": "leader_name",
        "领涨股票-涨跌幅": "leader_pct_chg",
    }

    df = df.rename(columns=rename_map)

    for col in ["pct_chg", "amount", "turnover", "up_count", "down_count", "leader_pct_chg"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "amount" not in df.columns:
        df["amount"] = None

    df["amount_ratio"] = df["amount"] / total_amount

    keep_cols = [
        "board_type", "board_code", "board_name", "pct_chg",
        "amount", "amount_ratio", "turnover",
        "up_count", "down_count",
        "leader_name", "leader_pct_chg"
    ]

    for col in keep_cols:
        if col not in df.columns:
            df[col] = None

    return df[keep_cols]


def save_board_amount_ratio(df, trade_date):
    conn = psycopg2.connect(DATABASE_DSN)
    cur = conn.cursor()

    sql = """
    INSERT INTO board_amount_ratio (
        trade_date, board_type, board_code, board_name,
        pct_chg, amount, amount_ratio, turnover,
        up_count, down_count, leader_name, leader_pct_chg
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (trade_date, board_type, board_name)
    DO UPDATE SET
        board_code = EXCLUDED.board_code,
        pct_chg = EXCLUDED.pct_chg,
        amount = EXCLUDED.amount,
        amount_ratio = EXCLUDED.amount_ratio,
        turnover = EXCLUDED.turnover,
        up_count = EXCLUDED.up_count,
        down_count = EXCLUDED.down_count,
        leader_name = EXCLUDED.leader_name,
        leader_pct_chg = EXCLUDED.leader_pct_chg;
    """

    for _, row in df.iterrows():
        cur.execute(sql, (
            trade_date,
            row["board_type"],
            row["board_code"],
            row["board_name"],
            row["pct_chg"],
            row["amount"],
            row["amount_ratio"],
            row["turnover"],
            row["up_count"],
            row["down_count"],
            row["leader_name"],
            row["leader_pct_chg"],
        ))

    conn.commit()
    cur.close()
    conn.close()


def update_board_history():
    trade_date = datetime.now().strftime("%Y-%m-%d")

    total_amount = fetch_total_market_amount()

    industry_df = fetch_industry_board_today()
    concept_df = fetch_concept_board_today()

    industry_df = normalize_board_df(industry_df, total_amount)
    concept_df = normalize_board_df(concept_df, total_amount)

    all_df = pd.concat([industry_df, concept_df], ignore_index=True)

    save_board_amount_ratio(all_df, trade_date)

    print(f"板块成交占比已更新：{trade_date}，共 {len(all_df)} 条")


def calc_board_ratio_change(board_type="行业", window=3):
    """计算板块成交占比 N日变化，返回当日数据附带 ratio_today, ratio_before, ratio_change"""
    conn = psycopg2.connect(DATABASE_DSN)

    sql = """
    SELECT trade_date, board_type, board_name, amount_ratio, pct_chg, amount
    FROM board_amount_ratio
    WHERE board_type = %s
    ORDER BY trade_date ASC
    """

    df = pd.read_sql(sql, conn, params=(board_type,))
    conn.close()

    if df.empty:
        return pd.DataFrame()

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["amount_ratio"] = pd.to_numeric(df["amount_ratio"], errors="coerce")

    # 获取最近 N 个交易日
    all_dates = sorted(df["trade_date"].unique())
    if len(all_dates) < window:
        return pd.DataFrame()

    recent_dates = all_dates[-window:]
    latest_date = all_dates[-1]

    pivot = df.pivot_table(
        index="board_name",
        columns="trade_date",
        values="amount_ratio",
        aggfunc="first"
    )

    latest_df = df[df["trade_date"] == latest_date].copy()

    if recent_dates[-1] in pivot.columns and recent_dates[0] in pivot.columns:
        latest_df["ratio_today"] = latest_df["board_name"].map(pivot[recent_dates[-1]])
        latest_df["ratio_before"] = latest_df["board_name"].map(pivot[recent_dates[0]])
        latest_df[f"ratio_change_{window}d"] = (
            latest_df["ratio_today"] - latest_df["ratio_before"]
        )
    else:
        return pd.DataFrame()

    latest_df = latest_df.sort_values(f"ratio_change_{window}d", ascending=False)
    return latest_df


def get_all_ratio_changes():
    """获取行业和概念的 3日/5日成交占比变化，供日报使用"""
    result = {}

    for board_type, label in [("行业", "industry"), ("概念", "concept")]:
        for window in [3, 5]:
            change_df = calc_board_ratio_change(board_type, window)
            if change_df.empty:
                result[f"{label}_ratio_{window}d_up"] = pd.DataFrame()
                result[f"{label}_ratio_{window}d_down"] = pd.DataFrame()
                continue

            col_name = f"ratio_change_{window}d"
            if col_name not in change_df.columns:
                continue

            up = change_df[change_df[col_name] > 0].head(10).copy()
            down = change_df[change_df[col_name] < 0].sort_values(col_name, ascending=True).head(10).copy()

            result[f"{label}_ratio_{window}d_up"] = up
            result[f"{label}_ratio_{window}d_down"] = down

    return result


if __name__ == "__main__":
    update_board_history()
