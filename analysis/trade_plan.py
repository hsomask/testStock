"""
交易计划模块
根据市场环境和个股条件生成条件化明日计划
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily"


def _market_restrictions(market_result, quality):
    """根据市场环境返回交易限制"""
    score = market_result.get("score", 50)
    status = market_result.get("status", "")
    limit_down = market_result.get("limit_down", 0)
    up_count = market_result.get("up_count", 0)
    down_count = market_result.get("down_count", 0)
    confidence = quality.get("confidence_score", 0)

    restrictions = {
        "allow_real_trade": True,
        "max_position_pct": 5,  # 总仓位上限，成数
        "single_stock_pct": 1,  # 单票仓位
        "reasons": [],
    }

    if confidence < 70:
        restrictions["allow_real_trade"] = False
        restrictions["reasons"].append(f"可信度{confidence}<70，仅生成观察计划")

    if limit_down > 50:
        restrictions["allow_real_trade"] = False
        restrictions["reasons"].append(f"跌停{limit_down}只>50，禁止追高")

    if down_count > up_count * 2:
        restrictions["max_position_pct"] = 1
        restrictions["reasons"].append(f"下跌{down_count}只超上涨{up_count}只2倍，仓位上限1成")

    if down_count > up_count:
        old = restrictions["max_position_pct"]
        restrictions["max_position_pct"] = min(old, 3)
        if old > 3:
            restrictions["reasons"].append(f"下跌{down_count}只多于上涨{up_count}只，市场分化，仓位上限降至3成")

    if score < 45:
        restrictions["allow_real_trade"] = False
        restrictions["max_position_pct"] = 0
        restrictions["reasons"].append(f"市场评分{score}<45，空仓或模拟")

    if status in ("退潮", "冰点"):
        restrictions["allow_real_trade"] = False
        restrictions["reasons"].append(f"市场{status}，不生成买入计划")

    return restrictions


def _classify_stock(row):
    """分类单只股票"""
    action = str(row.get("action_signal", ""))
    risk = str(row.get("risk_level", ""))
    pct_20d = row.get("pct_20d", np.nan)
    pct_5d = row.get("pct_5d", np.nan)
    vr = row.get("volume_ratio", np.nan)
    turnover = row.get("turnover", np.nan)

    # 获取今日涨幅
    today_pct = row.get("pct_chg", np.nan)

    # 0. 滚雪球趋势 + 可信度 < 70 → 强制只观察
    # （strategy 从 row 传入，无法在此函数参数中获取，由调用方传入）
    # 此逻辑在 generate_trade_plan 中处理

    # 1. 高风险回避（仅 signal/risk 触发）
    if action == "回避" or risk == "高":
        return "高风险回避", "信号/风险等级预警"

    # 2. 交易条件不满足
    trade_issues = []
    if pd.notna(pct_20d) and pct_20d >= 80:
        trade_issues.append(f"20日涨幅{pct_20d:.0f}%≥80%")
    if pd.notna(pct_5d) and pct_5d >= 30:
        trade_issues.append(f"5日涨幅{pct_5d:.0f}%≥30%")
    if pd.notna(vr) and vr >= 10:
        trade_issues.append(f"量比{vr:.1f}≥10")
    if pd.notna(turnover) and turnover >= 30:
        trade_issues.append(f"换手率{turnover:.0f}%≥30")
    # 接近涨停判断：20cm板(300/301/688)用19%，主板用9.5%
    is_20cm = str(row.get("code", "")).startswith(("300", "301", "688"))
    limit_like = 19 if is_20cm else 9.5
    if pd.notna(today_pct) and today_pct >= limit_like:
        trade_issues.append(f"今日涨幅{today_pct:.1f}%接近涨停，不适合作为低吸候选")

    if trade_issues:
        return "交易条件不满足", "；".join(trade_issues)

    # 3. 关键指标缺失 → 只能观察
    has_ma5 = pd.notna(row.get("ma5"))
    has_ma20 = pd.notna(row.get("ma20"))
    has_pct_5d = pd.notna(pct_5d)
    has_pct_20d = pd.notna(pct_20d)
    has_vr = pd.notna(vr)
    has_to = pd.notna(turnover)

    if not ((has_ma5 or has_ma20) and has_pct_5d and has_pct_20d and has_vr and has_to):
        return "只观察", "关键指标缺失，只能观察"

    # 4. 候选低吸
    if (action == "观察" and risk in ("低", "中")
            and pct_20d < 50 and pct_5d < 20 and vr < 6 and turnover < 25):
        return "候选低吸", "满足全部低吸条件"

    # 5. 其他
    return "只观察", "部分条件不满足，继续观察"


def _gen_entry_notes():
    """生成买点条件文字"""
    return (
        "1. 只在回踩观察区间下沿附近考虑；"
        "2. 不追高开过多（开盘涨幅不超过3%）；"
        "3. 不跌破风险失效位；"
        "4. 所属板块不能明显走弱；"
        "5. 大盘不能继续恶化。"
    )


def _load_strategy_feedback():
    try:
        from analysis.strategy_feedback import load_latest_strategy_feedback
        return load_latest_strategy_feedback(window_days=20)
    except Exception:
        return {}


def _fmt_feedback_pct(value):
    try:
        if value is None or pd.isna(value):
            return "-"
        return f"{float(value):.1%}"
    except Exception:
        return "-"


def _apply_strategy_feedback_downgrade(category, reason, strategy, feedback_map):
    feedback = feedback_map.get(strategy) or {}
    status = feedback.get("status")
    if status not in ("weak", "blocked"):
        return category, reason, feedback

    sample = feedback.get("sample_count") or 0
    win_rate = _fmt_feedback_pct(feedback.get("win_rate_1d"))
    failed_rate = _fmt_feedback_pct(feedback.get("failed_rate"))
    feedback_reason = feedback.get("reason") or "策略近期反馈偏弱"
    note = f"策略反馈降级：近20日样本{sample}，胜率{win_rate}，失败率{failed_rate}，{feedback_reason}"

    if status == "weak" and category == "候选低吸":
        return "只观察", f"{reason}；{note}", feedback
    if status == "blocked" and category in ("候选低吸", "只观察"):
        return "交易条件不满足", f"{reason}；{note}", feedback
    return category, reason, feedback


def generate_trade_plan(trade_date, market_result, quality, themes,
                         filtered_result, excluded_result):
    """生成交易计划"""
    restrictions = _market_restrictions(market_result, quality)
    strategy_feedback = _load_strategy_feedback()

    plans = {
        "候选低吸": [],
        "只观察": [],
        "交易条件不满足": [],
        "高风险回避": [],
        "不可交易过滤": [],
    }

    # 不可交易过滤
    for ex in excluded_result:
        plans["不可交易过滤"].append({
            "code": ex["code"],
            "name": ex["name"],
            "strategy": ex["strategy"],
            "reason": ex["exclude_reason"],
        })

    # 分类每只股票
    for pool_name, pool_df in filtered_result.items():
        if pool_df is None or pool_df.empty:
            continue
        for _, row in pool_df.iterrows():
            code = str(row.get("code", ""))
            name = str(row.get("name", ""))
            category, reason = _classify_stock(row)
            category, reason, feedback = _apply_strategy_feedback_downgrade(
                category, reason, pool_name, strategy_feedback
            )
            # 滚雪球趋势 + 可信度 < 70 → 强制只观察
            if pool_name == "滚雪球趋势" and quality.get("confidence_score", 0) < 70 and category == "候选低吸":
                category = "只观察"
                reason = "报告可信度低于70，只观察，不生成候选低吸"
            close = row.get("close", np.nan)
            plans[category].append({
                "code": code,
                "name": name,
                "strategy": pool_name,
                "close": round(float(close), 2) if pd.notna(close) else None,
                "pct_chg": round(float(row.get("pct_chg", 0)), 2) if pd.notna(row.get("pct_chg")) else None,
                "risk_level": str(row.get("risk_level", "")),
                "action_signal": str(row.get("action_signal", "")),
                "observe_low": round(float(row["observe_low"]), 2) if pd.notna(row.get("observe_low")) else None,
                "observe_high": round(float(row["observe_high"]), 2) if pd.notna(row.get("observe_high")) else None,
                "pressure_price": round(float(row["pressure_price"]), 2) if pd.notna(row.get("pressure_price")) else None,
                "invalid_price": round(float(row["invalid_price"]), 2) if pd.notna(row.get("invalid_price")) else None,
                "reason": reason,
                "feedback_status": feedback.get("status"),
                "feedback_score": feedback.get("feedback_score"),
                "feedback_reason": feedback.get("reason"),
            })

    # 组装输出
    trade_plan = {
        "trade_date": trade_date,
        "generated_at": datetime.now().isoformat(),
        "market_snapshot": {
            "market_score": market_result.get("score"),
            "market_status": market_result.get("status"),
            "confidence_score": quality.get("confidence_score"),
            "up_count": market_result.get("up_count"),
            "down_count": market_result.get("down_count"),
            "limit_up": market_result.get("limit_up"),
            "limit_down": market_result.get("limit_down"),
            "sentiment_stage": market_result.get("status", ""),
        },
        "market_restrictions": restrictions,
        "entry_notes": _gen_entry_notes(),
        "plans": plans,
        "summary": {
            "候选低吸": len(plans["候选低吸"]),
            "只观察": len(plans["只观察"]),
            "交易条件不满足": len(plans["交易条件不满足"]),
            "高风险回避": len(plans["高风险回避"]),
            "不可交易过滤": len(plans["不可交易过滤"]),
        },
    }

    return trade_plan


def save_trade_plan(trade_plan, trade_date):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = REPORTS_DIR / f"trade_plan_{trade_date}.json"
    json_path.write_text(json.dumps(trade_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"交易计划已保存：{json_path}")

    # Markdown
    md_path = REPORTS_DIR / f"trade_plan_{trade_date}.md"
    md_text = _render_trade_plan_md(trade_plan)
    md_path.write_text(md_text, encoding="utf-8")
    print(f"交易计划已保存：{md_path}")

    return trade_plan


def _render_trade_plan_md(tp):
    """渲染交易计划 Markdown"""
    lines = [f"# 明日交易计划 · {tp['trade_date']}", ""]

    # 市场限制
    r = tp["market_restrictions"]
    lines.append("## 市场环境限制")
    lines.append(f"- 是否允许实盘：{'是' if r['allow_real_trade'] else '否（仅模拟观察）'}")
    lines.append(f"- 总仓位上限：{r['max_position_pct']}成")
    lines.append(f"- 单票仓位：{r['single_stock_pct']}成")
    for reason in r["reasons"]:
        lines.append(f"  - {reason}")
    lines.append("")

    # 买点条件
    lines.append("## 买点条件")
    lines.append(tp["entry_notes"])
    lines.append("")

    # 各分类
    for category, stocks in tp["plans"].items():
        lines.append(f"## {category}（{len(stocks)}只）")
        if not stocks:
            lines.append("暂无")
        else:
            for s in stocks:
                lines.append(f"- **{s['name']}**（{s['code']}）")
                lines.append(f"  策略：{s['strategy']} | 收盘：{s.get('close','-')} | 涨幅：{s.get('pct_chg','-')}%")
                lines.append(f"  风险：{s.get('risk_level','-')} | 信号：{s.get('action_signal','-')}")
                if s.get("observe_low") and s.get("observe_high"):
                    lines.append(f"  观察区间：{s['observe_low']}~{s['observe_high']} | 压力位：{s.get('pressure_price','-')} | 失效位：{s.get('invalid_price','-')}")
                lines.append(f"  原因：{s['reason']}")
                lines.append("")
        lines.append("")

    # 汇总
    lines.append("## 汇总")
    for k, v in tp["summary"].items():
        lines.append(f"- {k}：{v}只")
    lines.append("")
    lines.append("> 本计划仅用于辅助决策，不构成投资建议。市场有风险，投资需谨慎。")

    return "\n".join(lines)
