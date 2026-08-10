"""
个股所属行业/概念映射模块
每周运行一次，按板块刷新成分股数据写入 stock_board_map 表
刷新策略：delete old + insert latest（空数据时保留旧映射）
"""
import time
import psycopg2

from data.config import DATABASE_DSN
from analysis.data_sources.eastmoney_board import (
    fetch_board_constituents,
    fetch_board_list,
)

def _refresh_board(conn, board_type_label, board_name, constituents):
    """刷新单个板块映射：delete old + insert latest。
    如果成分股为空，保留旧数据不删除。
    返回 (status, deleted, inserted, elapsed)
    """
    if constituents is None or len(constituents) == 0:
        return ("empty_skipped", 0, 0, 0)

    cur = conn.cursor()
    deleted = 0
    inserted = 0
    t0 = time.time()

    try:
        cur.execute(
            "DELETE FROM stock_board_map WHERE board_type = %s AND board_name = %s",
            (board_type_label, board_name),
        )
        deleted = cur.rowcount

        for code, name in constituents:
            cur.execute(
                """INSERT INTO stock_board_map
                   (code, name, board_type, board_name, source, updated_at)
                   VALUES (%s, %s, %s, %s, %s, NOW())
                   ON CONFLICT (code, board_type, board_name)
                   DO UPDATE SET
                       name = EXCLUDED.name,
                       source = EXCLUDED.source,
                       updated_at = NOW()""",
                (code, name, board_type_label, board_name, "push2delay"),
            )
            inserted += 1

        conn.commit()
        elapsed = time.time() - t0
        return ("refreshed", deleted, inserted, elapsed)

    except Exception as e:
        conn.rollback()
        elapsed = time.time() - t0
        print(f"  [ERROR] {board_name} 刷新失败：{e}，已回滚该板块")
        return ("failed", 0, 0, elapsed)

    finally:
        cur.close()


def _map_boards(boards, board_type_label, conn):
    """遍历板块列表，逐个刷新成分股"""
    total_board_count = len(boards)
    refreshed = 0
    empty_skipped = 0
    failed = 0
    total_deleted = 0
    total_inserted = 0
    start_time = time.time()

    for idx, (board_code, board_name) in enumerate(boards):
        try:
            cons = fetch_board_constituents(board_code)
        except Exception as e:
            print(f"  [{idx+1}/{total_board_count}] {board_name} — 获取成分股失败：{e}")
            failed += 1
            continue

        if not cons:
            empty_skipped += 1
            if idx % 50 == 0:
                print(f"  [{idx+1}/{total_board_count}] {board_name} — 空数据，保留旧映射，跳过")
            continue

        status, deleted, inserted, elapsed = _refresh_board(
            conn, board_type_label, board_name, cons
        )

        if status == "refreshed":
            refreshed += 1
            total_deleted += deleted
            total_inserted += inserted
            if idx % 50 == 0:
                print(f"  [{idx+1}/{total_board_count}] {board_name} — 刷新完成，删除 {deleted} 条，写入 {inserted} 条，用时 {elapsed:.1f}s")
        elif status == "empty_skipped":
            empty_skipped += 1
            print(f"  [{idx+1}/{total_board_count}] {board_name} — 空数据，保留旧映射，跳过")
        else:
            failed += 1
            print(f"  [{idx+1}/{total_board_count}] {board_name} — 刷新失败，已回滚")

        time.sleep(0.15)

    elapsed = time.time() - start_time
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)

    print(f"\n{board_type_label}映射完成：")
    print(f"  - 板块数：{total_board_count}")
    print(f"  - 成功刷新板块数：{refreshed}")
    print(f"  - 空数据跳过板块数：{empty_skipped}")
    print(f"  - 失败板块数：{failed}")
    print(f"  - 删除旧记录数：{total_deleted}")
    print(f"  - 写入新记录数：{total_inserted}")
    print(f"  - 耗时：{mins} 分 {secs} 秒")

    return refreshed, empty_skipped, failed, total_deleted, total_inserted, elapsed


def update_industry_stock_map(conn):
    boards = fetch_board_list("行业")
    if not boards:
        raise RuntimeError("industry board list is empty; existing mappings retained")
    print(f"行业板块列表：{len(boards)} 个")
    return _map_boards(boards, "行业", conn)


def update_concept_stock_map(conn):
    boards = fetch_board_list("概念")
    if not boards:
        raise RuntimeError("concept board list is empty; existing mappings retained")
    print(f"概念板块列表：{len(boards)} 个")
    return _map_boards(boards, "概念", conn)


def update_all_stock_board_map():
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is not configured")

    conn = psycopg2.connect(DATABASE_DSN)
    overall_start = time.time()
    scope_errors = []

    # 行业映射
    ind_result = None
    try:
        ind_result = update_industry_stock_map(conn)
    except Exception as e:
        print(f"行业映射异常：{e}")
        scope_errors.append(f"industry: {e}")
        ind_result = (0, 0, 0, 0, 0, 0)

    # 概念映射
    con_result = None
    try:
        con_result = update_concept_stock_map(conn)
    except Exception as e:
        print(f"概念映射异常：{e}")
        scope_errors.append(f"concept: {e}")
        con_result = (0, 0, 0, 0, 0, 0)

    conn.close()

    # 汇总统计
    if ind_result and con_result:
        total_refreshed = ind_result[0] + con_result[0]
        total_empty = ind_result[1] + con_result[1]
        total_failed = ind_result[2] + con_result[2]
        total_deleted = ind_result[3] + con_result[3]
        total_inserted = ind_result[4] + con_result[4]
        total_time = time.time() - overall_start
        mins = int(total_time // 60)
        secs = int(total_time % 60)

        print(f"\n{'='*50}")
        print("全部映射完成：")
        print(f"  - 总板块数：{ind_result[0] + ind_result[1] + ind_result[2] + con_result[0] + con_result[1] + con_result[2]}")
        print(f"  - 成功刷新总数：{total_refreshed}")
        print(f"  - 空数据跳过总数：{total_empty}")
        print(f"  - 失败总数：{total_failed}")
        print(f"  - 删除旧记录总数：{total_deleted}")
        print(f"  - 写入新记录总数：{total_inserted}")
        print(f"  - 总耗时：{mins} 分 {secs} 秒")

        summary = {
            "status": "failed" if scope_errors or total_failed else "success",
            "refreshed": total_refreshed,
            "empty_skipped": total_empty,
            "failed": total_failed,
            "deleted": total_deleted,
            "inserted": total_inserted,
            "scope_errors": scope_errors,
        }
        if summary["status"] == "failed":
            raise RuntimeError(f"board mapping incomplete: {summary}")
        return summary


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    update_all_stock_board_map()
