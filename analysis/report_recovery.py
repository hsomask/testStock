"""Recover a missing daily report from immutable signal snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2

from analysis.evaluation_report_reader import (
    load_correction_effectiveness_summary,
    load_t1_evaluation_summary,
)
from analysis.report_renderer import (
    append_compact_evaluation_section,
    append_evaluation_section,
)
from analysis.trade_calendar import normalize_trade_date
from data.config import DATABASE_DSN, REPORT_DIR


DAILY_DIR = Path(REPORT_DIR) / "daily"


def _sql_date(date_text):
    return f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"


def _load_snapshot_rows(conn, date_text):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.signal_id,c.source_run_id,c.code,c.name,c.strategy,
               c.canonical_final_layer,c.primary_direction,c.market_status,
               c.market_score,c.trade_mode,c.position_cap,c.sentiment_score,
               c.sentiment_stage,c.data_confidence,c.close_price,c.pct_chg,
               c.risk_level,c.action_signal,c.entry_reason,c.risk_reasons,
               c.observe_low,c.observe_high,c.pressure_price,c.invalid_price,
               c.feature_json
        FROM candidate_feature_snapshot c
        WHERE c.trade_date=%s
        ORDER BY c.canonical_final_layer,c.strategy,c.code
        """,
        (_sql_date(date_text),),
    )
    columns = [item[0] for item in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def _fmt(value, digits=2):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _snapshot_plan(row):
    feature = row.get("feature_json") or {}
    if isinstance(feature, str):
        try:
            feature = json.loads(feature)
        except Exception:
            feature = {}
    plan = feature.get("plan") or {}
    return {**row, **plan}


def _group_plans(rows):
    grouped = {"候选低吸": [], "只观察": [], "高风险回避": []}
    seen = set()
    for raw in rows:
        item = _snapshot_plan(raw)
        key = (item.get("code"), item.get("strategy"))
        if key in seen:
            continue
        seen.add(key)
        layer = item.get("final_layer") or item.get("canonical_final_layer")
        if layer == "候选低吸":
            target = "候选低吸"
        elif layer == "只观察":
            target = "只观察"
        else:
            target = "高风险回避"
        grouped[target].append(item)
    return grouped


def render_recovery_bundle(date_text, rows, t1_data):
    """Build a transparent recovery main report and immutable audit appendix."""
    if not rows:
        raise RuntimeError(f"candidate snapshots are missing for {date_text}")
    context = rows[0]
    plans = _group_plans(rows)
    directions = []
    for row in rows:
        name = str(row.get("primary_direction") or "").strip()
        if name and name not in directions:
            directions.append(name)
    date_display = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"
    market_status = context.get("market_status") or "待确认"
    market_score = _fmt(context.get("market_score"), 1)
    sentiment_stage = context.get("sentiment_stage") or "待确认"
    sentiment_score = _fmt(context.get("sentiment_score"), 1)
    position_cap = _fmt(context.get("position_cap"), 0)
    confidence = _fmt(context.get("data_confidence"), 0)
    source_runs = sorted({str(row.get("source_run_id")) for row in rows if row.get("source_run_id")})

    main = [
        "---", f"date: {date_display}", "recovery_mode: immutable_snapshot",
        f"market_status: {market_status}", f"market_score: {market_score}",
        f"sentiment_stage: {sentiment_stage}", f"position_cap: {position_cap}成",
        f"data_confidence: {confidence}", "---", "",
        f"# A股收盘复盘与次日计划｜{date_display}", "",
        "## 0. 收盘后先看结论", "",
        "> **本报告由当日不可变候选快照恢复，未重新运行选股。**", "",
        f"- 市场状态：{market_status}（{market_score}分）",
        f"- 短线情绪：{sentiment_stage}（{sentiment_score}分）",
        f"- 仓位上限：{position_cap}成",
        f"- 主要方向：{'、'.join(directions[:5]) or '快照未记录明确方向'}",
        f"- 快照候选：{len(rows)}条，数据可信度 {confidence}/100", "",
        "## 今日复盘", "",
        "- 信号、最终分层和交易区间均取自当日持久化快照。",
        "- 全市场宽度及板块排名无法从候选快照完整还原，不在恢复报告中补写。",
        "- 恢复过程不写入或覆盖 `stock_signal` 与候选快照。", "",
    ]
    append_compact_evaluation_section(main, t1_data)
    main.extend(["## 2. 次日操作计划", ""])
    for title, key in (("满足条件才考虑", "候选低吸"), ("只观察", "只观察"), ("明确回避", "高风险回避")):
        main.extend([f"### {title}", ""])
        items = plans[key]
        if not items:
            main.extend(["暂无。", ""])
            continue
        main.extend(["| 股票 | 策略 | 参考区间 | 失效条件 | 原因 |", "|---|---|---|---|---|"])
        for item in items[:10]:
            zone = f"{_fmt(item.get('observe_low'))}～{_fmt(item.get('observe_high'))}"
            reason = str(item.get("display_reason") or item.get("reason") or item.get("entry_reason") or "-").replace("|", "/").replace("\n", "；")
            main.append(
                f"| {item.get('name') or item.get('code')} | {item.get('strategy') or '-'} | "
                f"{zone} | {_fmt(item.get('invalid_price'))} | {reason[:80]} |"
            )
        main.append("")
    main.extend([
        "## 3. 次日只验证三件事", "",
        "1. 快照记录的主要方向是否继续获得承接。",
        "2. 候选是否进入参考区间并满足原始触发条件。",
        "3. 任一候选触及失效价格时，原计划立即作废。", "",
        "## 4. 执行纪律", "",
        "> 不因报告恢复而追加新候选；只执行当日快照中已经存在的计划。", "",
        "## 5. 数据状态", "",
        f"- 恢复来源：candidate_feature_snapshot（{len(rows)}条）",
        f"- 原始运行：{', '.join(source_runs) or '未记录'}",
        f"- 完整审计明细：[查看附录](daily_report_{date_text}_appendix.md)", "",
        "---", "", "本报告仅用于数据复盘和学习，不构成任何投资建议。",
    ])

    appendix = [
        "---", f"date: {date_display}", "recovery_mode: immutable_snapshot_audit", "---", "",
        f"# A股日报恢复审计附录｜{date_display}", "",
        "> 本附录由当日持久化信号快照恢复；没有重跑选股，也没有使用事后行情修改候选。", "",
        "## 1. 昨日观察池兑现复盘（T+1）", "",
    ]
    eval_lines = []
    append_evaluation_section(eval_lines, t1_data)
    appendix = appendix[:-2] + eval_lines + ["## 2. 市场与交易环境", ""]
    appendix.extend([
        f"- 市场状态：{market_status}", f"- 市场评分：{market_score}",
        f"- 情绪阶段：{sentiment_stage}", f"- 情绪评分：{sentiment_score}",
        f"- 数据可信度：{confidence}",
        "- 限制：候选快照不保存完整市场宽度，相关指标不作恢复。", "",
        "## 3. 不可变候选快照", "",
        "| signal_id | 股票 | 策略 | 最终层级 | 主方向 | 收盘价 | 涨幅 | 观察区间 | 失效价 |",
        "|---|---|---|---|---|---:|---:|---|---:|",
    ])
    for row in rows:
        item = _snapshot_plan(row)
        appendix.append(
            f"| {row.get('signal_id') or '-'} | {row.get('name') or row.get('code')} | "
            f"{row.get('strategy') or '-'} | {row.get('canonical_final_layer') or '-'} | "
            f"{row.get('primary_direction') or '-'} | {_fmt(row.get('close_price'))} | "
            f"{_fmt(row.get('pct_chg'))}% | {_fmt(row.get('observe_low'))}～{_fmt(row.get('observe_high'))} | "
            f"{_fmt(row.get('invalid_price'))} |"
        )
    appendix.extend(["", "## 4. 恢复审计", "", f"- 快照行数：{len(rows)}", f"- 原始运行ID：{', '.join(source_runs) or '未记录'}", "- 信号表写入：0", "- 快照表写入：0", ""])
    return "\n".join(main), "\n".join(appendix)


def recover_missing_report(trade_date, *, conn=None):
    date_text = normalize_trade_date(trade_date)
    own_conn = conn is None
    db = conn or psycopg2.connect(DATABASE_DSN)
    try:
        rows = _load_snapshot_rows(db, date_text)
        t1_data = load_t1_evaluation_summary(date_text)
        t1_data["correction_effectiveness"] = load_correction_effectiveness_summary(date_text)
        main, appendix = render_recovery_bundle(date_text, rows, t1_data)
        cur = db.cursor()
        cur.execute(
            """
            INSERT INTO daily_report (trade_date,report_mode,report_type,content,confidence_score,created_at)
            VALUES (%s,'unified','daily',%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT (trade_date,report_mode,report_type) DO UPDATE SET
              content=EXCLUDED.content,confidence_score=EXCLUDED.confidence_score,
              created_at=CURRENT_TIMESTAMP
            """,
            (_sql_date(date_text), main, rows[0].get("data_confidence")),
        )
        cur.close()
        db.commit()
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        main_path = DAILY_DIR / f"daily_report_{date_text}.md"
        appendix_path = DAILY_DIR / f"daily_report_{date_text}_appendix.md"
        main_path.write_text(main, encoding="utf-8")
        appendix_path.write_text(appendix, encoding="utf-8")
        return {
            "status": "success", "trade_date": date_text, "mode": "snapshot_recovery",
            "snapshot_count": len(rows), "report_path": str(main_path),
            "appendix_path": str(appendix_path), "signal_tables_touched": [],
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if own_conn:
            db.close()


def main():
    parser = argparse.ArgumentParser(description="Recover missing daily report from immutable snapshots")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    print(json.dumps(recover_missing_report(args.date), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
