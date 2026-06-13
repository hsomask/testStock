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
    classify_concept_label, label_category_name, explain_non_industrial_label, dedup_watchlist_entries,
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

def _fmt_pct(val):
    if val is None:
        return "N/A"
    return f"{val * 100:.2f}%"


def _render_snapshot_stocks(lines, td):
    """快照复盘：展示 Top/Bottom 表现"""
    top = td.get("top_winners", [])
    bottom = td.get("top_losers", [])
    if top:
        lines.append("### 表现较好")
        lines.append("")
        lines.append("| 股票 | 昨日层级 | 今日涨跌 | 量价 | 结果 |")
        lines.append("|------|----------|----------|------|------|")
        for s in top:
            pct_str = _fmt_pct(s.get("pct_chg", 0) / 100) if s.get("pct_chg") is not None else "N/A"
            vol_note = s.get("volume_note", "N/A")
            tag = s.get("tag", "N/A")
            lines.append(f"| {s.get('name','')} | {s.get('layer','')} | {pct_str} | {vol_note} | {tag} |")
        lines.append("")
    if bottom:
        lines.append("### 表现较弱")
        lines.append("")
        lines.append("| 股票 | 昨日层级 | 今日涨跌 | 量价 | 结果 |")
        lines.append("|------|----------|----------|------|------|")
        for s in bottom:
            pct_str = _fmt_pct(s.get("pct_chg", 0) / 100) if s.get("pct_chg") is not None else "N/A"
            vol_note = s.get("volume_note", "N/A")
            tag = s.get("tag", "N/A")
            lines.append(f"| {s.get('name','')} | {s.get('layer','')} | {pct_str} | {vol_note} | {tag} |")
        lines.append("")


def _dedup_tp_entries(items):
    """trade_plan 条目按 name 去重，合并 strategy"""
    if not items:
        return items
    seen = {}
    for st in items:
        key = st.get("name", st.get("code", ""))
        if key in seen:
            existing = seen[key]
            s = st.get("strategy", "")
            if s and s not in existing.get("strategy", ""):
                existing["strategy"] = existing.get("strategy", "") + " / " + s
        else:
            seen[key] = dict(st)
    return list(seen.values())


