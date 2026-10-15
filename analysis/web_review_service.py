"""Presentation composition; never recomputes strategy scores or final layers."""
from __future__ import annotations

from collections import defaultdict, OrderedDict
from copy import deepcopy
import math
import re
from threading import RLock
from time import monotonic

import psycopg2

from analysis.web_review_data import DailyArtifactReader, board_scope, valid_date
from analysis.web_review_events import EventCache


LAYERS = {"候选低吸", "只观察", "交易条件不满足", "高风险回避", "不可交易过滤"}
MODE_CODES = {"空仓": "empty", "防守": "defensive", "试错": "trial", "进攻": "offensive"}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_code(code):
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise ValueError("Expected a six-digit stock code")
    return code


def group_candidates(rows, day, allowed=False):
    grouped = defaultdict(list)
    for row in rows:
        if board_scope(row.get("code")) != "unsupported":
            grouped[row["code"]].append(row)
    result = []
    for code, matches in grouped.items():
        row = deepcopy(matches[0])
        layers = {r.get("source_layer") for r in matches}
        verified = all(r.get("decision_schema_version") == "daily_decision_v1" for r in matches)
        layer = next(iter(layers)) if len(layers) == 1 else None
        row.update({
            "strategies": list(dict.fromkeys(r.get("strategy") for r in matches if r.get("strategy"))),
            "source_layer": layer, "layer_conflict": len(layers) != 1,
            "board_scope": board_scope(code), "price_reference_date": day,
            "recommendation_eligible": bool(allowed and verified and layer == "候选低吸"
                                             and board_scope(code) == "main_board"),
        })
        result.append(row)
    return result


def continuity(current, previous, previous_day):
    previous_by_code = {row["code"]: row for row in previous}
    current_codes = {row["code"] for row in current}
    result = []
    for row in current:
        item = deepcopy(row)
        old = previous_by_code.get(row["code"])
        item["tracking_state"] = ("continued" if old and old.get("source_layer") == row.get("source_layer")
                                  else "layer_changed" if old else "new" if previous_day else "unknown")
        item["previous_layer"] = old.get("source_layer") if old else None
        result.append(item)
    for code, old in previous_by_code.items():
        if code not in current_codes:
            item = deepcopy(old)
            item.update({"tracking_state": "not_selected", "recommendation_eligible": False,
                         "reference_only": True})
            result.append(item)
    # Continuity determines display order only, not selection scores.
    result.sort(key=lambda r: (r["tracking_state"] == "new", r["tracking_state"] == "not_selected",
                               not r.get("recommendation_eligible", False), r["code"]))
    return result


