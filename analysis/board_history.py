"""
板块成交占比历史模块
每个交易日收盘后运行，将当日板块数据写入 board_amount_ratio 表
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime

import akshare as ak
from data.config import DATABASE_DSN, get_db_conn
from analysis.utils import to_date_display


def _safe_int(val):
    """安全转换为 int，NaN/None 返回 None"""
    import numpy as np
    try:
        v = float(val)
        if np.isnan(v) or np.isinf(v):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None

logger = logging.getLogger(__name__)


def fetch_total_market_amount(stock_df):
    """从个股行情汇总全市场成交额"""
    if stock_df is None or stock_df.empty:
        return 0
    if "amount" not in stock_df.columns:
        return 0
    return stock_df["amount"].sum()


def fetch_industry_board_today():
    from analysis.data_fetcher import _fetch_em_delay
    fs_filter = "m:90+t:2"
    fields = "f2,f3,f4,f6,f8,f12,f14,f20,f104,f105,f128,f136"
    rename_map = {
        "f12": "board_code", "f14": "board_name", "f2": "price",
        "f3": "pct_chg", "f6": "amount", "f8": "turnover",
        "f20": "total_mv", "f104": "up_count", "f105": "down_count",
        "f128": "leader_name", "f136": "leader_pct_chg",
    }
    numeric_cols = ["price", "pct_chg", "amount", "total_mv", "turnover",
                    "up_count", "down_count", "leader_pct_chg"]
    df = _fetch_em_delay(fs_filter, fields, rename_map, numeric_cols, pz=500)
    df["board_type"] = "行业"
    return df


def fetch_concept_board_today():
    from analysis.data_fetcher import _fetch_em_delay
    fs_filter = "m:90+t:3"
    fields = "f2,f3,f4,f6,f8,f12,f14,f20,f104,f105,f128,f136"
    rename_map = {
        "f12": "board_code", "f14": "board_name", "f2": "price",
        "f3": "pct_chg", "f6": "amount", "f8": "turnover",
        "f20": "total_mv", "f104": "up_count", "f105": "down_count",
        "f128": "leader_name", "f136": "leader_pct_chg",
    }
    numeric_cols = ["price", "pct_chg", "amount", "total_mv", "turnover",
                    "up_count", "down_count", "leader_pct_chg"]
    df = _fetch_em_delay(fs_filter, fields, rename_map, numeric_cols, pz=500)
    df["board_type"] = "概念"
    return df


def normalize_board_df(board_df, stock_df, total_amount, db_conn):
    """
    基于成分股聚合计算板块成交额。

    优先使用 stock_board_map 表获取成分股，按 code 匹配 stock_df 的 amount 汇总。
    如果 stock_board_map 不可用，则 report_renderer 显示"板块成交额暂缺"。
    """
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

    board_df = board_df.rename(columns=rename_map)

    for col in ["pct_chg", "turnover", "up_count", "down_count", "leader_pct_chg"]:
        if col in board_df.columns:
            board_df[col] = pd.to_numeric(board_df[col], errors="coerce")

    # 尝试从 stock_board_map 计算板块成交额
    map_df = pd.DataFrame()
    try:
        cur = db_conn.cursor()
        cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='stock_board_map')")
        if cur.fetchone()[0]:
            map_df = pd.read_sql("SELECT code, board_type, board_name FROM stock_board_map", db_conn)
        cur.close()
    except Exception as e:
        logger.exception(f"读取 stock_board_map 失败：{e}")

    if map_df.empty:
        logger.warning("stock_board_map 为空，无法计算板块成交占比")
        logger.warning("本次 board_amount_ratio 将写入基础板块信息，但 amount 和 amount_ratio 为空")
        board_df["amount"] = None
        board_df["amount_ratio"] = None
    else:
        # 合并成分股与个股行情
        merged = map_df.merge(
            stock_df[["code", "amount", "pct_chg"]].copy(),
            on="code",
            how="left"
        )

        board_amount = (
            merged
            .groupby(["board_type", "board_name"], as_index=False)
            .agg(
                amount=("amount", "sum"),
                member_count=("code", "count"),
                valid_amount_count=("amount", "count")
            )
        )

        # 计算板块涨幅（成分股涨幅均值）
        board_pct = (
            merged
            .groupby(["board_type", "board_name"], as_index=False)
            .agg(calc_pct_chg=("pct_chg", "mean"))
        )

        # 删除板块接口原始 amount 列，避免 merge 后出现 amount_x / amount_y
        if "amount" in board_df.columns:
            board_df = board_df.drop(columns=["amount"])

        # 合并成交额和涨幅
        board_df = board_df.merge(
            board_amount[["board_type", "board_name", "amount", "member_count", "valid_amount_count"]],
            on=["board_type", "board_name"],
            how="left"
        )

        if total_amount > 0:
            board_df["amount_ratio"] = board_df["amount"] / total_amount
        else:
            board_df["amount_ratio"] = None

    keep_cols = [
        "board_type", "board_code", "board_name", "pct_chg",
        "amount", "amount_ratio", "turnover",
        "up_count", "down_count",
        "leader_name", "leader_pct_chg"
    ]

    for col in keep_cols:
        if col not in board_df.columns:
            board_df[col] = None

    return board_df[keep_cols]


def save_board_amount_ratio(df, trade_date):
    if not DATABASE_DSN:
        logger.warning("DATABASE_DSN 未设置，跳过数据库写入")
        return
    db_trade_date = to_date_display(trade_date)
    conn = get_db_conn()
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
            db_trade_date,
            row["board_type"],
            row["board_code"],
            row["board_name"],
            row["pct_chg"],
            row["amount"],
            row["amount_ratio"],
            row["turnover"],
            _safe_int(row.get("up_count")),
            _safe_int(row.get("down_count")),
            row["leader_name"],
            row["leader_pct_chg"],
        ))

    conn.commit()
    cur.close()
    conn.close()


def update_board_history(trade_date=None):
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    today_ymd = trade_date.replace("-", "")

    if not DATABASE_DSN:
        logger.warning("DATABASE_DSN 未设置，数据库功能跳过")
        return

    from analysis.data_fetcher import is_trade_day
    if not is_trade_day(today_ymd):
        print(f"{today_ymd} 非交易日，跳过板块成交占比更新")
        return

    conn = get_db_conn()

    from analysis.data_fetcher import fetch_stock_spot
    stock_df = fetch_stock_spot()
    total_amount = fetch_total_market_amount(stock_df)

    industry_df = fetch_industry_board_today()
    concept_df = fetch_concept_board_today()

    industry_df = normalize_board_df(industry_df, stock_df, total_amount, conn)
    concept_df = normalize_board_df(concept_df, stock_df, total_amount, conn)

    all_df = pd.concat([industry_df, concept_df], ignore_index=True)

    conn.close()

    save_board_amount_ratio(all_df, trade_date)

    valid_count = all_df["amount"].notna().sum()
    if valid_count == 0:
        print("[警告] 板块映射数据暂缺，本次未能计算成交额和成交占比。请先运行：python -m analysis.stock_board_mapper")
    else:
        print(f"板块成交占比已更新：{trade_date}，共 {len(all_df)} 条（{valid_count} 条有成交额数据）")


def calc_board_ratio_change(board_type="行业", window=3):
    """计算板块成交占比 N日变化，返回当日数据附带 ratio_today, ratio_before, ratio_change"""
    if not DATABASE_DSN:
        logger.warning("DATABASE_DSN 未设置")
        return pd.DataFrame()
    conn = get_db_conn()

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
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None, help="日期 YYYYMMDD")
    args = parser.parse_args()
    date = to_date_display(args.date) if args.date else None
    update_board_history(trade_date=date)
