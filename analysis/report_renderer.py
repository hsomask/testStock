"""
日报渲染模块 — 统一主日报模板
"""
import requests
from pathlib import Path
import pandas as pd
import numpy as np

from analysis.utils import fmt_num, fmt_pct, fmt_yi
from analysis.explainer import explain_market_status
from analysis.board_alias import normalize_board_name
from analysis.report_insights import (
    check_weak_market, weak_market_conclusion,
    assess_profit_effect, compute_market_width,
    assess_trading_environment, assign_pattern_tag,
    generate_validation_checklist, explain_sentiment_stage,
    validate_position_consistency,
    filter_effective_themes, is_dynamic_label,
)
from data.config import MINIMAX_API_KEY, MINIMAX_API_URL


def _get_context_section(report_context, name):
    if not isinstance(report_context, dict):
        return {}
    s = report_context.get(name) or {}
    return s if isinstance(s, dict) else {}


# ── MiniMax AI ──

def call_minimax(prompt):
    if not MINIMAX_API_KEY:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "abab6.5s-chat",
            "messages": [
                {"role": "system", "content": "你是一名经验丰富的A股交易员和分析师，擅长用简洁、专业的语言总结市场情况和策略建议。你的分析基于数据，不构成投资建议。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7, "max_tokens": 2000,
        }
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=30)
        data = resp.json()
        if data.get("base_resp", {}).get("status_code") == 0:
            return data["choices"][0]["message"]["content"]
        return None
    except Exception:
        return None


# ── 板块表格渲染（保持不变）──

