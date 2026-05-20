"""
个股所属行业/概念映射模块
每周运行一次，将板块成分股数据写入 stock_board_map 表
支持断点续跑：已存在的 board 跳过，每板块即时落表
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


def _board_already_mapped(cur, board_type, board_name):
    """检查该板块是否已写入过"""
    cur.execute(
        "SELECT COUNT(*) FROM stock_board_map WHERE board_type=%s AND board_name=%s",
        (board_type, board_name)
    )
    return cur.fetchone()[0] > 0


def _flush_batch(cur, batch, conn):
    """写入一批记录"""
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
    for row in batch:
        cur.execute(sql, (
            row["code"], row["name"], row["board_type"],
            row["board_name"], row["source"],
        ))
    conn.commit()


def _map_boards(boards, board_type_label, cur, conn):
    """遍历板块列表，逐个获取成分股并即时落表"""
    total_written = 0
    batch = []

    for idx, (board_code, board_name) in enumerate(boards):
        if _board_already_mapped(cur, board_type_label, board_name):
            if idx % 50 == 0:
                print(f"  [{idx+1}/{len(boards)}] {board_name} — 已存在，跳过")
            continue

        try:
            cons = _get_board_cons(board_code)
            for code, name in cons:
                batch.append({
                    "code": code, "name": name,
                    "board_type": board_type_label,
                    "board_name": board_name,
                    "source": "push2delay",
                })

            # 每收集约 50 条就落表
            if len(batch) >= 50:
                _flush_batch(cur, batch, conn)
                total_written += len(batch)
                batch = []

            print(f"  [{idx+1}/{len(boards)}] {board_name} — {len(cons)}只")
            time.sleep(0.15)

        except Exception as e:
            print(f"  [{idx+1}/{len(boards)}] {board_name} — 失败：{e}")

    # 剩余批次落表
    if batch:
        _flush_batch(cur, batch, conn)
        total_written += len(batch)

    return total_written


def update_industry_stock_map(cur, conn):
    boards = _get_board_list("行业")
    print(f"行业板块列表：{len(boards)} 个")
    written = _map_boards(boards, "行业", cur, conn)
    print(f"行业映射完成，本次写入 {written} 条")


def update_concept_stock_map(cur, conn):
    boards = _get_board_list("概念")
    print(f"概念板块列表：{len(boards)} 个")
    written = _map_boards(boards, "概念", cur, conn)
    print(f"概念映射完成，本次写入 {written} 条")


def update_all_stock_board_map():
    if not DATABASE_DSN:
        print("DATABASE_DSN 未配置")
        return

    conn = psycopg2.connect(DATABASE_DSN)
    cur = conn.cursor()

    try:
        update_industry_stock_map(cur, conn)
    except Exception as e:
        print(f"行业映射异常：{e}")

    try:
        update_concept_stock_map(cur, conn)
    except Exception as e:
        print(f"概念映射异常：{e}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    update_all_stock_board_map()
