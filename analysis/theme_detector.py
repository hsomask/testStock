"""
今日主线判断模块
综合涨幅榜、成交占比变化、领涨股、观察池命中数判断当日主线方向
"""
import pandas as pd
from analysis.board_alias import normalize_board_name
from analysis.board_classifier import classify_board, get_board_cluster
import numpy as np


def detect_main_themes(
    industry_result,
    concept_result,
    board_ratio_changes=None,
    stock_pools=None,
):
    """
    检测今日主线方向。返回 0-3 个主线方向。

    参数：
        industry_result: analyze_boards 的行业结果
        concept_result: analyze_boards 的概念结果
        board_ratio_changes: get_all_ratio_changes 的成交占比变化
        stock_pools: run_all_selectors 的观察池结果

    返回：
        [
            {
                "name": "机器人",
                "score": 85,
                "level": "强主线",
                "reasons": [...],
                "beginner_explain": "...",
                "sustainability_risk": "..."
            },
            ...
        ]
    """
    themes = []

    # 收集候选板块：行业 + 概念
    candidates = _collect_candidates(industry_result, concept_result, board_ratio_changes)

    if not candidates:
        return []

    # 计算观察池命中
    pool_stocks = _collect_pool_stocks(stock_pools)
    pool_board_names = set()
    for s in pool_stocks:
        if "hot_board_hits" in s and isinstance(s["hot_board_hits"], list):
            pool_board_names.update(s["hot_board_hits"])

    # 板块名称归一化
    for board in candidates:
        raw_name = board.get("board_name", "")
        board["board_name_raw"] = raw_name
        board["board_name"] = normalize_board_name(raw_name)

    candidates = [
        board for board in candidates
        if classify_board(board.get("board_name", "")).category == "industrial"
    ]

    # 计算每个候选板块的观察池命中数
    for board in candidates:
        name = board.get("board_name", "")
        hit_count = 0
        for s in pool_stocks:
            if "hot_board_hits" in s and isinstance(s["hot_board_hits"], list):
                if name in s["hot_board_hits"]:
                    hit_count += 1
        board["pool_hit_count"] = hit_count

    # 为每个候选板块计算主线强度
    for board in candidates:
        score = 0
        reasons = []

        name = board.get("board_name", "")
        board_type = board.get("board_type", "")

        # 1. 涨幅榜
        pct = board.get("pct_chg", np.nan)
        if pd.notna(pct) and pct >= 3:
            score += 20
            reasons.append(f"出现在{board_type}涨幅榜前列（涨幅 {pct:+.1f}%）")
        elif pd.notna(pct) and pct >= 1:
            score += 10
            reasons.append(f"{board_type}涨幅靠前（涨幅 {pct:+.1f}%）")

        # 2. 成交占比 3日上升
        ratio_3d_up = board.get("ratio_3d_up", False)
        if ratio_3d_up:
            score += 25
            reasons.append("成交占比连续 3 日上升")

        # 3. 成交占比 5日上升
        ratio_5d_up = board.get("ratio_5d_up", False)
        if ratio_5d_up:
            score += 25
            reasons.append("成交占比连续 5 日上升")

        # 4. 领涨股涨幅
        leader_pct = board.get("leader_pct_chg", np.nan)
        if pd.notna(leader_pct) and leader_pct >= 8:
            score += 15
            reasons.append(f"领涨股涨幅较高（{leader_pct:+.1f}%）")

        # 5. 观察池命中
        hit_count = board.get("pool_hit_count", 0)
        if hit_count >= 2:
            score += 15
            reasons.append(f"多只个股进入观察池（{hit_count} 只命中）")
        elif hit_count >= 1:
            score += 8
            reasons.append(f"有 {hit_count} 只个股进入观察池")

        # 6. 上涨家数占比
        up_count = board.get("up_count", np.nan)
        down_count = board.get("down_count", np.nan)
        if pd.notna(up_count) and pd.notna(down_count):
            total = up_count + down_count
            if total > 0:
                up_ratio = up_count / total
                if up_ratio >= 0.7:
                    score += 10
                    reasons.append(f"板块内多数个股上涨（{up_ratio:.0%}）")

        # 分级
        if score >= 75:
            level = "强主线"
        elif score >= 55:
            level = "潜在主线"
        elif score >= 35:
            level = "短线热点"
        else:
            continue  # 不满足最低门槛，排除

        # 主线类型
        pct_val = pct if pd.notna(pct) else 0
        if pct_val < 0 and (ratio_3d_up or ratio_5d_up):
            theme_type = "分歧主线"
            # 修正文案：不写"涨幅靠前"
            reasons = [r.replace("涨幅靠前", "资金关注度提升但板块分歧较大")
                        .replace("出现在涨幅榜前列", "成交占比提升但当日下跌")
                        for r in reasons]
        elif pct_val < 0:
            theme_type = "分歧主线"
            reasons = [r.replace("涨幅靠前", "资金关注度提升但板块分歧较大")
                        .replace("出现在涨幅榜前列", "成交占比提升但当日下跌")
                        for r in reasons]
        elif score >= 55 and (ratio_3d_up or ratio_5d_up):
            theme_type = "上涨主线"
        elif hit_count >= 1 and pct_val < 2:
            theme_type = "回流主线"
            reasons.append("前期资金回流，关注持续性")
        else:
            theme_type = "上涨主线"

        # 小白解释
        beginner_explain = _generate_beginner_explain(name, level, score, reasons)

        # 持续性风险
        sustainability_risk = _assess_sustainability(name, ratio_3d_up, ratio_5d_up, pct_val)

        themes.append({
            "name": name,
            "board_type": board_type,
            "score": score,
            "level": level,
            "theme_type": theme_type,
            "reasons": reasons,
            "beginner_explain": beginner_explain,
            "sustainability_risk": sustainability_risk,
        })

    # 按主线簇去重，避免证券/券商/非银金融重复占位。
    deduped = {}
    for theme in themes:
        cluster = get_board_cluster(theme.get("name", "")) or theme.get("name", "")
        candidate = dict(theme)
        candidate["name"] = cluster
        current = deduped.get(cluster)
        if current is None or candidate.get("score", 0) > current.get("score", 0):
            deduped[cluster] = candidate
    themes = list(deduped.values())

    # 排序，取前 3
    themes.sort(key=lambda x: x["score"], reverse=True)
    return themes[:3]


