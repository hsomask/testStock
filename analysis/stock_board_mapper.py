"""
个股所属行业/概念映射模块
每周运行一次，将 AkShare 板块成分股数据写入 stock_board_map 表
"""
import time
import akshare as ak
import pandas as pd
import psycopg2
from data.config import DATABASE_DSN


def save_stock_board_map(rows):
    if not rows:
        return

    conn = psycopg2.connect(DATABASE_DSN)
    cur = conn.cursor()

    sql = """
    INSERT INTO stock_board_map (
        code, name, board_type, board_name, source
    )
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (code, board_type, board_name)
    DO UPDATE SET
        name = EXCLUDED.name,
        source = EXCLUDED.source,
        updated_at = CURRENT_TIMESTAMP;
    """

    for row in rows:
        cur.execute(sql, (
            row["code"],
            row["name"],
            row["board_type"],
            row["board_name"],
            row["source"],
        ))

    conn.commit()
    cur.close()
    conn.close()


def update_industry_stock_map():
    board_df = ak.stock_board_industry_name_em()
    board_names = board_df["板块名称"].dropna().unique().tolist()

    all_rows = []

    for board_name in board_names:
        try:
            cons = ak.stock_board_industry_cons_em(symbol=board_name)

            for _, row in cons.iterrows():
                all_rows.append({
                    "code": str(row.get("代码", "")).zfill(6),
                    "name": row.get("名称", ""),
                    "board_type": "行业",
                    "board_name": board_name,
                    "source": "akshare_industry_cons_em",
                })

            print(f"行业映射完成：{board_name}，{len(cons)}只")

            time.sleep(0.3)

        except Exception as e:
            print(f"行业映射失败：{board_name}，错误：{e}")

    save_stock_board_map(all_rows)

    print(f"行业成分股映射更新完成，共 {len(all_rows)} 条")


def update_concept_stock_map():
    board_df = ak.stock_board_concept_name_em()
    board_names = board_df["板块名称"].dropna().unique().tolist()

    all_rows = []

    for board_name in board_names:
        try:
            cons = ak.stock_board_concept_cons_em(symbol=board_name)

            for _, row in cons.iterrows():
                all_rows.append({
                    "code": str(row.get("代码", "")).zfill(6),
                    "name": row.get("名称", ""),
                    "board_type": "概念",
                    "board_name": board_name,
                    "source": "akshare_concept_cons_em",
                })

            print(f"概念映射完成：{board_name}，{len(cons)}只")

            time.sleep(0.3)

        except Exception as e:
            print(f"概念映射失败：{board_name}，错误：{e}")

    save_stock_board_map(all_rows)

    print(f"概念成分股映射更新完成，共 {len(all_rows)} 条")


def update_all_stock_board_map():
    update_industry_stock_map()
    update_concept_stock_map()


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    update_all_stock_board_map()