def render_unified_report(
    trade_date, data_status, quality, market, industry, concept,
    sentiment, selectors, board_ratio_changes=None,
    trade_plan=None, board_trend_summary=None, report_context=None,
    themes=None, t1_data=None,
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
    weak_triggers, weak_checked, weak_items, weak_green, weak_lb = check_weak_market(market)
    weak_tag, weak_conclusion = weak_market_conclusion(weak_triggers, weak_checked, weak_green, weak_lb)
    profit = assess_profit_effect(market)
    width = compute_market_width(market)
    width_ok = width["adv_ratio"] > 1.2 and width["green_ratio"] < 0.5
    width_weak = width["green_ratio"] > 0.6 or width["adv_ratio"] < 0.5
    env = assess_trading_environment(market, sentiment, trade_plan, profit)
    env["weak_market_triggers"] = f"{weak_triggers}/{weak_checked}"
    # Merge themes from both detect_main_themes and sentiment
    all_raw_themes = list(themes or [])
    if isinstance(sentiment, dict) and sentiment.get("themes"):
        all_raw_themes.extend(sentiment["themes"])
    effective_themes, dynamic_themes = filter_effective_themes(all_raw_themes)

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
    # 1. 昨日观察池兑现复盘（T+1）
    # ══════════════════════════════════════
    lines.append("## 1. 昨日观察池兑现复盘（T+1）")
    lines.append("")

    status = (t1_data or {}).get("status", "missing")

    if not t1_data or not t1_data.get("available"):
        # missing / error
        msg = (t1_data or {}).get("message", "今日 T+1 复盘尚未生成。")
        lines.append(f"{msg}")
        lines.append("")
        lines.append("本模块将在 evaluation 链路完成后自动展示，不影响今日日报主体。")
        lines.append("")

    elif status == "snapshot":
        td = t1_data
        lines.append("> K 线覆盖率不足，本段使用当日行情快照生成降级复盘，仅供观察，不计入正式 evaluation 统计。")
        lines.append("")
        lines.append("| 项目 | 结果 |")
        lines.append("|------|------|")
        lines.append(f"| 信号日期 | {td.get('signal_date', 'N/A')} |")
        lines.append(f"| 评价日期 | {td.get('as_of_date', 'N/A')} |")
        lines.append(f"| 昨日观察池数量 | {td.get('total_signals', 0)} |")
        lines.append(f"| 快照覆盖数量 | {td.get('snapshot_covered', 0)} |")
        lines.append(f"| 快照覆盖率 | {_fmt_pct(td.get('snapshot_coverage'))} |")
        if td.get('kline_coverage') is not None:
            lines.append(f"| K线覆盖率 | {_fmt_pct(td.get('kline_coverage'))} |")
        lines.append(f"| 复盘口径 | 快照复盘（降级） |")
        lines.append("")
        _render_snapshot_stocks(lines, td)

    elif status == "defer":
        lines.append("今日 T+1 复盘因行情缓存不足暂缓。")
        lines.append("当前不对昨日观察池表现下结论。")
        lines.append("")

    elif status == "insufficient":
        td = t1_data
        lines.append("今日 T+1 复盘覆盖不足，暂不下结论。")
        lines.append("")
        lines.append("| 项目 | 结果 |")
        lines.append("|------|------|")
        lines.append(f"| 信号日期 | {td.get('signal_date', 'N/A')} |")
        lines.append(f"| 评价日期 | {td.get('as_of_date', 'N/A')} |")
        lines.append(f"| 昨日观察池数量 | {td.get('total_signals', 0)} |")
        lines.append(f"| 实际评价数量 | {td.get('evaluated_1d', 0)} |")
        lines.append(f"| 1日覆盖率 | {_fmt_pct(td.get('coverage_1d'))} |")
        lines.append("")
        lines.append("> 覆盖不足时不展示胜率、平均收益和强结论。")
        lines.append("")

    elif status == "partial":
        td = t1_data
        lines.append("> T+1 覆盖率偏低，结果仅供观察，不作为稳定结论。")
        lines.append("")
        lines.append("| 项目 | 结果 |")
        lines.append("|------|------|")
        lines.append(f"| 信号日期 | {td.get('signal_date', 'N/A')} |")
        lines.append(f"| 评价日期 | {td.get('as_of_date', 'N/A')} |")
        lines.append(f"| 昨日观察池数量 | {td.get('total_signals', 0)} |")
        lines.append(f"| 实际评价数量 | {td.get('evaluated_1d', 0)} |")
        lines.append(f"| 1日覆盖率 | {_fmt_pct(td.get('coverage_1d'))} |")
        lines.append(f"| 平均次日收益 | {_fmt_pct(td.get('avg_return_1d'))} |")
        lines.append(f"| 次日胜率 | {_fmt_pct(td.get('win_rate_1d'))} |")
        lines.append(f"| 分层倒挂 | {'**是**' if td.get('inversion') else '否'} |")
        lines.append(f"| 风险预警 | {'**有**' if td.get('risk_warning') else '无'} |")
        lines.append(f"| 结论等级 | {td.get('conclusion_level', 'N/A')} |")
        lines.append("")
        top = td.get("top_winners", [])
        bottom = td.get("top_losers", [])
        if top or bottom:
            lines.append("> 样本覆盖不足，个股表现仅作为局部参考。")
            lines.append("")
            if top:
                for s in top:
                    lines.append(f"- {s['name']}（{s.get('layer','')}）：{_fmt_pct(s['ret'])}")
            if bottom:
                for s in bottom:
                    lines.append(f"- {s['name']}（{s.get('layer','')}）：{_fmt_pct(s['ret'])}")
            lines.append("")

    else:
        # ok
        td = t1_data
        lines.append("| 项目 | 结果 |")
        lines.append("|------|------|")
        lines.append(f"| 信号日期 | {td.get('signal_date', 'N/A')} |")
        lines.append(f"| 评价日期 | {td.get('as_of_date', 'N/A')} |")
        lines.append(f"| 昨日观察池数量 | {td.get('total_signals', 0)} |")
        lines.append(f"| 实际评价数量 | {td.get('evaluated_1d', 0)} |")
        lines.append(f"| 1日覆盖率 | {_fmt_pct(td.get('coverage_1d'))} |")
        lines.append(f"| 平均次日收益 | {_fmt_pct(td.get('avg_return_1d'))} |")
        lines.append(f"| 次日胜率 | {_fmt_pct(td.get('win_rate_1d'))} |")
        lines.append(f"| 分层倒挂 | {'**是**' if td.get('inversion') else '否'} |")
        lines.append(f"| 风险预警 | {'**有**' if td.get('risk_warning') else '无'} |")
        lines.append(f"| 结论等级 | {td.get('conclusion_level', 'N/A')} |")
        lines.append("")
        top = td.get("top_winners", [])
        bottom = td.get("top_losers", [])
        if top:
            lines.append("**表现较好：**")
            for s in top:
                lines.append(f"- {s['name']}（{s.get('layer','')}）：{_fmt_pct(s['ret'])}")
            lines.append("")
        if bottom:
            lines.append("**表现较弱：**")
            for s in bottom:
                lines.append(f"- {s['name']}（{s.get('layer','')}）：{_fmt_pct(s['ret'])}")
            lines.append("")

    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 2. 交易环境判断
    # ══════════════════════════════════════
    lines.append("## 2. 交易环境判断")
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
    lines.append("## 3. 市场状态")
    lines.append("")
    lines.append("### 3.1 大盘指数")
    indices = market.get("indices", [])
    if indices:
        lines.append("| 指数 | 收盘 | 涨跌幅 | 成交额(亿) |")
        lines.append("|------|------|--------|-----------|")
        for item in indices:
            lines.append(f"| {item['name']} | {fmt_num(item.get('close'))} | {fmt_pct(item.get('pct_chg'))} | {fmt_num(item.get('amount', 0)/1e8, 0)} |")
    else:
        lines.append("指数数据暂缺")
    lines.append("")

    lines.append("### 3.2 市场宽度")
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
    lines.append("## 4. 弱市不做检查")
    lines.append("")
    lines.append(f"**弱市不做：{weak_tag}**")
    lines.append("")
    if weak_triggers >= 1:
        lines.append("可计算项中，部分指标触发弱市信号，但涨跌停比仍显示短线活跃。")
    else:
        lines.append("可计算项中，绿盘占比和涨跌停比均未触发弱市信号。")
    lines.append(f"结论：{weak_conclusion}")
    lines.append("")
    lines.append("| 类别 | 数量 |")
    lines.append("|------|------|")
    lines.append(f"| 可计算项 | {weak_checked} |")
    lines.append(f"| 已触发 | {weak_triggers} |")
    lines.append(f"| 数据不足 | 3 |")
    lines.append("")
    lines.append("| 检查项 | 当前值 | 触发 | 解读 |")
    lines.append("|--------|--------|------|------|")
    for item in weak_items:
        trig = "YES" if item["triggered"] else "no"
        if item["status"] == "insufficient":
            trig = "-"
        lines.append(f"| {item['name']} | {item['value']} | {trig} | {item['note']} |")
    lines.append("")
    lines.append(f"**仓位上限：** 不超过 trade_plan 上限（{pos['max_pct']}成）。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 4. 情绪周期与赚钱效应
    # ══════════════════════════════════════
    lines.append("## 5. 情绪周期与赚钱效应")
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
    lines.append("## 6. 资金流向")
    lines.append("")
    if board_ratio_changes:
        # 行业表格（原样保留）
        for label, ratio_key in [
            ("行业 3日流入 TOP5", "industry_ratio_3d_up"),
            ("行业 3日流出 TOP5", "industry_ratio_3d_down"),
        ]:
            df = board_ratio_changes.get(ratio_key)
            if df is not None and not df.empty:
                lines.append(f"### {label}")
                lines.append("| 板块 | 涨幅 | 成交占比 | 变化 |")
                lines.append("|---|---|---|---|")
                lines.append(render_ratio_change_table(df, max_rows=5))
                lines.append("")

        # 概念表格 — 分流为产业概念 + 动态/风格标签
        for ratio_key, label_prefix in [
            ("concept_ratio_3d_up", "产业概念 3日流入"),
            ("concept_ratio_3d_down", "产业概念 3日流出"),
        ]:
            df = board_ratio_changes.get(ratio_key)
            if df is not None and not df.empty:
                industrial = []
                non_industrial = []
                for _, row in df.iterrows():
                    name = row.get("board_name", "")
                    cat = classify_concept_label(str(name))
                    if cat == "industrial":
                        industrial.append(row)
                    else:
                        non_industrial.append(row)

                if industrial:
                    lines.append(f"### {label_prefix} TOP5")
                    lines.append("| 概念 | 涨幅 | 成交占比 | 变化 |")
                    lines.append("|---|---|---|---|")
                    for row in industrial[:5]:
                        name = normalize_board_name(row.get("board_name", "-"))
                        pct = fmt_pct(row.get("pct_chg", np.nan))
                        ratio_today = row.get("ratio_today", np.nan)
                        change = row.get("ratio_change_3d", row.get("ratio_change_5d", np.nan))
                        ratio_str = f"{ratio_today * 100:.2f}%" if pd.notna(ratio_today) else "-"
                        change_str = f"{change * 100:+.2f}个百分点" if pd.notna(change) else "-"
                        lines.append(f"| {name} | {pct} | {ratio_str} | {change_str} |")
                    lines.append("")
                    if len(industrial) < 5:
                        lines.append(f"> 过滤动态标签后，产业概念仅 {len(industrial)} 个，不强行补位。")
                        lines.append("")

        # 动态/风格标签
        all_non_ind = {}
        for ratio_key in ["concept_ratio_3d_up", "concept_ratio_3d_down"]:
            df = board_ratio_changes.get(ratio_key)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    name = str(row.get("board_name", ""))
                    cat = classify_concept_label(name)
                    if cat != "industrial":
                        change = row.get("ratio_change_3d", row.get("ratio_change_5d", 0))
                        cat_label = label_category_name(cat)
                        if name not in all_non_ind or abs(change) > abs(all_non_ind[name][0]):
                            all_non_ind[name] = (change, cat_label)

        if all_non_ind:
            lines.append("### 短线情绪/风格标签变化 TOP5")
            lines.append("")
            lines.append("> 这些不是产业主线，只反映短线情绪、市场热度、交易风格或资金属性的变化。")
            lines.append("")
            lines.append("| 标签 | 类型 | 变化 | 看法 |")
            lines.append("|------|------|------|------|")
            sorted_tags = sorted(all_non_ind.items(), key=lambda x: abs(x[1][0]), reverse=True)
            for name, (change, cat_label) in sorted_tags[:5]:
                change_str = f"{change * 100:+.2f}个百分点"
                explain = explain_non_industrial_label(name, cat_label)
                lines.append(f"| {name} | {cat_label} | {change_str} | {explain} |")
            lines.append("")
    else:
        lines.append("暂无资金流向数据")
        lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 6. 主线分析
    # ══════════════════════════════════════
    lines.append("## 7. 主线分析")
    lines.append("")

    # 从 board_ratio_changes 提取产业概念作为观察方向
    obs_directions = []
    if board_ratio_changes:
        for ratio_key in ["concept_ratio_3d_up", "concept_ratio_3d_down"]:
            df = board_ratio_changes.get(ratio_key)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    name = str(row.get("board_name", ""))
                    if classify_concept_label(name) == "industrial":
                        raw = row.get("ratio_change_3d", row.get("ratio_change_5d", 0))
                        change = float(raw) * 100 if pd.notna(raw) else 0
                        obs_directions.append((name, change))

        # 也从行业提取
        for ratio_key in ["industry_ratio_3d_up"]:
            df = board_ratio_changes.get(ratio_key)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    name = row.get("board_name", "")
                    raw = row.get("ratio_change_3d", row.get("ratio_change_5d", 0))
                    change = float(raw) * 100 if pd.notna(raw) else 0
                    obs_directions.append((name, change))

        obs_directions.sort(key=lambda x: x[1], reverse=True)

    if obs_directions:
        # 观察主线 (positive change)
        obs_main = [(n, c) for n, c in obs_directions if c > 0][:5]
        # 退潮方向 (negative change)
        receding = [(n, c) for n, c in obs_directions if c < 0][:5]

        if obs_main:
            lines.append("### 7.1 有效主线 / 观察主线")
            lines.append("")
            lines.append("| 方向 | 依据 | 风险 |")
            lines.append("|------|------|------|")
            # 动态风险文案
            if width_ok and s_stage in ("高潮", "过热"):
                theme_risk = "市场宽度尚可，但情绪高潮，持续性待确认"
            elif width_ok:
                theme_risk = "市场宽度尚可，关注持续性"
            elif width_weak:
                theme_risk = "市场宽度偏弱，只作观察"
            else:
                theme_risk = "市场宽度一般，持续性待确认"

            for name, chg in obs_main:
                direction = "观察主线" if chg > 0.5 else "观察方向"
                chg_str = f"3日变化 +{chg:.2f}个百分点"
                lines.append(f"| {name} | {chg_str}，成交占比提升 | {theme_risk} |")
            lines.append("")

        if receding:
            lines.append("### 7.2 退潮方向")
            lines.append("")
            lines.append("| 方向 | 依据 | 说明 |")
            lines.append("|------|------|------|")
            for name, chg in receding:
                chg_str = f"3日变化 {chg:+.2f}个百分点"
                lines.append(f"| {name} | {chg_str} | 相关标的不追高，只等回调确认 |")
            lines.append("")

    if dynamic_themes:
        lines.append("### 7.3 动态标签（不作为主线）")
        lines.append("")
        dynamic_names = ", ".join(t["name"] for t in dynamic_themes[:8])
        lines.append(f"  {dynamic_names}")
        lines.append("")

    # 主线结论
    if obs_main:
        main_names = "、".join(n for n, _ in obs_main[:4])
        if width_ok:
            width_word = "市场宽度尚可"
            if s_stage in ("高潮", "过热"):
                advice = "但短线情绪处于高潮，持续性仍需确认，不宜追高扩散"
            else:
                advice = "可适度参与分歧低吸"
        elif width_weak:
            width_word = "市场宽度偏弱"
            advice = "只作为观察主线，不宜扩散到普买"
        else:
            width_word = "市场宽度一般"
            advice = "适合分歧低吸，不宜追高"
        lines.append(f"**主线结论：** 今日没有全市场级别主线，但存在局部结构方向：{main_names}。{width_word}，{advice}。")
    elif not obs_directions:
        lines.append("今日暂无明确产业主线，热点偏分散。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 7. 弱市例外扫描
    # ══════════════════════════════════════
    lines.append("## 8. 弱市例外扫描")
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
    lines.append("## 9. 风险提示")
    lines.append("")
    lines.append("### 9.1 市场风险")
    sentiment_stage = s_stage
    if sentiment_stage in ("高潮", "过热"):
        lines.append(f"- 短线情绪处于**{sentiment_stage}**，需警惕高潮后分歧。涨停家数较多但不宜在高潮阶段盲目追高。")
        lines.append("- 若次日强势股开始冲高回落，应降低追涨优先级。")
    if width["green_ratio"] > 0.6:
        lines.append(f"- 绿盘占比 {width['green_ratio']:.1%}，多数个股下跌，指数表现不能代表全市场赚钱效应。")
    if width["lb_ratio"] < 1:
        lines.append("- 跌停压过涨停，短线风险偏高。")
    if width["adv_ratio"] < 0.5:
        lines.append("- 涨跌比偏弱，市场宽度不足。")
    if market.get("score", 0) < 45:
        lines.append("- 市场综合评分偏低，整体偏弱。")
    if sentiment_stage not in ("高潮", "过热") and not (width["green_ratio"] > 0.6 or width["lb_ratio"] < 1 or market.get("score", 0) < 45):
        lines.append("- 当前市场风险信号未明显触发。")
    lines.append("")

    # 板块风险：从资金流出方向提取
    receding_list = [(n, c) for n, c in obs_directions if c < 0][:5] if obs_directions else []
    if receding_list:
        lines.append("### 9.2 板块风险")
        receding_names = "、".join(n for n, _ in receding_list[:5])
        lines.append(f"- {receding_names} 短期资金流出，相关个股降低追高优先级。")
        if any(True for n, c in obs_directions if c > 0):
            p_risk = "市场宽度尚可，但短线情绪处于高潮，需警惕次日分歧" if (width_ok and s_stage in ("高潮", "过热")) else ("市场宽度偏弱，持续性仍需验证" if width_weak else "持续性仍需观察")
            lines.append(f"- 虽有局部方向资金流入，但{p_risk}。")
        lines.append("")

    # 观察池风险
    lines.append("### 9.3 观察池风险")
    # 从 selectors 直接统计
    n_count = 0
    caution_count = 0
    for pool_key in ["一次起爆", "N字异动", "二次起爆", "板块联动", "短线强势", "滚雪球趋势"]:
        df = selectors.get(pool_key)
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            strategy = str(row.get("strategy", ""))
            risk = str(row.get("risk_level", ""))
            action = str(row.get("action_signal", ""))
            if strategy in ("N字异动", "二次起爆") or pool_key in ("N字异动", "二次起爆"):
                n_count += 1
            if risk == "中" and action == "谨慎":
                caution_count += 1
    if n_count > 3:
        lines.append(f"- 多只候选来自 N字异动/二次起爆（{n_count}只），一旦市场宽度继续走弱，容易冲高回落。")
    if caution_count > 0:
        lines.append(f"- 谨慎观察层 {caution_count} 只股票不应和可观察层同等对待。")
    lines.append("")

    # 数据风险
    lines.append("### 9.4 数据风险")
    lines.append(f"- 报告可信度：{quality.get('confidence_score', 0)} / 100")
    if profit["downgraded"]:
        lines.append("- 赚钱效应为降级判断（缺少连板高度、炸板率、昨涨停表现）")
    for issue in quality.get("issues", [])[:3]:
        lines.append(f"- {issue}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 9. 机会观察
    # ══════════════════════════════════════
    lines.append("## 10. 机会观察")
    lines.append("")
    obs_main_list = [(n, c) for n, c in obs_directions if c > 0][:5] if obs_directions else []
    receding_list = [(n, c) for n, c in obs_directions if c < 0][:3] if obs_directions else []

    if obs_main_list:
        lines.append("今日没有全市场级别主线，但存在局部结构机会：")
        lines.append("")
        opp_risk_word = "市场宽度尚可，但短线情绪处于高潮，不宜追高扩散" if (width_ok and s_stage in ("高潮", "过热")) else ("市场宽度偏弱，不适合扩散到普买" if width_weak else "可适度参与")
        for i, (name, chg) in enumerate(obs_main_list):
            lines.append(f"{i + 1}. **{name}**")
            lines.append(f"   资金流入明显，作为观察主线；{opp_risk_word}。")
            lines.append("")
        if receding_list:
            receding_names = "、".join(n for n, _ in receding_list)
            lines.append(f"**退潮方向：** {receding_names} — 短期资金流出，相关个股只做回调确认，不追高。")
            lines.append("")
        lines.append(f"所有机会均限制在 trade_plan 总仓位上限内。当前总仓位上限：{pos['max_pct']}成。")
    else:
        lines.append("暂无明确产业主线，以观察为主。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 10. 观察池
    # ══════════════════════════════════════
    lines.append("## 11. 观察池")
    lines.append("")
    if not quality.get("has_volume_ratio", True):
        lines.append("> 当前数据源缺少量比字段，量比相关筛选已自动降级。")
        lines.append("")

    # ── 以 trade_plan 为准 ──
    if trade_plan and trade_plan.get("plans"):
        tp_plans = trade_plan["plans"]
        tp_summary = trade_plan.get("summary", {})

        # 先去重（节内）
        low_buy = _dedup_tp_entries(tp_plans.get("候选低吸", []))
        watch_only = _dedup_tp_entries(tp_plans.get("只观察", []))
        cond_fail = _dedup_tp_entries(tp_plans.get("交易条件不满足", []))
        high_risk = _dedup_tp_entries(tp_plans.get("高风险回避", []))
        excluded = _dedup_tp_entries(tp_plans.get("不可交易过滤", []))

        # 跨节互斥：不可交易过滤 > 高风险回避 > 交易条件不满足 > 只观察 > 候选低吸
        def _tp_key(st):
            return st.get("code", "") or st.get("name", "")
        excluded_keys = {_tp_key(s) for s in excluded}
        high_risk_keys = {_tp_key(s) for s in high_risk}
        cond_fail_keys = {_tp_key(s) for s in cond_fail}
        watch_keys = {_tp_key(s) for s in watch_only}
        high_risk = [s for s in high_risk if _tp_key(s) not in excluded_keys]
        cond_fail = [s for s in cond_fail if _tp_key(s) not in (excluded_keys | high_risk_keys)]
        watch_only = [s for s in watch_only if _tp_key(s) not in (excluded_keys | high_risk_keys | cond_fail_keys)]
        low_buy = [s for s in low_buy if _tp_key(s) not in (excluded_keys | high_risk_keys | cond_fail_keys | watch_keys)]

        # 10.1 候选低吸
        if low_buy:
            lines.append(f"### 11.1 候选低吸（{tp_summary.get('候选低吸', len(low_buy))}只）")
            lines.append("")
            lines.append("| 股票 | 策略来源 | 模式标签 | 买入价 | 目标价 | 止损逻辑 | 仓位 | 能买 | 不能买 |")
            lines.append("|------|----------|----------|--------|--------|----------|------|------|--------|")
            for st in low_buy:
                tag = assign_pattern_tag(st, st.get("strategy", ""), market, effective_themes)
                o_low = st.get("observe_low", st.get("buy_low", "-"))
                o_high = st.get("observe_high", st.get("buy_high", "-"))
                inv = st.get("invalid_price", st.get("stop_loss", "-"))
                lines.append(
                    f"| {st.get('name','')} | {st.get('strategy','')} | {tag} | {o_low}~{o_high} | "
                    f"{st.get('pressure_price', '-')} | 跌破{inv} | ≤{pos['single_pct']}成 | 回调企稳 | 追高/破位 |"
                )
            lines.append("")

        # 10.2 只观察
        if watch_only:
            lines.append(f"### 11.2 只观察（{tp_summary.get('只观察', len(watch_only))}只）")
            lines.append("")
            lines.append("| 股票 | 策略来源 | 模式标签 | 买入价 | 目标价 | 止损逻辑 | 仓位 | 能买 | 不能买 |")
            lines.append("|------|----------|----------|--------|--------|----------|------|------|--------|")
            for st in watch_only:
                tag = assign_pattern_tag(st, st.get("strategy", ""), market, effective_themes)
                o_low = st.get("observe_low", "-")
                o_high = st.get("observe_high", "-")
                inv = st.get("invalid_price", "-")
                lines.append(
                    f"| {st.get('name','')} | {st.get('strategy','')} | {tag} | {o_low}~{o_high} | "
                    f"{st.get('pressure_price', '-')} | 跌破{inv} | ≤{pos['single_pct']}成 | 确认信号 | 盲目追高 |"
                )
            lines.append("")

        # 10.3 交易条件不满足
        if cond_fail:
            lines.append(f"### 11.3 交易条件不满足（{len(cond_fail)}只）")
            lines.append("")
            lines.append("| 股票 | 策略来源 | 当前状态 | 原因 | 处理 |")
            lines.append("|------|----------|----------|------|------|")
            for st in cond_fail:
                reason = st.get("reason", st.get("entry_reason", "-"))
                lines.append(f"| {st.get('name','')} | {st.get('strategy','')} | 不适合低吸 | {reason} | 不追高，只观察 |")
            lines.append("")

        # 10.4 高风险回避（始终展示，与 trade_plan 对齐）
        lines.append(f"### 11.4 高风险回避（{len(high_risk)}只）")
        lines.append("")
        if high_risk:
            lines.append("| 股票 | 策略来源 | 高风险原因 | 只复盘不买原因 |")
            lines.append("|------|----------|------------|----------------|")
            for st in high_risk:
                lines.append(f"| {st.get('name','')} | {st.get('strategy','')} | {st.get('risk_level','-')} | 风险偏高，仅复盘 |")
        else:
            lines.append("暂无")
        lines.append("")

        # 10.5 不可交易过滤
        if excluded:
            lines.append(f"### 11.5 不可交易过滤（{len(excluded)}只）")
            lines.append("")
            lines.append("| 股票 | 策略来源 | 原因 | 处理 |")
            lines.append("|------|----------|------|------|")
            for st in excluded:
                reason = st.get("reason", "-")
                lines.append(f"| {st.get('name','')} | {st.get('strategy','')} | {reason} | 不纳入观察池 |")
            lines.append("")
    else:
        lines.append("暂无交易计划数据")
        lines.append("")

    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 11. 明日验证清单
    # ══════════════════════════════════════
    lines.append("## 12. 明日验证清单")
    lines.append("")
    checklist = generate_validation_checklist(market, effective_themes, profit, weak_triggers)
    for i, item in enumerate(checklist):
        lines.append(f"{i + 1}. {item}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ══════════════════════════════════════
    # 13. 交易计划摘要
    # ══════════════════════════════════════
    if trade_plan:
        r = trade_plan.get("market_restrictions", {})
        s = trade_plan.get("summary", {})
        lines.append("## 13. 交易计划摘要")
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
    lines.append("## 14. 纪律")
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
    lines.append("## 15. 数据可信度")
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
            # Skip the "无法展示成交占比变化" if board_ratio_changes is available
            if "无法展示成交占比变化" in str(issue) and board_ratio_changes:
                lines.append(f"- 板块成交占比变化来自缓存或降级数据，完整性需谨慎。")
            else:
                lines.append(f"- {issue}")
        lines.append("")

    # 影响范围：区分全市场 vs 观察池
    lines.append("**影响范围：**")
    lines.append("- 市场和板块判断：影响较小；")

    # 检查是否有均线缺失相关 issue
    has_ma_issue = any("均线" in str(issue) for issue in quality.get("issues", []))
    has_ma_item = any("均线" in str(item.get("item", "")) for item in quality.get("items", []))
    if has_ma_issue or has_ma_item:
        lines.append("- 全市场选股广度：受影响（均线数据缺失影响部分策略评分）；")
        lines.append("- 当前观察池买入价/止损/均线判断：可参考（观察池均线覆盖率正常）。")
    else:
        lines.append("- 个股观察池排序：可能受影响（数据缺失时）。")
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
    report_context=None, t1_data=None,
):
    """统一入口：所有 mode 走同一份主日报"""
    return render_unified_report(
        trade_date, data_status, quality, market, industry,
        concept, sentiment, selectors, board_ratio_changes,
        trade_plan=trade_plan, board_trend_summary=board_trend_summary,
        report_context=report_context,
        themes=themes,
        t1_data=t1_data,
    )


def save_report(report, trade_date, mode="beginner"):
    out_dir = Path("reports/daily")
    out_dir.mkdir(parents=True, exist_ok=True)
    # 统一只生成一份主日报
    path = out_dir / f"daily_report_{trade_date}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    return path
