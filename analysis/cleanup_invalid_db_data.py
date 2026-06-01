"""
数据库非交易日数据清理工具
  dry-run: python -m analysis.cleanup_invalid_db_data --date 20260523 --dry-run
  apply:   python -m analysis.cleanup_invalid_db_data --date 20260523 --apply

清理流程：先备份到 _quarantine 表，确认成功后再删除原表污染行。
每张表在独立事务中执行，任一步失败即 rollback，不删除数据。
"""
import argparse
import logging
import sys

import psycopg2

from data.config import DATABASE_DSN
from analysis.data_fetcher import is_trade_day

logger = logging.getLogger(__name__)

CLEANUP_TABLES = [
    "stock_signal",
    "board_amount_ratio",
    "pipeline_job_log",
    "signal_tracker",
    "signal_performance",
    "backtest_result",
]


def date_to_sql(date_str):
    """YYYYMMDD → YYYY-MM-DD"""
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def get_db_conn():
    if not DATABASE_DSN:
        return None
    return psycopg2.connect(DATABASE_DSN)


def table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return cur.fetchone()[0]


def has_trade_date_column(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = 'trade_date')",
        (table_name,),
    )
    return cur.fetchone()[0]


def source_columns(cur, table_name):
    """返回源表的所有列名（按序）"""
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
        (table_name,),
    )
    return [row[0] for row in cur.fetchall()]


def count_invalid_rows(cur, table_name, sql_date):
    cur.execute(
        f'SELECT COUNT(*) FROM "{table_name}" WHERE trade_date = %s',
        (sql_date,),
    )
    return cur.fetchone()[0]


def ensure_quarantine_table(conn, cur, table_name):
    """确保 quarantine 表存在，不存在则按源表结构创建并补充元信息列"""
    quarantine_name = f"{table_name}_quarantine"
    if table_exists(cur, quarantine_name):
        return quarantine_name

    cols = source_columns(cur, table_name)
    col_list = ", ".join(f'"{c}"' for c in cols)

    cur.execute(
        f'CREATE TABLE "{quarantine_name}" AS SELECT {col_list} FROM "{table_name}" WHERE 1=0'
    )

    for meta_col, meta_type in [
        ("quarantined_at", "TIMESTAMP DEFAULT now()"),
        ("quarantine_reason", "TEXT"),
    ]:
        try:
            cur.execute(
                f'ALTER TABLE "{quarantine_name}" ADD COLUMN IF NOT EXISTS {meta_col} {meta_type}'
            )
        except Exception:
            pass

    conn.commit()
    logger.info(f"创建 quarantine 表: {quarantine_name}")
    return quarantine_name


def cleanup_table(conn, table_name, sql_date, date_str, reason, dry_run):
    """对单表执行清理（dry-run 或 apply）"""
    cur = conn.cursor()

    try:
        row_count = count_invalid_rows(cur, table_name, sql_date)
    except Exception as e:
        print(f"  [SKIP] {table_name} 查询失败: {e}")
        cur.close()
        return

    if row_count == 0:
        print(f"  [SKIP] {table_name} trade_date={date_str} rows=0")
        cur.close()
        return

    if dry_run:
        print(f"  [DRY-RUN] {table_name} trade_date={date_str} rows={row_count}")
        cur.close()
        return

    # ── apply 模式 ──
    quarantine_name = ensure_quarantine_table(conn, cur, table_name)

    # 动态拼接列名
    src_cols = source_columns(cur, table_name)
    src_col_list = ", ".join(f'"{c}"' for c in src_cols)
    q_col_list = src_col_list + ', "quarantined_at", "quarantine_reason"'

    try:
        # 1. 备份到 quarantine
        insert_sql = (
            f'INSERT INTO "{quarantine_name}" ({q_col_list}) '
            f'SELECT {src_col_list}, now(), %s FROM "{table_name}" WHERE trade_date = %s'
        )
        cur.execute(insert_sql, (reason, sql_date))
        quarantined = cur.rowcount

        if quarantined != row_count:
            raise RuntimeError(
                f"quarantine 行数不匹配：预期 {row_count}，实际 {quarantined}"
            )

        # 2. 删除原表污染行
        cur.execute(
            f'DELETE FROM "{table_name}" WHERE trade_date = %s',
            (sql_date,),
        )
        deleted = cur.rowcount

        if deleted != row_count:
            raise RuntimeError(
                f"delete 行数不匹配：预期 {row_count}，实际 {deleted}"
            )

        conn.commit()
        print(f"  [OK] {table_name} trade_date={date_str} quarantined={quarantined} deleted={deleted}")

    except Exception as e:
        conn.rollback()
        print(f"  [FAIL] {table_name} trade_date={date_str}: {e}")
    finally:
        cur.close()


def find_candidates(conn, date_str):
    """扫描各表，返回候选列表"""
    sql_date = date_to_sql(date_str)
    cur = conn.cursor()
    candidates = []

    for table_name in CLEANUP_TABLES:
        if not table_exists(cur, table_name):
            continue
        if not has_trade_date_column(cur, table_name):
            continue
        try:
            count = count_invalid_rows(cur, table_name, sql_date)
        except Exception:
            continue
        if count > 0:
            candidates.append({"table": table_name, "trade_date": date_str, "rows": count})

    cur.close()
    return candidates


def main():
    parser = argparse.ArgumentParser(description="数据库非交易日数据清理")
    parser.add_argument("--date", type=str, required=True, help="清理日期 YYYYMMDD")
    parser.add_argument("--dry-run", action="store_true", default=True, help="仅预览（默认）")
    parser.add_argument("--apply", action="store_true", default=False, help="执行清理（备份→删除）")
    args = parser.parse_args()

    trade_date = args.date
    sql_date = date_to_sql(trade_date)

    # ── 安全检查 1：交易日禁止清理 ──
    if is_trade_day(trade_date):
        print(f"[SAFE STOP] {trade_date} 是交易日，不允许自动清理")
        return

    # ── 安全检查 2：apply 不允许没有 date（argparse 已保证） ──
    # argparse --date required=True，所以这里必然有 date

    print(f"=== 数据库清理（{trade_date}）===")
    if not args.apply:
        print("模式: dry-run\n")
    else:
        print("模式: apply（备份 → 删除）\n")

    if not DATABASE_DSN:
        print("[ERROR] DATABASE_DSN 未配置，无法连接数据库")
        sys.exit(1)

    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"[ERROR] 数据库连接失败: {e}")
        sys.exit(1)

    try:
        candidates = find_candidates(conn, trade_date)
    except Exception as e:
        print(f"[ERROR] 扫描过程出错: {e}")
        conn.close()
        sys.exit(1)

    if not candidates:
        print(f"日期 {trade_date} 在各表中无数据，无需清理")
        conn.close()
        return

    print(f"发现 {len(candidates)} 个表中有非交易日数据:\n")

    total_rows = sum(c["rows"] for c in candidates)
    reason = f"非交易日污染清理 {trade_date}"

    for c in candidates:
        cleanup_table(
            conn,
            c["table"],
            sql_date,
            trade_date,
            reason,
            dry_run=not args.apply,
        )

    conn.close()

    if args.apply:
        print(f"\n=== 清理完成 ===")
        print(f"处理 {len(candidates)} 表，共 {total_rows} 行已备份并删除")
    else:
        print(f"\n合计: {len(candidates)} 表, {total_rows} 行")
        print("使用 --apply 执行清理")


if __name__ == "__main__":
    main()
