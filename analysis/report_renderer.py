import requests
from pathlib import Path
import pandas as pd
import numpy as np

from analysis.utils import fmt_num, fmt_pct, fmt_yi
from analysis.explainer import explain_market_status, get_daily_learning_topics
from data.config import MINIMAX_API_KEY, MINIMAX_API_URL


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
                {
                    "role": "system",
                    "content": "你是一名经验丰富的A股交易员和分析师，擅长用简洁、专业的语言总结市场情况和策略建议。你的分析基于数据，不构成投资建议。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 2000,
        }
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=30)
        data = resp.json()
        if data.get("base_resp", {}).get("status_code") == 0:
            return data["choices"][0]["message"]["content"]
        return None
    except Exception:
        return None


def build_ai_prompt(trade_date, market, industry, concept, sentiment, selectors):
    prompt_parts = [
        f"日期：{trade_date}",
        "",
        f"## 市场数据",
        f"- 市场状态：{market['status']}",
        f"- 市场情绪评分：{market['score']}/100",
        f"- 成交额：{market['total_amount']:.0f}亿",
        f"- 上涨：{market['up_count']}只，下跌：{market['down_count']}只",
        f"- 涨停：{market['limit_up']}只，跌停：{market['limit_down']}只",
        "",
        f"## 情绪周期",
        f"- 情绪阶段：{sentiment['stage']}",
        f"- 情绪评分：{sentiment['score']}/100",
        "",
    ]
    active_inds = industry.get("active_boards", [])
    if active_inds:
        prompt_parts.append(f"强势行业：{'、'.join(active_inds)}")
    active_cons = concept.get("active_boards", [])
    if active_cons:
        prompt_parts.append(f"强势概念：{'、'.join(active_cons)}")
    prompt_parts.append("")
    for pool_name, pool_df in selectors.items():
        if pool_df is not None and not pool_df.empty:
            stocks = [f"{row['name']}({row['code']})" for _, row in pool_df.iterrows()]
            prompt_parts.append(f"{pool_name}观察池：{'、'.join(stocks)}")
    prompt_parts.append("")
    return "\n".join(prompt_parts)


def build_one_line_prompt(trade_date, market, sentiment, industry, concept):
    return (
        f"日期：{trade_date}\n"
        f"市场状态：{market['status']}，情绪评分：{market['score']}/100\n"
        f"成交额：{market['total_amount']:.0f}亿，上涨{market['up_count']}只，下跌{market['down_count']}只\n"
        f"涨停{market['limit_up']}只，跌停{market['limit_down']}只\n"
        f"情绪阶段：{sentiment['stage']}\n"
        f"强势行业：{'、'.join(industry.get('active_boards', [])[:5])}\n"
        f"强势概念：{'、'.join(concept.get('active_boards', [])[:5])}\n"
        f"请用2-3句话总结今天市场整体情况，用简洁专业的交易员语气，面向新手可理解。"
    )


def build_strategy_prompt(trade_date, market, sentiment, selectors):
    prompt = (
        f"日期：{trade_date}\n"
        f"市场情绪评分：{market['score']}/100，状态：{market['status']}\n"
        f"情绪阶段：{sentiment['stage']}\n\n"
        f"请按以下三个场景给出明日应对建议（简洁，每个场景2-3句话，适合新手阅读）：\n"
        f"1. 市场放量上涨 → 应对方式\n"
        f"2. 市场缩量震荡 → 应对方式\n"
        f"3. 市场走弱 → 应对方式\n"
        f"\n注意：不构成投资建议，用观察、关注、等待等中性词汇。"
    )
    return prompt


# ── 板块表格渲染 ──

def render_board_table(df, max_rows=10):
    if df is None or df.empty:
        return "暂无数据\n"
    lines = []
    for _, row in df.head(max_rows).iterrows():
        name = row.get("board_name", "-")
        pct = fmt_pct(row.get("pct_chg", np.nan))
        turnover = row.get("turnover", np.nan)
        leader = row.get("leader", "-")
        leader_pct = row.get("leader_pct_chg", np.nan)
        lines.append(f"| {name} | {pct} | 换手{fmt_num(turnover, 2)} | {leader} {fmt_pct(leader_pct)} |")
    return "\n".join(lines) + "\n"


