"""
部署前环境检查
运行：python -m analysis.preflight_check
Docker：docker compose run --rm --entrypoint "" stock-report python -m analysis.preflight_check
"""
import os
import time
import logging
from pathlib import Path

import psycopg2

from data.config import (
    DATABASE_DSN,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_TO,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
REQUIRED_TABLES = [
    "board_amount_ratio",
    "stock_board_map",
    "daily_report",
    "data_quality_log",
    "stock_signal",
    "job_run_log",
]

results = []


def ok(msg):
    results.append(("OK", msg))
    print(f"  [OK] {msg}")


def warn(msg):
    results.append(("WARN", msg))
    print(f"  [WARN] {msg}")


def fail(msg):
    results.append(("FAIL", msg))
    print(f"  [FAIL] {msg}")


def check_database_dsn():
    print("\n1. DATABASE_DSN")
    if DATABASE_DSN:
        ok(f"DATABASE_DSN 已配置")
    else:
        fail("DATABASE_DSN 未设置")


def check_db_connection():
    print("\n2. 数据库连接")
    if not DATABASE_DSN:
        fail("跳过（DATABASE_DSN 未配置）")
        return None
    try:
        conn = psycopg2.connect(DATABASE_DSN)
        ok("数据库连接成功")
        return conn
    except Exception as e:
        fail(f"数据库连接失败：{e}")
        return None


def check_tables(conn):
    print("\n3. 必要表检查")
    if conn is None:
        fail("跳过（无数据库连接）")
        return
    cur = conn.cursor()
    all_ok = True
    for table in REQUIRED_TABLES:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)",
            (table,)
        )
        if cur.fetchone()[0]:
            ok(f"表 {table} 存在")
        else:
            warn(f"表 {table} 不存在（可运行 init_db 创建）")
            all_ok = False
    cur.close()


def check_stock_board_map(conn):
    print("\n4. stock_board_map 数据")
    if conn is None:
        fail("跳过（无数据库连接）")
        return
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM stock_board_map")
        count = cur.fetchone()[0]
        cur.close()
        if count > 0:
            ok(f"stock_board_map 有 {count} 条记录")
        else:
            warn("stock_board_map 为空，请运行 stock_board_mapper")
    except Exception as e:
        warn(f"检查失败：{e}")


def check_smtp():
    print("\n5. SMTP 邮件配置")
    missing = []
    if not SMTP_HOST:
        missing.append("SMTP_HOST")
    if not SMTP_USER:
        missing.append("SMTP_USER")
    if not SMTP_PASSWORD:
        missing.append("SMTP_PASSWORD")
    if not EMAIL_TO:
        missing.append("EMAIL_TO")
    if missing:
        warn(f"SMTP 配置不完整，缺少：{', '.join(missing)}")
    else:
        ok(f"SMTP 配置完整（{SMTP_HOST}:{SMTP_PORT}，{SMTP_USER} → {EMAIL_TO}）")


def check_dirs():
    print("\n6. 目录可写检查")
    for name in ["reports", "logs"]:
        d = BASE_DIR / name
        if d.exists():
            test_file = d / ".write_test"
            try:
                test_file.write_text("test")
                test_file.unlink()
                ok(f"{name}/ 可写")
            except Exception:
                warn(f"{name}/ 不可写")
        else:
            warn(f"{name}/ 不存在")


def check_timezone():
    print("\n7. 时区检查")
    tz = time.tzname[0] if hasattr(time, 'tzname') else os.environ.get("TZ", "unknown")
    if "Asia/Shanghai" in os.environ.get("TZ", "") or "CST" in str(tz):
        ok(f"时区：{os.environ.get('TZ', tz)}")
    else:
        warn(f"时区：{tz}，建议设置 TZ=Asia/Shanghai")


def check_akshare():
    print("\n8. AkShare 连通性")
    try:
        import requests
        for k in list(os.environ.keys()):
            if 'proxy' in k.lower():
                del os.environ[k]
        s = requests.Session()
        s.trust_env = False
        s.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        })
        r = s.get(
            "https://push2delay.eastmoney.com/api/qt/clist/get",
            params={"pn": "1", "pz": "1", "po": "1", "np": "1", "fltt": "2", "invt": "2",
                    "fid": "f3", "fs": "m:0+t:6", "fields": "f12,f14"},
            timeout=15
        )
        data = r.json()
        if data.get("data", {}).get("total", 0) > 0:
            ok(f"东方财富 push2delay 连通，返回 {data['data']['total']} 只股票")
        else:
            warn("东方财富 push2delay 返回空数据")

        # Also test sina
        r2 = s.get("https://hq.sinajs.cn/list=sh600000", timeout=10)
        if "var hq_str" in r2.text:
            ok("新浪 hq.sinajs.cn 连通")
        else:
            warn("新浪 hq.sinajs.cn 返回异常")
    except Exception as e:
        fail(f"AkShare 基础连通性测试失败：{e}")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print("=== 部署前环境检查 ===\n")

    check_database_dsn()
    conn = check_db_connection()
    check_tables(conn)
    check_stock_board_map(conn)
    if conn:
        try:
            conn.close()
        except Exception:
            pass
    check_smtp()
    check_dirs()
    check_timezone()
    check_akshare()

    # 汇总
    ok_count = sum(1 for r in results if r[0] == "OK")
    warn_count = sum(1 for r in results if r[0] == "WARN")
    fail_count = sum(1 for r in results if r[0] == "FAIL")

    print(f"\n=== 检查完成：{ok_count} OK / {warn_count} WARN / {fail_count} FAIL ===\n")

    if fail_count > 0:
        print("请修复 FAIL 项后再运行日报。")
    elif warn_count > 0:
        print("WARN 项不影响基本运行，但建议修复以获得完整功能。")
    else:
        print("所有检查通过，环境就绪。")


if __name__ == "__main__":
    main()