def _collect_candidates(industry_result, concept_result, board_ratio_changes):
    """收集所有候选板块（行业+概念），附带涨幅和成交占比信息"""
    candidates = []

    # 从行业 TOP gainers 和 strength 中收集
    for result, btype in [(industry_result, "行业"), (concept_result, "概念")]:
        if result is None:
            continue
        seen = set()
        for key in ["top_gain", "top_strength", "top_hot"]:
            df = result.get(key)
            if df is None or df.empty:
                continue
            for _, row in df.head(15).iterrows():
                name = row.get("board_name", "")
                if not name or name in seen:
                    continue
                seen.add(name)

                board = {
                    "board_name": name,
                    "board_type": btype,
                    "pct_chg": row.get("pct_chg", np.nan),
                    "up_count": row.get("up_count", np.nan),
                    "down_count": row.get("down_count", np.nan),
                    "leader_pct_chg": row.get("leader_pct_chg", np.nan),
                    "ratio_3d_up": False,
                    "ratio_5d_up": False,
                    "pool_hit_count": 0,
                }
                candidates.append(board)

    # 从成交占比变化数据中补充（只处理 _up 结尾的递增数据）
    if board_ratio_changes:
        for key, ratio_df in board_ratio_changes.items():
            if ratio_df is None or ratio_df.empty:
                continue
            if not key.endswith("_up"):
                continue
            window = 3 if "3d" in key else 5
            for _, row in ratio_df.iterrows():
                name = row.get("board_name", "")
                for c in candidates:
                    if c["board_name"] == name:
                        if window == 3:
                            c["ratio_3d_up"] = True
                        else:
                            c["ratio_5d_up"] = True
                        break

    return candidates


def _collect_pool_stocks(stock_pools):
    """从观察池收集所有股票"""
    stocks = []
    if not stock_pools:
        return stocks
    for pool_name, pool_df in stock_pools.items():
        if pool_df is None or pool_df.empty:
            continue
        for _, row in pool_df.iterrows():
            stocks.append(row.to_dict())
    return stocks


def _generate_beginner_explain(name, level, score, reasons):
    """生成小白解释"""
    if level == "强主线":
        return (
            f"{name}方向今天不仅涨幅靠前，而且资金连续关注，是比较明确的市场焦点。"
            f"如果明天能继续维持，这个方向值得重点观察。"
        )
    elif level == "潜在主线":
        return (
            f"{name}方向今天表现不错，有成为主线的潜力。"
            f"但还需要明天再确认，如果资金继续流入，主线地位会更确定。"
        )
    else:
        return (
            f"{name}方向今天有资金关注，但持续性和强度还不够。"
            f"可以先观察，等信号更明确后再重点关注。"
        )


def _assess_sustainability(name, ratio_3d_up, ratio_5d_up, pct_chg):
    """评估主线持续性风险"""
    risks = []
    if pd.notna(pct_chg) and pct_chg >= 5:
        risks.append("今日涨幅较大，次日可能出现分歧或回调。")
    if not ratio_3d_up and not ratio_5d_up:
        risks.append("成交占比尚未形成连续上升趋势，持续性需要明天确认。")
    if ratio_3d_up and not ratio_5d_up:
        risks.append("3日成交占比上升但5日趋势尚未形成，中期持续性待验证。")
    if not risks:
        risks.append("当前趋势较好，但需持续关注资金流向是否变化。")
    return "；".join(risks)
