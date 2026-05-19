"""
个股所属行业/概念映射模块
每周运行一次，将板块成分股数据写入 stock_board_map 表
"""
import time
import pandas as pd
import psycopg2
import requests

from data.config import DATABASE_DSN


def _fetch_em_paginated(fs_filter, fields, pz=100):
    """使用 push2delay 分页获取 EastMoney 数据"""
    s = requests.Session()
    s.trust_env = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    })
    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    all_rows = []
    page = 1
    total = None
    while True:
        params = {"pn": str(page), "pz": str(pz), "po": "1", "np": "1",
                  "fltt": "2", "invt": "2", "fid": "f3",
                  "fs": fs_filter, "fields": fields}
        resp = s.get(url, params=params, timeout=30)
        data = resp.json()
        if total is None:
            total = data.get("data", {}).get("total", 0)
        diff = data.get("data", {}).get("diff") or []
        all_rows.extend(diff)
        if len(all_rows) >= total:
            break
        page += 1
    return pd.DataFrame(all_rows)


def _get_board_list(board_type_label):
    """获取行业或概念板块名称和代码列表"""
    fs_filter = "m:90+t:2" if board_type_label == "行业" else "m:90+t:3"
    df = _fetch_em_paginated(fs_filter, "f12,f14", pz=500)
    if df.empty:
        return []
    return [(row["f12"], row["f14"]) for _, row in df.iterrows() if pd.notna(row.get("f14"))]


def _get_board_cons(board_code):
    """获取板块成分股"""
    df = _fetch_em_paginated(f"b:{board_code}", "f12,f14", pz=500)
    if df.empty:
        return []
    return [(str(row["f12"]).zfill(6), row.get("f14", "")) for _, row in df.iterrows()]


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
    boards = _get_board_list("行业")
    print(f"获取行业板块列表：{len(boards)} 个")

    all_rows = []
    for board_code, board_name in boards:
        try:
            cons = _get_board_cons(board_code)
            for code, name in cons:
                all_rows.append({
                    "code": code,
                    "name": name,
                    "board_type": "行业",
                    "board_name": board_name,
                    "source": "push2delay",
                })
            print(f"行业映射完成：{board_name}，{len(cons)}只")
            time.sleep(0.2)
        except Exception as e:
            print(f"行业映射失败：{board_name}，错误：{e}")

    save_stock_board_map(all_rows)
    print(f"行业成分股映射更新完成，共 {len(all_rows)} 条")


def update_concept_stock_map():
    boards = _get_board_list("概念")
    print(f"获取概念板块列表：{len(boards)} 个")

    all_rows = []
    for board_code, board_name in boards:
        try:
            cons = _get_board_cons(board_code)
            for code, name in cons:
                all_rows.append({
                    "code": code,
                    "name": name,
                    "board_type": "概念",
                    "board_name": board_name,
                    "source": "push2delay",
                })
            print(f"概念映射完成：{board_name}，{len(cons)}只")
            time.sleep(0.2)
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