def render_ratio_change_table(ratio_df, max_rows=10):
    if ratio_df is None or ratio_df.empty:
        return "暂无历史数据，需积累3-5个交易日\n"

    # 检查成交额数据是否可用
    if "ratio_today" in ratio_df.columns and ratio_df["ratio_today"].notna().sum() == 0:
        return "板块成交额暂缺，无法展示成交占比变化\n"

    lines = []
    for _, row in ratio_df.head(max_rows).iterrows():
        name = row.get("board_name", "-")
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


def render_market(market):
    lines = ["## 大盘总览", ""]
    lines.append("### 三大指数")
    indices = market.get("indices", [])
    if indices:
        lines.append("| 指数 | 收盘 | 涨跌幅 | 开盘 | 最高 | 最低 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for item in indices:
            lines.append(
                f"| {item['name']} | {fmt_num(item.get('close'))} | "
                f"{fmt_pct(item.get('pct_chg'))} | {fmt_num(item.get('open'))} | "
                f"{fmt_num(item.get('high'))} | {fmt_num(item.get('low'))} |"
            )
    else:
        lines.append("指数数据暂缺")
    lines.append("")
    lines.append(f"成交额：{market['total_amount']:.0f}亿")
    lines.append("")
    lines.append("### 涨跌统计")
    lines.append(f"- 上涨：{market['up_count']}只")
    lines.append(f"- 下跌：{market['down_count']}只")
    lines.append(f"- 平盘：{market['flat_count']}只")
    lines.append(f"- 涨停：{market['limit_up']}只")
    lines.append(f"- 跌停：{market['limit_down']}只")
    lines.append(f"- 20cm涨停：{market['limit_up_20cm']}只")
    lines.append(f"- 20cm跌停：{market['limit_down_20cm']}只")
    lines.append("")
    lines.append(f"市场情绪评分：{market['score']} / 100，状态：{market['status']}")
    lines.append("")
    lines.append(f"简评：{market['summary']}")
    lines.append("")
    return "\n".join(lines)


# ── 观察池渲染 ──

def render_stock_pool_beginner(df, pool_label):
    """小白版：每只股票展示入选原因/风险原因/风险等级/操作信号"""
    if df is None or df.empty:
        return f"暂无符合条件个股\n"

    lines = []
    lines.append(f"### {pool_label}")
    lines.append("")

    for idx, row in df.reset_index(drop=True).iterrows():
        risk_level = row.get("risk_level", "数据不足")
        action_signal = row.get("action_signal", "数据不足")
        signal_emoji = {"观察": "[观察]", "谨慎": "[谨慎]", "回避": "[回避]", "数据不足": "[数据不足]"}.get(action_signal, "")
        risk_emoji = {"低": "[低]", "中": "[中]", "高": "[高]"}.get(risk_level, "")

        lines.append(f"**{idx + 1}. {row['name']}（{row['code']}）** {signal_emoji} {action_signal} | {risk_emoji} {risk_level}风险")
        lines.append("")

        # 基本信息
        lines.append(f"- 收盘：{fmt_num(row['close'])} | 涨幅：{fmt_pct(row['pct_chg'])} | 量比：{fmt_num(row.get('volume_ratio', np.nan))}")
        turnover_val = row.get("turnover", np.nan)
        lines.append(f"- 换手率：{fmt_num(turnover_val, 2)}% | 5日涨幅：{fmt_pct(row.get('pct_5d', np.nan), 1)} | 20日涨幅：{fmt_pct(row.get('pct_20d', np.nan), 1)}")
        lines.append(f"- MA5：{fmt_num(row.get('ma5', np.nan))} | MA10：{fmt_num(row.get('ma10', np.nan))} | MA20：{fmt_num(row.get('ma20', np.nan))}")

        # 观察区间（使用新字段，兼容旧字段）
        o_low = row.get("observe_low", row.get("buy_low", "-"))
        o_high = row.get("observe_high", row.get("buy_high", "-"))
        p_price = row.get("pressure_price", row.get("target", "-"))
        i_price = row.get("invalid_price", row.get("stop_loss", "-"))
        lines.append(f"- 观察区间：{o_low} ~ {o_high} | 参考压力位：{p_price} | 风险失效位：{i_price}")
        lines.append(f"- 持仓观察周期：{row.get('hold_days', '-')}")

        lines.append("")

        # 入选原因
        entry_reason = row.get("entry_reason", row.get("reason", ""))
        lines.append(f"**入选原因**：{entry_reason}")
        lines.append("")

        # 风险原因
        risk_reasons = row.get("risk_reasons", "")
        if risk_reasons:
            lines.append(f"**风险原因**：")
            lines.append(risk_reasons)
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def render_stock_pool_pro(df):
    """专业版：保留原格式，追加风险等级和操作信号"""
    if df is None or df.empty:
        return "暂无符合条件个股\n"

    lines = []

    for idx, row in df.reset_index(drop=True).iterrows():
        risk_level = row.get("risk_level", "")
        action_signal = row.get("action_signal", "")
        extra = ""
        if risk_level and action_signal:
            extra = f" | 风险：{risk_level} | 信号：{action_signal}"

        lines.append(f"{idx + 1}. {row['name']}({row['code']}) — {row['strategy']}{extra}")
        lines.append(f"收盘：{row['close']} | 涨幅：{fmt_pct(row['pct_chg'])} | 量比：{row['volume_ratio']}")
        lines.append(
            f"MA5：{fmt_num(row.get('ma5', np.nan))} | MA10：{fmt_num(row.get('ma10', np.nan))} | MA20：{fmt_num(row.get('ma20', np.nan))} | "
            f"5日涨幅：{fmt_pct(row.get('pct_5d', np.nan), 1)} | 20日涨幅：{fmt_pct(row.get('pct_20d', np.nan), 1)}"
        )
        buy_low = row.get("buy_low", row.get("observe_low", "-"))
        buy_high = row.get("buy_high", row.get("observe_high", "-"))
        target = row.get("target", row.get("pressure_price", "-"))
        stop_loss = row.get("stop_loss", row.get("invalid_price", "-"))
        lines.append(f"区间：{buy_low}~{buy_high} | 参考压力位：{target} | 风险失效位：{stop_loss}")
        lines.append(f"持仓周期：{row['hold_days']} | 仓位：{row.get('position', '-')}")
        lines.append(f"入选原因：{row.get('entry_reason', row.get('reason', ''))}")
        risk_reasons = row.get("risk_reasons", "")
        if risk_reasons:
            lines.append(f"风险原因：{risk_reasons.replace(chr(10), '；')}")
        lines.append("")

    return "\n".join(lines)


# ── 数据质量渲染 ──

def render_quality_check(quality):
    lines = ["## 数据质量检查", ""]
    lines.append("| 检查项 | 状态 | 说明 |")
    lines.append("|---|---|---|")
    for item in quality["items"]:
        lines.append(f"| {item['item']} | {item['status']} | {item['detail']} |")
    lines.append("")
    lines.append(f"**报告可信度：{quality['confidence_score']} / 100**")
    if quality["confidence_score"] < 60:
        lines.append("")
        lines.append("> 今日数据完整性较低，报告仅供参考，不建议据此做交易判断。")
    if quality["issues"]:
        lines.append("")
        lines.append("**扣分/问题项：**")
        for issue in quality["issues"]:
            lines.append(f"- {issue}")
    lines.append("")
    return "\n".join(lines)


# ── 主线判断渲染 ──

def render_themes(themes):
    lines = ["## 今日主线判断", ""]
    if not themes:
        lines.append("今日主线判断：**暂不明确**")
        lines.append("")
        lines.append("原因：热点比较分散，没有板块同时满足涨幅靠前和成交占比连续上升，观察池个股分布较散。")
        lines.append("")
        lines.append("> 这种情况下不适合强行判断主线，应该多观察，少追高。")
        lines.append("")
        return "\n".join(lines)

    for i, theme in enumerate(themes):
        lines.append(f"### {i + 1}. {theme['name']}（{theme['board_type']}）")
        lines.append(f"- **主线强度**：{theme['level']}（评分 {theme['score']}）")
        lines.append(f"- **判断依据**：")
        for r in theme["reasons"]:
            lines.append(f"  - {r}")
        lines.append(f"- **小白解释**：{theme['beginner_explain']}")
        lines.append(f"- **持续性风险**：{theme['sustainability_risk']}")
        lines.append("")
    return "\n".join(lines)


# ── 小白版完整报告 ──

def render_beginner_report(
    trade_date, data_status, quality, market, industry, concept,
    sentiment, selectors, themes, board_ratio_changes=None,
):
    date_display = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

    lines = []
    lines.append(f"# A股每日复盘报告 · 小白友好版")
    lines.append(f"**日期：{date_display}**")
    lines.append("")
    lines.append("> 注意：本报告只基于公开行情数据和规则筛选生成，不构成投资建议。以下内容仅为基于数据规则筛选出的观察标的。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 数据质量检查
    lines.append(render_quality_check(quality))
    lines.append("---")
    lines.append("")

    # 2. 今日市场一句话结论（AI）
    lines.append("## 今日市场一句话结论")
    lines.append("")
    one_line_prompt = build_one_line_prompt(date_display, market, sentiment, industry, concept)
    ai_one_line = call_minimax(one_line_prompt)
    if ai_one_line:
        lines.append(ai_one_line)
    else:
        score = market["score"]
        if score >= 60:
            lines.append(f"今天市场整体偏强，成交额{market['total_amount']:.0f}亿，上涨{market['up_count']}只。热门方向较活跃，但部分个股涨幅较大，明天需要防止追高。")
        elif score >= 45:
            lines.append(f"今天市场处于震荡平衡状态，成交额{market['total_amount']:.0f}亿，上涨{market['up_count']}只。板块轮动较快，适合观察，不适合重仓操作。")
        else:
            lines.append(f"今天市场偏弱，成交额{market['total_amount']:.0f}亿，下跌{market['down_count']}只。亏钱效应较明显，应优先控制风险，等待情绪修复。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 3. 市场情绪
    lines.append("## 市场情绪")
    lines.append("")
    lines.append(f"- 市场情绪评分：**{sentiment['score']} / 100**")
    lines.append(f"- 当前状态：**{sentiment['stage']}**")
    lines.append(f"- 小白解释：{explain_market_status(sentiment['score'])}")
    lines.append("")

    # 关键数据
    lines.append(f"- 成交额：{market['total_amount']:.0f}亿")
    lines.append(f"- 上涨：{market['up_count']}只 / 下跌：{market['down_count']}只")
    lines.append(f"- 涨停：{market['limit_up']}只 / 跌停：{market['limit_down']}只")
    lines.append("")

    # 防误操作提示
    if market["score"] < 45:
        lines.append("> **风险提示**：当前市场偏弱，不适合追高。所有观察池仅供学习复盘。")
        lines.append("")
    if market["limit_down"] >= 50:
        lines.append("> **风险提示**：跌停数量较多，说明市场亏钱效应较强。今日观察池只适合学习复盘。")
        lines.append("")
    lines.append("---")
    lines.append("")

    # 4. 今日主线判断
    lines.append(render_themes(themes))
    lines.append("---")
    lines.append("")

    # 5. 今日风险方向
    lines.append("## 今日风险方向")
    lines.append("")
    if industry and industry.get("top_loss") is not None and not industry["top_loss"].empty:
        top_loss_names = industry["top_loss"]["board_name"].head(5).tolist()
        lines.append(f"- **跌幅靠前行业**：{'、'.join(top_loss_names)}")
    if concept and concept.get("top_loss") is not None and not concept["top_loss"].empty:
        top_loss_concepts = concept["top_loss"]["board_name"].head(5).tolist()
        lines.append(f"- **跌幅靠前概念**：{'、'.join(top_loss_concepts)}")
    lines.append(f"- **跌停数量**：{market['limit_down']}只" + ("，亏钱效应较强" if market['limit_down'] >= 30 else ""))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 6. 今日观察池
    lines.append("## 今日观察池")
    lines.append("")
    if not quality.get("has_volume_ratio", True):
        lines.append("> **注意**：当前数据源缺少量比字段，量比相关筛选已自动降级，本观察池可信度下降。")
        lines.append("")
    lines.append("> 以下标的为基于数据规则筛选的观察对象，风险等级和操作信号仅供参考。")
    lines.append("")

    pool_sections = [
        ("一次起爆", "一次起爆观察池"),
        ("N字异动", "N字异动观察池"),
        ("二次起爆", "二次起爆观察池"),
        ("板块联动", "板块联动观察池"),
        ("短线强势", "短线强势观察池"),
    ]
    for pool_key, label in pool_sections:
        pool_df = selectors.get(pool_key)
        lines.append(render_stock_pool_beginner(pool_df, label))
    lines.append("---")
    lines.append("")

    # 7. 明日策略（AI）
    lines.append("## 明日策略")
    lines.append("")
    strategy_prompt = build_strategy_prompt(date_display, market, sentiment, selectors)
    ai_strategy = call_minimax(strategy_prompt)
    if ai_strategy:
        lines.append(ai_strategy)
    else:
        lines.append("| 明日场景 | 判断信号 | 应对方式 |")
        lines.append("|---|---|---|")
        lines.append("| 市场放量上涨 | 指数上涨、成交额放大、上涨家数增加 | 观察主线方向的分歧低吸机会 |")
        lines.append("| 市场缩量震荡 | 成交额下降、热点轮动快 | 少追高，轻仓观察 |")
        lines.append("| 市场走弱 | 跌停增加、情绪评分下降 | 降低风险，优先学习复盘 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 8. 今日学习概念
    lines.append("## 今日学习概念")
    lines.append("")
    topics = get_daily_learning_topics(market, industry, concept, sentiment, selectors)
    for name, text in topics:
        lines.append(f"### {name}")
        lines.append(f"{text}")
        lines.append("")
    lines.append("---")
    lines.append("")

    # 9. 免责声明
    lines.append("## 免责声明")
    lines.append("")
    lines.append("本报告仅用于数据复盘和学习，不构成任何投资建议。所有观察池标的均为基于公开行情数据的规则筛选结果，观察区间/参考压力位/风险失效位由策略公式生成，不代表未来价格走势。市场有风险，投资需谨慎。")
    lines.append("")
    lines.append(f"> 报告模式：小白友好版 | 数据源：AkShare | 生成时间：{date_display}")

    return "\n".join(lines)


# ── 专业版报告 ──

def render_pro_report(
    trade_date, data_status, quality, market, industry, concept,
    sentiment, selectors, board_ratio_changes=None,
):
    date_display = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    lines = []

    # 数据质量检查
    lines.append(render_quality_check(quality))

    # 原日报结构
    lines.append(f"# A股日报 · 专业版 | {date_display}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 数据获取
    lines.append(f"## 数据获取完成 {date_display}")
    lines.append("")
    lines.append(f"- 个股日线：{data_status.get('stock_count', 0)}只")
    lines.append(f"- 行业板块：{data_status.get('industry_count', 0)}个")
    lines.append(f"- 概念指数：{data_status.get('concept_count', 0)}条")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 大盘总览
    lines.append(render_market(market))
    lines.append("---")
    lines.append("")

    # 行业板块分析
    lines.append(f"## 行业板块分析 | {date_display}")
    lines.append("")
    for title, key in [("行业涨幅 TOP10", "top_gain"), ("行业跌幅 TOP10", "top_loss"),
                       ("行业强度 TOP10", "top_strength"), ("行业活跃度 TOP10", "top_hot")]:
        lines.append(f"### {title}")
        lines.append("| 板块 | 涨幅 | 换手 | 领涨股 |")
        lines.append("|---|---|---|---|")
        lines.append(render_board_table(industry.get(key)))
        lines.append("")

    if board_ratio_changes:
        for label, ratio_key in [
            ("行业成交占比 3日递增 TOP10", "industry_ratio_3d_up"),
            ("行业成交占比 3日递减 TOP10", "industry_ratio_3d_down"),
            ("行业成交占比 5日上升 TOP10", "industry_ratio_5d_up"),
            ("行业成交占比 5日下降 TOP10", "industry_ratio_5d_down"),
        ]:
            df = board_ratio_changes.get(ratio_key)
            if df is not None and not df.empty:
                lines.append(f"### {label}")
                lines.append("| 板块 | 涨幅 | 成交占比 | 变化 |")
                lines.append("|---|---|---|---|")
                lines.append(render_ratio_change_table(df))
                lines.append("")

    lines.append("---")
    lines.append("")

    # 概念板块分析
    lines.append(f"## 概念板块分析 | {date_display}")
    lines.append("")
    for title, key in [("概念涨幅 TOP10", "top_gain"), ("概念跌幅 TOP10", "top_loss"),
                       ("概念强度 TOP10", "top_strength"), ("概念活跃度 TOP10", "top_hot")]:
        lines.append(f"### {title}")
        lines.append("| 板块 | 涨幅 | 换手 | 领涨股 |")
        lines.append("|---|---|---|---|")
        lines.append(render_board_table(concept.get(key)))
        lines.append("")

    if board_ratio_changes:
        for label, ratio_key in [
            ("概念成交占比 3日递增 TOP10", "concept_ratio_3d_up"),
            ("概念成交占比 3日递减 TOP10", "concept_ratio_3d_down"),
            ("概念成交占比 5日上升 TOP10", "concept_ratio_5d_up"),
            ("概念成交占比 5日下降 TOP10", "concept_ratio_5d_down"),
        ]:
            df = board_ratio_changes.get(ratio_key)
            if df is not None and not df.empty:
                lines.append(f"### {label}")
                lines.append("| 板块 | 涨幅 | 成交占比 | 变化 |")
                lines.append("|---|---|---|---|")
                lines.append(render_ratio_change_table(df))
                lines.append("")

    lines.append("---")
    lines.append("")

    # 情绪周期
    lines.append(f"## 情绪周期分析 | {date_display}")
    lines.append("")
    lines.append("### 市场情绪温度计")
    lines.append(f"- 情绪评分：{sentiment['score']} / 100")
    lines.append(f"- 当前阶段：{sentiment['stage']}")
    lines.append(f"- 解读：{sentiment['comment']}")
    lines.append("")
    lines.append("### 行业板块情绪分布")
    lines.append("| 阶段 | 板块数 | 占比 | 分布 |")
    lines.append("|---|---|---|---|")
    lines.append(render_distribution(sentiment["industry_distribution"]))
    lines.append("")
    lines.append("### 概念板块情绪分布")
    lines.append("| 阶段 | 板块数 | 占比 | 分布 |")
    lines.append("|---|---|---|---|")
    lines.append(render_distribution(sentiment["concept_distribution"]))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 观察池（5个）
    if not quality.get("has_volume_ratio", True):
        lines.append("> **注意**：当前数据源缺少量比字段，量比相关筛选已自动降级，本观察池可信度下降。")
        lines.append("")
    pool_sections = [
        ("一次起爆", "观察池 · 一次起爆"),
        ("N字异动", "观察池 · N字异动"),
        ("二次起爆", "观察池 · 二次起爆"),
        ("板块联动", "观察池 · 板块联动"),
        ("短线强势", "观察池 · 短线强势"),
    ]
    for pool_key, header in pool_sections:
        lines.append(f"## {header} | {date_display}")
        lines.append("")
        lines.append(render_stock_pool_pro(selectors.get(pool_key)))
        lines.append("---")
        lines.append("")

    # 风险与机会
    lines.append(f"## 风险与机会 | {date_display}")
    lines.append("")
    lines.append("### 风险提示")
    lines.append("- 若市场情绪评分低于45，应降低仓位，避免追高。")
    lines.append("- 若跌停数量明显增加，说明亏钱效应扩散。")
    lines.append("- 若热点板块连续高潮，次日应警惕分歧。")
    lines.append("")
    lines.append("### 机会方向")
    lines.append("- 优先关注强势行业与强势概念的交集。")
    lines.append("- 优先选择放量但未严重透支的个股。")
    lines.append("- 优先关注站上 MA5/MA10/MA20 且量价配合的标的。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # AI 市场总结与策略
    lines.append(f"## 市场总结与策略 | {date_display}")
    lines.append("")
    ai_prompt = build_ai_prompt(date_display, market, industry, concept, sentiment, selectors)
    ai_prompt += "\n请按以下结构输出分析（不构成投资建议）：\n1. 整体判断\n2. 主线方向分析\n3. 操作建议\n4. 明日策略（分三个场景）"
    ai_result = call_minimax(ai_prompt)
    if ai_result:
        lines.append(ai_result)
    else:
        lines.append("### 一、整体判断")
        lines.append(f"- 当前市场状态：{market['status']}，情绪评分：{market['score']} / 100")
        lines.append("### 二、主线方向")
        lines.append("- 参考行业强度 TOP10 与概念强度 TOP10。")
        lines.append("### 三、操作建议")
        if market["score"] >= 60:
            lines.append("- 市场情绪偏强，可关注主线板块内的分歧机会。")
        elif market["score"] >= 45:
            lines.append("- 市场处于震荡平衡阶段，适合轻仓试错。")
        else:
            lines.append("- 市场偏弱，应控制仓位，等待情绪修复。")
        lines.append("")
        lines.append("### 四、明日策略")
        lines.append("| 场景 | 信号 | 策略 | 仓位 |")
        lines.append("|---|---|---|---|")
        lines.append("| 指数反弹 | 放量上涨且上涨家数增加 | 关注主线低吸 | 3-5成 |")
        lines.append("| 震荡分化 | 热点轮动但成交不足 | 只做核心前排 | 2-3成 |")
        lines.append("| 继续下跌 | 跌停增加且缩量 | 控制风险，等待修复 | 1-2成以下 |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 免责声明
    lines.append("## 免责声明")
    lines.append("")
    lines.append("以上内容仅为量化数据分析和策略复盘，不构成任何投资建议。")
    lines.append("")
    lines.append(f"> 报告模式：专业版 | 数据源：AkShare | 生成时间：{date_display}")

    return "\n".join(lines)


# ── 兼容入口 ──

def render_daily_report(
    trade_date, data_status, market, industry, concept,
    sentiment, selectors, board_ratio_changes=None, mode="beginner",
    quality=None, themes=None,
):
    """统一入口，根据 mode 分发到 beginner 或 pro 渲染"""
    if mode == "pro":
        return render_pro_report(
            trade_date, data_status, quality, market, industry,
            concept, sentiment, selectors, board_ratio_changes,
        )
    else:
        return render_beginner_report(
            trade_date, data_status, quality, market, industry,
            concept, sentiment, selectors, themes, board_ratio_changes,
        )


def save_report(report, trade_date, mode="beginner"):
    out_dir = Path("reports/daily")
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if mode == "beginner" else "_pro"
    path = out_dir / f"daily_report_{trade_date}{suffix}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    return path
