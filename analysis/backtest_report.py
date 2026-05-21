"""
策略回测报告模块
基于 signal_performance 输出各策略效果统计
运行：python -m analysis.backtest_report
"""
import psycopg2
import pandas as pd
import logging
from pathlib import Path
from datetime import datetime

from data.config import DATABASE_DSN

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "backtest"


def _get_db_conn():
    if not DATABASE_DSN:
        return None
    try:
        return psycopg2.connect(DATABASE_DSN)
    except Exception as e:
        print(f"[错误] 数据库连接失败：{e}")
        return None


def _stats(df):
    """计算统计指标"""
    n = len(df)
    if n == 0:
        return {"样本数": 0}
    ret_cols = [c for c in ["return_t1", "return_t3", "return_t5"] if c in df.columns]
    stats = {"样本数": n}
    for c in ret_cols:
        s = df[c].dropna()
        if len(s) > 0:
            win_rate = (s > 0).sum() / len(s) * 100
            avg_ret = s.mean()
            stats[f"{c[-2:]}_胜率"] = f"{win_rate:.0f}%"
            stats[f"{c[-2:]}_均收益"] = f"{avg_ret:+.1f}%"
    if "max_drawdown_5d" in df.columns:
        dd = df["max_drawdown_5d"].dropna()
        if len(dd) > 0:
            stats["均最大回撤"] = f"{dd.mean():.1f}%"
    if "hit_pressure" in df.columns:
        stats["触压比例"] = f"{df['hit_pressure'].mean()*100:.0f}%"
    if "hit_invalid" in df.columns:
        stats["触失效率比例"] = f"{df['hit_invalid'].mean()*100:.0f}%"
    return stats


def generate_backtest_report():
    conn = _get_db_conn()
    if conn is None:
        return

    df = pd.read_sql("SELECT * FROM signal_performance", conn)
    conn.close()

    if df.empty:
        print("signal_performance 为空，跳过回测报告")
        return

    trade_date = datetime.now().strftime("%Y%m%d")

    lines = [f"# 策略回测报告 · {trade_date}", ""]

    # 1. 按策略
    lines.append("## 按策略统计")
    for strategy in sorted(df["strategy"].dropna().unique()):
        sdf = df[df["strategy"] == strategy]
        stats = _stats(sdf)
        lines.append(f"### {strategy}")
        for k, v in stats.items():
            lines.append(f"- {k}：{v}")
        lines.append("")

    # 2. 按风险等级
    lines.append("## 按风险等级统计")
    for level in sorted(df["risk_level"].dropna().unique()) if "risk_level" in df.columns else []:
        sdf = df[df["risk_level"] == level]
        stats = _stats(sdf)
        lines.append(f"### 风险{level}")
        for k, v in stats.items():
            lines.append(f"- {k}：{v}")
        lines.append("")

    # 3. 按操作信号
    lines.append("## 按操作信号统计")
    for sig in sorted(df["action_signal"].dropna().unique()) if "action_signal" in df.columns else []:
        sdf = df[df["action_signal"] == sig]
        stats = _stats(sdf)
        lines.append(f"### {sig}")
        for k, v in stats.items():
            lines.append(f"- {k}：{v}")
        lines.append("")

    lines.append("---")
    lines.append("> 本报告基于历史数据统计，不构成投资建议。过去表现不代表未来收益。")

    report = "\n".join(lines)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"weekly_strategy_report_{trade_date}.md"
    path.write_text(report, encoding="utf-8")
    print(f"回测报告已保存：{path}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    generate_backtest_report()


if __name__ == "__main__":
    main()