class ReviewService:
    def __init__(self, daily_dir, repository=None):
        self.files = DailyArtifactReader(daily_dir)
        self.events = EventCache(self.files.root.parent / "events")
        self.repository = repository
        self.cache = OrderedDict()
        self.lock = RLock()

    def _cached(self, key, loader):
        with self.lock:
            cached = self.cache.get(key)
            if cached and monotonic() - cached[0] < 60:
                return deepcopy(cached[1])
            value = loader()
            self.cache[key] = (monotonic(), deepcopy(value))
            self.cache.move_to_end(key)
            while len(self.cache) > 64:
                self.cache.popitem(last=False)
            return value

    def _db(self, method, *args):
        if not self.repository:
            return None
        try:
            return self._cached((method, *args), lambda: getattr(self.repository, method)(*args))
        except (psycopg2.Error, OSError):
            # Do not leak database addresses/credentials into public error responses.
            return None

    def dates(self):
        days = set(self.files.dates())
        db_dates = self._db("dates")
        days.update(db_dates or [])
        return {"dates": sorted(days, reverse=True)[:366],
                "database_status": "available" if db_dates is not None else "unavailable"}

    def _base(self, day):
        value = self.files.daily(day)
        snapshots = self._db("snapshots", day)
        value["sources"]["snapshots"] = "unavailable" if snapshots is None else "available" if snapshots else "missing"
        value["market_scope"] = "full_market" if value["sources"]["summary"] == "available" else "missing"
        value["source_conflict"] = False
        if snapshots:
            scores = {r.get("market_score") for r in snapshots}
            if len(scores) > 1 or (value["market_scope"] == "full_market"
                                  and value["market"].get("score") is not None
                                  and scores != {value["market"]["score"]}):
                value["source_conflict"] = True
                issues = value["quality"].get("issues")
                value["quality"]["issues"] = (issues if isinstance(issues, list) else []) + [
                    "报告与候选快照的市场评分不一致，暂停新增推荐，需核对产物版本。"]
            if value["market_scope"] == "missing":
                first = snapshots[0]
                value["market"].update({"score": first["market_score"], "status": first["market_status"]})
                value["sentiment"] = {"score": first["sentiment_score"], "stage": first["sentiment_stage"]}
                value["quality"] = {"confidence_score": first["data_confidence"],
                                     "issues": ["仅有候选快照，未取得全市场摘要，宽度及板块榜不补写。"]}
                value["market_scope"] = "candidate_snapshot"
            modes = {r.get("trade_mode") for r in snapshots}
            if not value["mode"].get("code") and len(modes) == 1:
                name = next(iter(modes))
                value["mode"] = {"code": MODE_CODES.get(name), "name": name, "summary": None}
            # Snapshot-only recovery is for observation. Execution needs the saved plan.
            allowed = (value["new_recommendations_allowed"]
                       and value["mode"].get("code") != "empty" and not value["source_conflict"])
            if any(r.get("trade_mode") == "空仓" for r in snapshots):
                allowed = False
            value["new_recommendations_allowed"] = allowed
            value["candidates"] = group_candidates(snapshots, day, allowed)
            value["decision_status"] = "canonical_snapshot"
        else:
            for row in value["candidates"]:
                row["decision_schema_version"] = "daily_decision_v1" if value["decision_status"] == "canonical" else None
            value["candidates"] = group_candidates(value["candidates"], day, value["new_recommendations_allowed"])
        return value

    def daily(self, day):
        valid_date(day)
        value = self._base(day)
        previous_day = self._db("previous_day", day)
        previous = self._base(previous_day) if previous_day else None
        previous_available = previous and (previous["sources"]["summary"] == "available"
                                            or previous["sources"]["snapshots"] == "available")
        rows = continuity(value["candidates"], previous["candidates"] if previous_available else [],
                          previous_day if previous_available else None)
        value["tracking"] = rows
        eligible_tracking = [r for r in rows if r["tracking_state"] != "new"
                             or value["new_recommendations_allowed"]]
        # A weak day does not turn today's new candidates into a disguised recommendation.
        value["featured"] = eligible_tracking[:10]
        value["comparison_date"] = previous_day if previous_available else None
        value["market_changes"] = []
        if previous_available and previous["market_scope"] == value["market_scope"] == "full_market":
            for key in ("up_count", "down_count", "limit_up", "limit_down"):
                a, b = value["market"].get(key), previous["market"].get(key)
                if number(a) and number(b):
                    value["market_changes"].append({"field": key, "change": a-b})
        value["recap"] = {"continued": sum(r["tracking_state"] == "continued" for r in rows),
                          "changed": sum(r["tracking_state"] == "layer_changed" for r in rows),
                          "not_selected": sum(r["tracking_state"] == "not_selected" for r in rows),
                          "available": bool(previous_available)}
        value["downloads"] = []
        value["events"] = []
        seen = set()
        for row in value["featured"]:
            for event in self.events.load(row["code"], day)["events"]:
                if event["id"] not in seen:
                    seen.add(event["id"])
                    value["events"].append(event)
        value["events"] = sorted(value["events"], key=lambda e:e["published_at"], reverse=True)[:5]
        value["events_status"] = "available" if value["events"] else "not_collected"
        return value

    def stock(self, code, day):
        valid_code(code)
        valid_date(day)
        bars = self._db("kline", code, day)
        history = self._db("history", code, day)
        rows = self._db("snapshots", day, code)
        evaluations = self._db("evaluation", day, code)
        by_signal = {(r["signal_trade_date"].replace("-", ""), r.get("strategy")): r
                     for r in evaluations or []}
        for item in history or []:
            evaluation = by_signal.get((item["trade_date"].replace("-", ""), item.get("strategy")))
            item["evaluation"] = {key: evaluation.get(key) for key in (
                "next_1d_return", "next_3d_return", "coverage_1d", "price_status", "target_1d_date"
            )} if evaluation else None
        current = group_candidates(rows or [], day)
        name = (current[0].get("name") if current else None) or next(
            (r.get("name") for r in reversed(bars or []) if r.get("name")), None)
        latest = bars[-1] if bars else None
        event_data = self.events.load(code, day)
        explanations = []
        price_note = "历史缓存未逐行记录复权口径，可能混源；K线仅供观察，暂不据此判定旧价格触发或跨期收益。"
        if current:
            row = current[0]
            if (latest and str(latest.get("time", "")).replace("-", "") == day
                    and number(latest.get("close")) and number(row.get("close"))
                    and abs(latest["close"] - row["close"]) > .011):
                price_note = (f"同日价格不一致：K线收盘 {latest['close']:.2f}，"
                              f"候选快照 {row['close']:.2f}；原因待核实，不能混用。" + price_note)
            change = row.get("pct_chg")
            if number(change):
                explanations.append(f"当日涨跌幅 {change:+.2f}%。涨跌是结果，本身不能确认消息驱动。")
            ratio = row.get("volume_ratio")
            if number(ratio):
                explanations.append(f"快照量比 {ratio:.2f}。量比反映相对量能，不能单独证明资金流入或出货。")
            close, ma20 = row.get("close"), row.get("ma20")
            if number(close) and number(ma20):
                relation = "上方" if close > ma20 else "下方" if close < ma20 else "附近"
                explanations.append(f"快照收盘 {close:.2f}，MA20 {ma20:.2f}，处于20日均线{relation}。这是位置证据，不代表下一日涨跌。")
        return {"code": code, "name": name, "trade_date": day, "board_scope": board_scope(code),
                "current": current[0] if current else None, "history": history or [],
                "bars": bars or [], "latest_bar_date": latest.get("time") if latest else None,
                "sources": {"kline": "unavailable" if bars is None else "available" if bars else "missing",
                            "history": "unavailable" if history is None else "available" if history else "missing"},
                "explanations": explanations,
                "price_basis_note": price_note,
                "events": event_data["events"], "events_status": event_data["status"],
                "event_note": "检索命中只是相关线索，不代表涨跌原因。" if event_data["events"] else
                              "没有可用的新闻证据缓存，暂不能确认本次涨跌的事件原因。"}

    def strategies(self, day):
        valid_date(day)
        rows = self._db("evaluation", day)
        if rows is None:
            return {"status": "unavailable", "rows": []}
        dates = sorted({r["signal_trade_date"] for r in rows}, reverse=True)[:20]
        groups = defaultdict(list)
        for row in rows:
            if row["signal_trade_date"] in dates:
                groups[row.get("strategy") or "未分类"].append(row)
        output = []
        for name, samples in groups.items():
            valid = [r["next_1d_return"] for r in samples if r.get("is_mature_1d") is True
                     and number(r.get("next_1d_return")) and number(r.get("coverage_1d")) and r["coverage_1d"] >= .9]
            output.append({"strategy": name, "total": len(samples), "evaluated": len(valid),
                           "avg_return": sum(valid)/len(valid) if valid else None,
                           "win_rate": sum(x > 0 for x in valid)/len(valid) if valid else None})
        return {"status": "available", "rows": output, "signal_dates": dates,
                "definition": "截至所选日期已记录的最近20个信号日；按策略信号统计，覆盖率至少90%且T+1成熟。未计成交条件与成本，不是实盘收益。",
                "comparison_status": "not_implemented"}
