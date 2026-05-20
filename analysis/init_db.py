"""
初始化数据库表
运行：python -m analysis.init_db
"""
import psycopg2
import logging
from pathlib import Path

from data.config import DATABASE_DSN

logger = logging.getLogger(__name__)

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"

TABLES = [
    "board_amount_ratio",
    "stock_board_map",
    "daily_report",
    "data_quality_log",
    "stock_signal",
    "job_run_log",
    "stock_hist_kline",
]


def init_database():
    if not DATABASE_DSN:
        print("[错误] DATABASE_DSN 未设置，无法初始化数据库")
        print("请在 .env 文件中设置 DATABASE_DSN=postgresql://user:pass@host:port/dbname")
        return

    print(f"数据库地址：{DATABASE_DSN}")

    if not SCHEMA_SQL.exists():
        print(f"[错误] 未找到建表脚本：{SCHEMA_SQL}")
        return

    sql_content = SCHEMA_SQL.read_text(encoding="utf-8")

    conn = psycopg2.connect(DATABASE_DSN)
    cur = conn.cursor()

    try:
        cur.execute(sql_content)
        conn.commit()
        print("建表 SQL 执行完成")
    except Exception as e:
        conn.rollback()
        print(f"[错误] 建表失败：{e}")
        cur.close()
        conn.close()
        return

    # 验证表是否创建成功
    for table in TABLES:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)",
            (table,)
        )
        exists = cur.fetchone()[0]
        status = "已就绪" if exists else "未创建"
        print(f"  {table}: {status}")

    cur.close()
    conn.close()
    print("数据库初始化完成")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    init_database()