def render_board_table(df, max_rows=10):
    if df is None or df.empty:
        return "暂无数据\n"
    seen = set()
    deduped = []
    for _, row in df.iterrows():
        key = (row.get("pct_chg", np.nan), row.get("turnover", np.nan), str(row.get("leader", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= max_rows:
            break
    lines = []
    for row in deduped:
        name = normalize_board_name(row.get("board_name", "-"))
        pct = fmt_pct(row.get("pct_chg", np.nan))
        turnover = row.get("turnover", np.nan)
        leader = row.get("leader", "-")
        leader_pct = row.get("leader_pct_chg", np.nan)
        lines.append(f"| {name} | {pct} | 换手{fmt_num(turnover, 2)} | {leader} {fmt_pct(leader_pct)} |")
    return "\n".join(lines) + "\n"


def render_ratio_change_table(ratio_df, max_rows=10):
    if ratio_df is None or ratio_df.empty:
        return "暂无历史数据\n"
    if "ratio_today" in ratio_df.columns and ratio_df["ratio_today"].notna().sum() == 0:
        return "板块成交额暂缺\n"
    seen_names = set()
    lines = []
    for _, row in ratio_df.iterrows():
        name = normalize_board_name(row.get("board_name", "-"))
        if name in seen_names:
            continue
        if len(seen_names) >= max_rows:
            break
        seen_names.add(name)
        pct = fmt_pct(row.get("pct_chg", np.nan))
        ratio_today = row.get("ratio_today", np.nan)
        change = row.get("ratio_change_3d", row.get("ratio_change_5d", np.nan))
        ratio_str = f"{ratio_today * 100:.2f}%" if pd.notna(ratio_today) else "-"
        change_str = f"{change * 100:+.2f}个百分点" if pd.notna(change) else "-"
        lines.append(f"| {name} | {pct} | {ratio_str} | {change_str} |")
    return "\n".join(lines) + "\n"


def render_distribution(dist):
    if not dist:
        return "暂无数据\n"
    lines = []
    for label in ["高潮", "过热", "平衡", "退潮", "冰点"]:
        item = dist.get(label, {"count": 0, "ratio": 0})
        bar_len = int(item["ratio"] / 5)
        bar = "█" * bar_len
        lines.append(f"| {label} | {item['count']}个 | {item['ratio']}% | {bar} |")
    return "\n".join(lines) + "\n"


# ── 观察池渲染（保持不变）──

def render_stock_pool_unified(df):
    """统一观察池个股渲染"""
    if df is None or df.empty:
        return "暂无符合条件个股\n"
    lines = []
    for idx, row in df.reset_index(drop=True).iterrows():
        risk_level = row.get("risk_level", "-")
        action_signal = row.get("action_signal", "-")
        lines.append(f"{idx + 1}. **{row['name']}**（{row['code']}）| {row['strategy']} | 风险:{risk_level} | 信号:{action_signal}")
        lines.append(f"   收盘:{fmt_num(row['close'])} | 涨幅:{fmt_pct(row['pct_chg'])} | 量比:{fmt_num(row.get('volume_ratio', np.nan))} | 换手:{fmt_num(row.get('turnover', np.nan), 2)}%")
        o_low = row.get("observe_low", row.get("buy_low", "-"))
        o_high = row.get("observe_high", row.get("buy_high", "-"))
        p_price = row.get("pressure_price", row.get("target", "-"))
        i_price = row.get("invalid_price", row.get("stop_loss", "-"))
        lines.append(f"   观察区间:{o_low}~{o_high} | 压力位:{p_price} | 失效位:{i_price}")
        lines.append(f"   入选原因:{row.get('entry_reason', row.get('reason', '-'))}")
        ths = row.get("ths_reason", "")
        if ths:
            lines.append(f"   题材归因:{ths}")
        risk_reasons = row.get("risk_reasons", "")
        if risk_reasons:
            lines.append(f"   风险:{risk_reasons.replace(chr(10), '；')[:120]}")
        lines.append("")
    return "\n".join(lines)


def render_snowball_pool(df):
    """滚雪球趋势池"""
    if df is None or df.empty:
        return "暂无符合条件个股\n"
    lines = ["> 趋势跟随策略：MACD回踩零轴附近后金叉，站上MA20，量比温和放大。", ""]
    for idx, row in df.reset_index(drop=True).iterrows():
        risk_level = row.get("risk_level", "-")
        lines.append(f"**{idx + 1}. {row['name']}（{row['code']}）** | 风险:{risk_level}")
        lines.append(f"- 收盘:{fmt_num(row['close'])} | 涨幅:{fmt_pct(row['pct_chg'])}")
        lines.append(f"- MA20:{fmt_num(row.get('ma20', np.nan))} | MACD DIF:{fmt_num(row.get('macd_dif', np.nan), 4)}")
        lines.append(f"- 止损(MA20):{fmt_num(row.get('invalid_price', np.nan))} | 持仓:{row.get('hold_days', '-')}")
        reason = row.get("entry_reason", row.get("reason", ""))
        if reason:
            lines.append(f"- 入选原因:{reason}")
        lines.append("")
    return "\n".join(lines)


# ── 统一主日报 ──

def render_unified_report(
    trade_date, data_status, quality, market, industry, concept,
    sentiment, selectors, board_ratio_changes=None,
    trade_plan=None, board_trend_summary=None, report_context=None,
):
    date_display = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    lines = []

    # context 优先取值
    market_context = _get_context_section(report_context, "market")
    sentiment_context = _get_context_section(report_context, "sentiment")
    m_score = market_context.get("score", market.get("score", 0))
    m_status = market_context.get("status", market.get("status", ""))
    s_score = sentiment_context.get("score", sentiment.get("score", 0))
    s_stage = sentiment_context.get("stage", sentiment.get("stage", ""))
    pos = validate_position_consistency(trade_plan)

    # ── 预计算 insights ──
    weak_triggers, weak_checked, weak_items = check_weak_market(market)
    weak_conclusion = weak_market_conclusion(weak_triggers, weak_checked)
    profit = assess_profit_effect(market)
    width = compute_market_width(market)
    env = assess_trading_environment(market, sentiment, trade_plan, profit)
    env["weak_market_triggers"] = f"{weak_triggers}/{weak_checked}"
    effective_themes, dynamic_themes = filter_effective_themes(sentiment.get("themes", []) if isinstance(sentiment, dict) else [])
    # themes can come from multiple sources
    all_themes = effective_themes  # will be overwritten below

    s_stage, stage_explain = explain_sentiment_stage(s_score, s_stage)

    # ── YAML frontmatter ──
    lines.append("---")
    lines.append(f"date: {date_display}")
    lines.append(f"market_score: {m_score}")
    lines.append(f"market_status: {m_status}")
    lines.append(f"sentiment_score: {s_score}")
    lines.append(f"sentiment_stage: {s_stage}")
    lines.append(f"position_cap: {pos['max_pct']}成")
    lines.append(f"data_confidence: {quality.get('confidence_score', 0)}")
    lines.append("---")
    lines.append("")

    # ── 标题 ──
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
        pd.Timestamp(date_display).dayofweek]
    lines.append(f"# A股每日复盘 | {date_display}（{weekday}）")
    lines.append("")

    # ══════════════════════════════════════
    # 0. 今日摘要
    # ══════════════════════════════════════
    lines.append("## 0. 今日摘要")
    lines.append("")
    lines.append("| 项目 | 结论 |")
    lines.append("|------|------|")
    lines.append(f"| 市场综合评分 | {m_score:.1f} / 100 |")
    lines.append(f"| 市场状态 | {m_status} |")
    lines.append(f"| 短线情绪阶段 | {s_stage} |")
    lines.append(f"| 总仓位上限 | {pos['max_pct']}成 |")
    lines.append(f"| 单票上限 | {pos['single_pct']}成 |")
    lines.append(f"| 数据可信度 | {quality.get('confidence_score', 0)} / 100 |")
    lines.append("")
    lines.append(f"**一句话结论：** {market.get('summary', '数据生成中')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 1. 交易环境判断
    # ══════════════════════════════════════
    lines.append("## 1. 交易环境判断")
    lines.append("")
    lines.append("| 维度 | 当前状态 | 解释 |")
    lines.append("|------|----------|------|")
    lines.append(f"| 赚钱效应 | {profit['level']} | {profit['detail'][:60]} |")
    lines.append(f"| 弱市不做 | 触发 {weak_triggers}/{weak_checked} | {weak_conclusion} |")
    amount = market.get("total_amount", 0)
    lines.append(f"| 市场量能 | {amount:.0f}亿 | 成交额 |")
    lines.append(f"| 仓位边界 | {pos['max_pct']}成 | 来自 trade_plan |")
    lines.append("")
    if profit["downgraded"]:
        lines.append(f"> {profit['note']}")
        lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 2. 市场状态
    # ══════════════════════════════════════
    lines.append("## 2. 市场状态")
    lines.append("")
    lines.append("### 2.1 大盘指数")
    indices = market.get("indices", [])
    if indices:
        lines.append("| 指数 | 收盘 | 涨跌幅 | 成交额(亿) |")
        lines.append("|------|------|--------|-----------|")
        for item in indices:
            lines.append(f"| {item['name']} | {fmt_num(item.get('close'))} | {fmt_pct(item.get('pct_chg'))} | {fmt_num(item.get('amount', 0)/1e8, 0)} |")
    else:
        lines.append("指数数据暂缺")
    lines.append("")

    lines.append("### 2.2 市场宽度")
    lines.append("")
    lines.append("| 指标 | 数值 | 判断 |")
    lines.append("|------|------|------|")
    lines.append(f"| 上涨家数 | {width['up_count']} | - |")
    lines.append(f"| 下跌家数 | {width['down_count']} | - |")
    lines.append(f"| 涨停家数 | {width['limit_up']} | - |")
    lines.append(f"| 跌停家数 | {width['limit_down']} | - |")
    lines.append(f"| 涨跌比 | {width['adv_ratio']:.2f} | {'宽度较好' if width['adv_ratio'] > 1.2 else '偏弱' if width['adv_ratio'] < 0.5 else '均衡'} |")
    lines.append(f"| 涨跌停比 | {width['lb_ratio']:.1f} | {'短线活跃' if width['lb_ratio'] > 3 else '弱市信号' if width['lb_ratio'] < 1 else '正常'} |")
    lines.append(f"| 绿盘占比 | {width['green_ratio']:.1%} | {'多数下跌' if width['green_ratio'] > 0.6 else '正常'} |")
    lines.append(f"| 炸板率 | N/A | 数据不足 |")
    lines.append(f"| 成交额 | {amount:.0f}亿 | - |")
    lines.append("")
    if width["green_ratio"] > 0.6 and market.get("score", 0) > 50:
        lines.append("> 指数偏强，但个股宽度偏弱，属于结构分化。指数强不代表赚钱效应普遍。")
        lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 3. 弱市不做检查
    # ══════════════════════════════════════
    lines.append("## 3. 弱市不做检查")
    lines.append("")
    lines.append("| 检查项 | 当前值 | 触发 | 解读 |")
    lines.append("|--------|--------|------|------|")
    for item in weak_items:
        trig = "YES" if item["triggered"] else "no"
        if item["status"] == "insufficient":
            trig = "-"
        lines.append(f"| {item['name']} | {item['value']} | {trig} | {item['note']} |")
    lines.append("")
    lines.append(f"**结论：** 已计算 {weak_checked} 项，触发 {weak_triggers} 项；3 项数据不足。→ {weak_conclusion}。")
    lines.append(f"**仓位上限：** 不超过 trade_plan 上限（{pos['max_pct']}成）。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 4. 情绪周期与赚钱效应
    # ══════════════════════════════════════
    lines.append("## 4. 情绪周期与赚钱效应")
    lines.append("")
    lines.append("| 指标 | 当前值 | 信号 |")
    lines.append("|------|--------|------|")
    lines.append(f"| 短线情绪评分 | {s_score:.1f} / 100 | {s_stage} |")
    lines.append(f"| 昨日涨停今日表现 | N/A | 数据不足 |")
    lines.append(f"| 连板高度 | N/A | 数据不足 |")
    lines.append(f"| 3板以上数量 | N/A | 数据不足 |")
    lines.append(f"| 涨停家数 | {width['limit_up']}家 | {'活跃' if width['limit_up'] > 50 else '一般'} |")
    lines.append(f"| 炸板率 | N/A | 数据不足 |")
    lines.append(f"| 成交额 | {amount:.0f}亿 | - |")
    lines.append("")
    lines.append(f"> {stage_explain}")
    if profit["downgraded"]:
        lines.append(f"> {profit['note']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 5. 资金流向（复用 board_ratio_changes + board_trend）
    # ══════════════════════════════════════
    lines.append("## 5. 资金流向")
    lines.append("")
    if board_ratio_changes:
        for label, ratio_key in [
            ("行业 3日流入 TOP5", "industry_ratio_3d_up"),
            ("行业 3日流出 TOP5", "industry_ratio_3d_down"),
            ("概念 3日流入 TOP5", "concept_ratio_3d_up"),
            ("概念 3日流出 TOP5", "concept_ratio_3d_down"),
        ]:
            df = board_ratio_changes.get(ratio_key)
            if df is not None and not df.empty:
                lines.append(f"### {label}")
                lines.append("| 板块 | 涨幅 | 成交占比 | 变化 |")
                lines.append("|---|---|---|---|")
                lines.append(render_ratio_change_table(df, max_rows=5))
                lines.append("")
    else:
        lines.append("暂无资金流向数据")
        lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 6. 主线分析
    # ══════════════════════════════════════
    lines.append("## 6. 主线分析")
    lines.append("")
    if effective_themes:
        lines.append("### 6.1 有效主线")
        lines.append("")
        lines.append("| 主线 | 强度 | 说明 |")
        lines.append("|------|------|------|")
        for t in effective_themes:
            lines.append(f"| {t['name']} | {t.get('level', '-')} | {t.get('beginner_explain', t.get('sustainability_risk', ''))[:60]} |")
        lines.append("")

    if dynamic_themes:
        lines.append("### 6.2 动态标签")
        lines.append("")
        lines.append("以下仅为热度标签，不作为有效主线：")
        dynamic_names = ", ".join(t["name"] for t in dynamic_themes)
        lines.append(f"  {dynamic_names}")
        lines.append("")

    if not effective_themes and not dynamic_themes:
        lines.append("今日无明显主线方向，热点较为分散。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 7. 弱市例外扫描
    # ══════════════════════════════════════
    lines.append("## 7. 弱市例外扫描")
    lines.append("")
    if weak_triggers >= 2:
        lines.append("当前弱市触发条件较多，以下为弱市环境下的例外扫描：")
        lines.append("- 今日暂无明确逆势涨停候选。")
    else:
        lines.append("今日弱市触发条件较少，暂不需要弱市例外扫描。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 8. 风险提示
    # ══════════════════════════════════════
    lines.append("## 8. 风险提示")
    lines.append("")
    lines.append("### 市场风险")
    if market.get("score", 0) < 45:
        lines.append("- 市场评分偏低，整体偏弱")
    if width["green_ratio"] > 0.6:
        lines.append("- 多数个股下跌，亏钱效应较强")
    if width["lb_ratio"] < 1:
        lines.append("- 跌停压过涨停，短线风险偏高")
    lines.append("")
    lines.append("### 数据风险")
    lines.append(f"- 报告可信度：{quality.get('confidence_score', 0)} / 100")
    if profit["downgraded"]:
        lines.append("- 赚钱效应为降级判断（缺少连板高度、炸板率、昨涨停表现）")
    for issue in quality.get("issues", []):
        lines.append(f"- {issue}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 9. 机会观察
    # ══════════════════════════════════════
    lines.append("## 9. 机会观察")
    lines.append("")
    if effective_themes:
        for t in effective_themes[:3]:
            lines.append(f"### {t['name']}")
            lines.append(f"- 逻辑：{t.get('beginner_explain', '')}")
            lines.append(f"- 风险：{t.get('sustainability_risk', '待评估')}")
            lines.append("")
    else:
        lines.append("暂无明确主线方向，以观察为主。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 10. 观察池
    # ══════════════════════════════════════
    lines.append("## 10. 观察池")
    lines.append("")
    if not quality.get("has_volume_ratio", True):
        lines.append("> 当前数据源缺少量比字段，量比相关筛选已自动降级。")
        lines.append("")

    pool_sections = [
        ("一次起爆", "一次起爆"), ("N字异动", "N字异动"),
        ("二次起爆", "二次起爆"), ("板块联动", "板块联动"),
        ("短线强势", "短线强势"), ("滚雪球趋势", "滚雪球趋势"),
    ]
    all_visible, all_caution, all_high_risk = [], [], []
    for pool_key, _ in pool_sections:
        df = selectors.get(pool_key)
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            entry = {"pool": pool_key, "row": row}
            risk = str(row.get("risk_level", ""))
            action = str(row.get("action_signal", ""))
            name = str(row.get("name", ""))
            if name.startswith("N"):
                all_high_risk.append(entry)
            elif risk == "高" or action in ("回避", "数据不足"):
                all_high_risk.append(entry)
            elif risk == "中" and action == "谨慎":
                all_caution.append(entry)
            else:
                all_visible.append(entry)

    # 可观察池
    lines.append("### 10.1 可观察")
    lines.append("")
    if all_visible:
        lines.append("| 股票 | 方向 | 模式标签 | 买入价 | 目标价 | 止损逻辑 | 仓位 | 能买 | 不能买 |")
        lines.append("|------|------|----------|--------|--------|----------|------|------|--------|")
        for entry in all_visible:
            row = entry["row"]
            tag = assign_pattern_tag(row, entry["pool"], market, effective_themes)
            o_low = row.get("observe_low", row.get("buy_low", "-"))
            o_high = row.get("observe_high", row.get("buy_high", "-"))
            inv = row.get("invalid_price", row.get("stop_loss", "-"))
            lines.append(
                f"| {row['name']} | {entry['pool']} | {tag} | {o_low}~{o_high} | "
                f"{row.get('pressure_price', '-')} | 跌破{inv} | ≤{pos['single_pct']}成 | 回调企稳 | 追高/破位 |"
            )
        lines.append("")
    else:
        lines.append("暂无符合条件个股")
        lines.append("")

    # 谨慎观察
    if all_caution:
        lines.append("### 10.2 谨慎观察")
        lines.append("")
        lines.append("| 股票 | 方向 | 模式标签 | 买入价 | 目标价 | 止损逻辑 | 仓位 | 能买 | 不能买 |")
        lines.append("|------|------|----------|--------|--------|----------|------|------|--------|")
        for entry in all_caution:
            row = entry["row"]
            tag = assign_pattern_tag(row, entry["pool"], market, effective_themes)
            o_low = row.get("observe_low", "-")
            o_high = row.get("observe_high", "-")
            inv = row.get("invalid_price", "-")
            lines.append(
                f"| {row['name']} | {entry['pool']} | {tag} | {o_low}~{o_high} | "
                f"{row.get('pressure_price', '-')} | 跌破{inv} | ≤{pos['single_pct']}成 | 确认信号 | 盲目追高 |"
            )
        lines.append("")

    # 高风险复盘
    if all_high_risk:
        lines.append("### 10.3 高风险复盘")
        lines.append("")
        lines.append("| 股票 | 方向 | 高风险原因 | 只复盘不买原因 |")
        lines.append("|------|------|------------|----------------|")
        for entry in all_high_risk[:8]:
            row = entry["row"]
            lines.append(
                f"| {row['name']} | {entry['pool']} | "
                f"{row.get('risk_level', '-')}/{row.get('action_signal', '-')} | 风险偏高，仅复盘 |"
            )
        lines.append("")

    # 滚雪球
    snowball_df = selectors.get("滚雪球趋势")
    if snowball_df is not None and not snowball_df.empty:
        lines.append("### 10.4 滚雪球趋势")
        lines.append("")
        lines.append(render_snowball_pool(snowball_df))

    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 11. 明日验证清单
    # ══════════════════════════════════════
    lines.append("## 11. 明日验证清单")
    lines.append("")
    checklist = generate_validation_checklist(market, effective_themes, profit, weak_triggers)
    for i, item in enumerate(checklist):
        lines.append(f"{i + 1}. {item}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 12. 交易计划摘要
    # ══════════════════════════════════════
    if trade_plan:
        r = trade_plan.get("market_restrictions", {})
        s = trade_plan.get("summary", {})
        lines.append("## 12. 交易计划摘要")
        lines.append("")
        if not r.get("allow_real_trade", True):
            lines.append("> 当前仅适合模拟观察，不建议实盘买入。")
            lines.append("")
        lines.append(f"- 实盘：{'允许' if r.get('allow_real_trade') else '仅模拟'} | 总仓位：{r.get('max_position_pct',0)}成 | 单票：{r.get('single_stock_pct',0)}成")
        lines.append(f"- 候选低吸：{s.get('候选低吸',0)} | 只观察：{s.get('只观察',0)} | 高风险回避：{s.get('高风险回避',0)} | 过滤：{s.get('不可交易过滤',0)}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ══════════════════════════════════════
    # 13. 纪律
    # ══════════════════════════════════════
    lines.append("## 13. 纪律")
    lines.append("")
    lines.append("- 不追高；")
    lines.append(f"- 总仓位不超过 trade_plan 上限（{pos['max_pct']}成）；")
    lines.append("- 弱市不做，结构分化只做核心方向；")
    lines.append("- 高风险复盘票只复盘，不作为正常买入候选；")
    lines.append("- 数据可信度不足时，只观察不下结论；")
    lines.append("- 本报告用于自动化复盘、风险提示和观察池生成，不构成实盘买卖建议。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 14. 数据可信度
    # ══════════════════════════════════════
    lines.append("## 14. 数据可信度")
    lines.append("")
    lines.append("| 项目 | 状态 | 说明 |")
    lines.append("|------|------|------|")
    lines.append(f"| 报告可信度 | {quality.get('confidence_score', 0)} / 100 | {'可参考' if quality.get('confidence_score', 0) >= 60 else '谨慎参考'} |")
    for item in quality.get("items", []):
        lines.append(f"| {item['item']} | {item['status']} | {item['detail']} |")
    lines.append("")
    if quality.get("issues"):
        lines.append("**主要扣分项：**")
        for issue in quality["issues"]:
            lines.append(f"- {issue}")
        lines.append("")
    lines.append("**影响范围：**")
    lines.append("- 市场和板块判断：影响较小；")
    lines.append("- 个股观察池排序：可能受影响（均线/量比数据缺失时）。")
    lines.append("")

    # ── 免责声明 ──
    lines.append("---")
    lines.append("")
    lines.append("## 免责声明")
    lines.append("")
    lines.append("本报告仅用于数据复盘和学习，不构成任何投资建议。所有观察池标的均为基于公开行情数据的规则筛选结果，观察区间/参考压力位/风险失效位由策略公式生成，不代表未来价格走势。市场有风险，投资需谨慎。")
    lines.append("")
    lines.append(f"> 数据源：AkShare | 生成时间：{date_display}")

    return "\n".join(lines)


# ── 兼容入口 ──

def render_daily_report(
    trade_date, data_status, market, industry, concept,
    sentiment, selectors, board_ratio_changes=None, mode="beginner",
    quality=None, themes=None, trade_plan=None, board_trend_summary=None,
    report_context=None,
):
    """统一入口：所有 mode 走同一份主日报"""
    return render_unified_report(
        trade_date, data_status, quality, market, industry,
        concept, sentiment, selectors, board_ratio_changes,
        trade_plan=trade_plan, board_trend_summary=board_trend_summary,
        report_context=report_context,
    )


def save_report(report, trade_date, mode="beginner"):
    out_dir = Path("reports/daily")
    out_dir.mkdir(parents=True, exist_ok=True)
    # 统一只生成一份主日报
    path = out_dir / f"daily_report_{trade_date}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    return path
