"""Offline API and presentation checks; no database or email writes."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import json
from types import SimpleNamespace

import psycopg2

from analysis.web_review_server import create_app
from analysis.web_review_service import ReviewService, continuity, group_candidates
from analysis.web_review_events import EventCache, normalize_events, safe_url, collect, collect_batch, collect_plan
from analysis.web_review_export import workbook


def snapshot(code="600000", layer="只观察"):
    return {"code": code, "name": "示例", "strategy": "趋势", "source_layer": layer,
            "decision_schema_version": "daily_decision_v1", "trade_mode": "空仓",
            "market_score": 35, "market_status": "弱势", "sentiment_score": 40,
            "sentiment_stage": "退潮", "data_confidence": 80, "close": 10,
            "pct_chg": -2, "volume_ratio": .7, "ma20": 11}


class Repository:
    def dates(self):
        return ["20261014", "20261013"]

    def previous_day(self, day):
        return "20261013"

    def snapshots(self, day, code=None):
        values = [snapshot(), snapshot("300001")]
        if day == "20261013":
            values.append(snapshot("600001"))
        else:
            values.append(snapshot("600002"))
        return [r for r in values if code is None or r["code"] == code]

    def kline(self, code, day):
        return []

    def history(self, code, day):
        return []

    def evaluation(self, day, code=None):
        return [{"signal_trade_date": "20261013", "strategy": "趋势", "is_mature_1d": True,
                 "next_1d_return": -.02, "coverage_1d": 1},
                {"signal_trade_date": "20261013", "strategy": "趋势", "is_mature_1d": True,
                 "next_1d_return": .5, "coverage_1d": .8}]


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ReviewService(Path(self.temp.name), Repository())
        self.client = create_app(self.service).test_client()

    def test_weak_day_keeps_old_not_new_recommendations(self):
        value = self.service.daily("20261014")
        self.assertFalse(value["new_recommendations_allowed"])
        self.assertEqual(value["market_scope"], "candidate_snapshot")
        self.assertIsNone(value["market"]["up_count"])
        self.assertNotIn("600002", [r["code"] for r in value["featured"]])
        exited = next(r for r in value["tracking"] if r["code"] == "600001")
        self.assertEqual(exited["tracking_state"], "not_selected")
        self.assertTrue(exited["reference_only"])

    def test_conflicting_layers_do_not_invent_resolution(self):
        rows = [snapshot(layer="候选低吸"), snapshot(layer="高风险回避")]
        result = group_candidates(rows, "20261014", allowed=True)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["source_layer"])
        self.assertFalse(result[0]["recommendation_eligible"])

    def test_continuity_does_not_mutate_inputs(self):
        rows = [snapshot()]
        original = deepcopy(rows)
        continuity(rows, rows, "20261013")
        self.assertEqual(rows, original)

    def test_no_calendar_means_no_claim_of_new_entry(self):
        rows = continuity([snapshot()], [], None)
        self.assertEqual(rows[0]["tracking_state"], "unknown")

    def test_quality_threshold_excludes_incomplete_evaluation(self):
        result = self.service.strategies("20261014")["rows"][0]
        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(result["total"], 2)
        self.assertAlmostEqual(result["avg_return"], -.02)

    def test_database_error_does_not_expose_connection_string(self):
        def broken():
            raise psycopg2.OperationalError("postgres://private-secret")
        self.service.repository.dates = broken
        response = self.client.get("/api/dates")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private-secret", response.get_data(as_text=True))
        self.assertEqual(response.json["database_status"], "unavailable")

    def test_api_input_validation(self):
        for url in ("/api/daily/20260230", "/api/stock/abc?date=20261014",
                    "/api/stock/600000?date=2026-10-14"):
            self.assertEqual(self.client.get(url).status_code, 400)

    def test_no_write_endpoints_or_directory_exposure(self):
        for method in ("post", "put", "delete", "patch"):
            self.assertEqual(getattr(self.client, method)("/api/dates").status_code, 405)
        for url in ("/.env", "/reports/", "/logs/", "/static/../../.env"):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_headers_and_html(self):
        response = self.client.get("/")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("收盘之后", response.get_data(as_text=True))

    def test_cached_rows_are_not_changed_by_presentation(self):
        self.service.daily("20261014")
        rows = self.service._db("snapshots", "20261014")
        self.assertNotIn("tracking_state", rows[0])

    def test_export_is_public_and_formula_text_is_literal(self):
        from openpyxl import load_workbook
        data = self.service.daily("20261014")
        data["candidates"][0]["name"] = "=1+1"
        data["candidates"][0]["risk_reasons"] = ["风险一", "风险二"]
        book = load_workbook(BytesIO(workbook(data)))
        self.assertEqual(book.active["B2"].data_type, "s")
        self.assertEqual(book.active["M2"].value, "风险一；风险二")
        for kind in ("md", "xlsx"):
            response = self.client.get(f"/api/export/20261014/{kind}")
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(self.client.get("/api/export/20261014/env").status_code, 404)
        self.assertEqual(self.client.get("/api/export/20260230/md").status_code, 400)

    def test_events_cutoff_dedup_and_collection_boundary(self):
        def news(day, url="https://example.com/one"):
            return {"新闻标题": "消息", "新闻链接": url, "发布时间": day}
        rows = [news("2026-10-14 16:00:00"), news("2026-10-14 16:00:00"),
                news("2026-10-15 09:00:00", "https://example.com/future"),
                news("2026-10-14 10:00:00", "javascript:alert(1)")]
        events = normalize_events(rows, "600000", "20261014", "2026-10-15T10:00:00+08:00")
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["after_close"])
        self.assertTrue(events[0]["late_collected"])
        self.assertEqual(normalize_events(rows, "600000", "20261014", "2026-10-14T09:00:00+08:00"), [])
        self.assertIsNone(safe_url("https://user:password@example.com"))

    def test_event_cache_keeps_first_collection_time(self):
        cache = EventCache(Path(self.temp.name) / "events")
        events = normalize_events([{"新闻标题": "消息", "新闻链接": "https://example.com",
                                   "发布时间": "2026-10-14 10:00:00"}],
                                 "600000", "20261014", "2026-10-14T11:00:00+08:00")
        cache.save("600000", "20261014", events, "available", "2026-10-15T11:00:00+08:00")
        self.assertFalse(cache.load("600000", "20261014")["events"][0]["late_collected"])
        with self.assertRaises(ValueError):
            cache.save("../secret", "20261014", [], "empty", "2026-10-14")

    def test_same_day_price_conflict_is_visible(self):
        self.service.repository.kline = lambda code, day: [{"time": "2026-10-14", "close": 9.5}]
        value = self.service.stock("600000", "20261014")
        self.assertIn("同日价格不一致", value["price_basis_note"])
        self.assertIn("9.50", value["price_basis_note"])

    def test_snapshot_conflict_survives_missing_summary_fallback(self):
        self.service.repository.snapshots = lambda day: [snapshot(), {**snapshot("600001"), "market_score": 99}]
        value = self.service._base("20261014")
        self.assertTrue(value["source_conflict"])
        self.assertFalse(value["new_recommendations_allowed"])
        self.assertTrue(any("不一致" in x for x in value["quality"]["issues"]))

    def test_news_timeout_and_empty_results_retain_cache(self):
        cache = EventCache(Path(self.temp.name) / "events")
        events = normalize_events([{"新闻标题": "消息", "新闻链接": "https://example.com",
                                   "发布时间": "2026-10-14 10:00:00"}],
                                 "600000", "20261014", "2026-10-14T11:00:00+08:00")
        cache.save("600000", "20261014", events, "available", "2026-10-14T11:00:00+08:00")
        with patch("analysis.web_review_events.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 1)):
            self.assertEqual(collect("600000", "20261014", cache)["retained"], 1)
        with patch("analysis.web_review_events.subprocess.run", return_value=SimpleNamespace(stdout="[]")):
            self.assertEqual(collect("600000", "20261014", cache)["retained"], 1)
        self.assertEqual(cache.load("600000", "20261014")["events"], events)

    def test_news_budget_stops_remaining_requests(self):
        with patch("analysis.web_review_events.monotonic", side_effect=[0, 0, 121]), patch(
                "analysis.web_review_events.collect", return_value={"status": "available"}) as fetch:
            results = collect_batch(["600000", "600001"], "20261014", None)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(results[1]["status"], "budget_exhausted")

    def test_news_failure_with_unwritable_cache_is_nonfatal(self):
        cache = EventCache(Path(self.temp.name) / "events")
        with patch("analysis.web_review_events.subprocess.run", side_effect=OSError("network")), patch.object(
                cache, "save", side_effect=OSError("disk")):
            self.assertEqual(collect("600000", "20261014", cache)["status"], "cache_unwritable")

    @patch("analysis.web_review_events.collect", return_value={"code": "market", "status": "available"})
    def test_plan_collection_preserves_order_deduplicates_and_bounds(self, _market):
        root = Path(self.temp.name)
        rows = [{"code": "300001"}, {"code": "600002"}, {"code": "600002"}, {"code": "688001"}]
        rows += [{"code": f"600{i:03d}"} for i in range(30)]
        plan = {"trade_date": "20261014", "decision": {"schema_version": "daily_decision_v1",
                "plans": {"只观察": rows}}}
        (root / "trade_plan_20261014.json").write_text(json.dumps(plan), encoding="utf-8")
        with patch("analysis.web_review_events.collect_batch", return_value=[{"status": "available"}]) as batch:
            result = collect_plan("20261014", root, None)
        codes = batch.call_args.args[0]
        self.assertEqual(codes[:3], ["300001", "600002", "600000"])
        self.assertEqual(len(codes), 20)
        self.assertNotIn("688001", codes)
        self.assertEqual(result["status"], "success")
        with patch("analysis.web_review_events.collect_batch", return_value=[{"status": "failed"}]):
            self.assertEqual(collect_plan("20261014", root, None)["status"], "deferred")

    def test_missing_or_legacy_plan_never_fetches(self):
        root = Path(self.temp.name)
        with patch("analysis.web_review_events.collect_batch") as batch:
            self.assertEqual(collect_plan("20261014", root, None)["status"], "skipped")
            (root / "trade_plan_20261014.json").write_text(json.dumps({"trade_date": "20261014",
                "plans": {"只观察": [{"code": "600000"}]}}), encoding="utf-8")
            self.assertEqual(collect_plan("20261014", root, None)["reason"], "canonical_plan_unavailable")
            batch.assert_not_called()

    def test_empty_canonical_plan_still_collects_market(self):
        root = Path(self.temp.name)
        plan = {"trade_date": "20261014", "decision": {
            "schema_version": "daily_decision_v1", "plans": {}}}
        (root / "trade_plan_20261014.json").write_text(json.dumps(plan), encoding="utf-8")
        with patch("analysis.web_review_events.collect", return_value={"status": "empty"}) as fetch, patch(
                "analysis.web_review_events.collect_batch") as batch:
            result = collect_plan("20261014", root, None)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_count"], 0)
        self.assertEqual(fetch.call_args.args[0], "market")
        batch.assert_not_called()

    def test_news_cleanup_keeps_seven_calendar_days_and_unrelated_files(self):
        root = Path(self.temp.name) / "events"
        cache = EventCache(root)
        for day in ("20261016", "20261017", "20261023"):
            cache.save("market", day, [], "empty", "2026-10-23T18:00:00+08:00")
        for name in ("daily_summary_20261001.json", "20260230_market.json", "notes.json"):
            (root / name).write_text("{}", encoding="utf-8")
        self.assertEqual(cache.cleanup("20261023"), {"removed": 1, "failed": 0})
        self.assertTrue((root / "20261017_market.json").exists())
        self.assertTrue((root / "20261023_market.json").exists())
        self.assertTrue((root / "daily_summary_20261001.json").exists())
        self.assertTrue((root / "20260230_market.json").exists())

    def test_news_cache_sets_public_read_permissions(self):
        cache = EventCache(Path(self.temp.name) / "events")
        with patch.object(Path, "chmod", autospec=True) as chmod:
            cache.save("market", "20261014", [], "empty", "2026-10-14T18:00:00+08:00")
        self.assertEqual(chmod.call_args.args[1], 0o644)

    def test_missing_old_news_is_expired(self):
        cache = EventCache(Path(self.temp.name) / "events")
        self.assertEqual(cache.load("market", "20000101")["status"], "expired")

    def test_historical_reason_is_not_todays_recommendation(self):
        self.service.repository.snapshots = lambda day, code=None: []
        self.service.repository.history = lambda code, day: [{"trade_date": "2026-10-13",
            "strategy": "趋势", "entry_reason": "原始突破条件", "source_layer": "只观察"}]
        value = self.service.stock("600000", "20261014")
        self.assertIsNone(value["current"])
        self.assertEqual(value["review"]["reference_date"], "20261013")
        self.assertEqual(value["review"]["status"], "historical_only")
        self.assertEqual(value["review"]["original_reasons"][0]["reason"], "原始突破条件")

    def test_correction_sidecar_is_same_day_and_whitelisted(self):
        evaluation = Path(self.temp.name) / "evaluation"
        evaluation.mkdir()
        daily = Path(self.temp.name) / "daily"
        service = ReviewService(daily, Repository())
        path = evaluation / "correction_effectiveness_20261014.json"
        payload = {"as_of_date": "20261014", "window_dates": ["20261013"],
                   "summary": {"total": 5, "private": "secret"}, "details": [{"private": "secret"}]}
        path.write_text(json.dumps(payload), encoding="utf-8")
        value = service.strategies("20261014")["correction"]
        self.assertEqual(value["status"], "available")
        self.assertIn("不能判断", value["comparison_note"])
        self.assertNotIn("secret", json.dumps(value))
        self.assertEqual(service.strategies("20261015")["correction"]["status"], "missing")
        payload["window_dates"] = ["20261015"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(service.strategies("20261014")["correction"]["status"], "invalid_window")

    def test_market_interpretation_score_conflict_is_not_displayed(self):
        path = Path(self.temp.name) / "daily_intelligence_20261014.json"
        path.write_text(json.dumps({"trade_date": "20261014", "market_read": {"score": 99,
                                   "profit_detail": "冲突解读"}}), encoding="utf-8")
        value = self.service.daily("20261014")["interpretation"]
        self.assertEqual(value["status"], "source_conflict")
        self.assertEqual(value["market_read"], {})

    def test_market_news_theme_link_is_literal_and_date_bound(self):
        root = Path(self.temp.name) / "daily"
        root.mkdir()
        (root / "daily_summary_20261014.json").write_text(json.dumps({"trade_date": "20261014",
            "themes": [{"name": "半导体"}, {"name": "银行"}]}), encoding="utf-8")
        service = ReviewService(root, Repository())
        events = normalize_events([{"新闻标题": "半导体行业发布消息", "新闻链接": "https://example.com/news",
                                   "发布时间": "2026-10-14 16:00:00"}],
                                 "market", "20261014", "2026-10-15T10:00:00+08:00")
        service.events.save("market", "20261014", events, "available", "2026-10-15T10:00:00+08:00")
        value = service.daily("20261014")
        self.assertEqual(len(value["themes"][0]["events"]), 1)
        self.assertEqual(value["themes"][1]["events"], [])
        self.assertTrue(value["market_events"][0]["late_collected"])
        self.assertTrue(value["market_events"][0]["after_close"])
        self.assertEqual(service.daily("20261013")["market_events"], [])

    def test_market_interpretation_mode_conflict_is_not_displayed(self):
        path = Path(self.temp.name) / "daily_intelligence_20261014.json"
        path.write_text(json.dumps({"trade_date": "20261014", "market_read": {
            "score": 35, "mode_name": "进攻", "mode_summary": "不应展示"}}), encoding="utf-8")
        self.assertEqual(self.service.daily("20261014")["interpretation"]["status"], "source_conflict")

    def test_watch_stock_without_signal_explains_only_same_day_price(self):
        self.service.repository.snapshots = lambda day, code=None: []
        self.service.repository.kline = lambda code, day: [{"time": "2026-10-14", "close": 9.5, "pct_chg": -2}]
        value = self.service.stock("600000", "20261014")
        self.assertTrue(any("9.50" in line for line in value["explanations"]))
        self.assertIsNone(value["current"])
        stale = self.service.stock("600000", "20261015")
        self.assertEqual(stale["explanations"], [])

    def test_mixed_snapshot_modes_block_recommendations(self):
        self.service.repository.snapshots = lambda day: [snapshot(), {**snapshot("600001"), "trade_mode": "进攻"}]
        value = self.service._base("20261014")
        self.assertTrue(value["source_conflict"])
        self.assertFalse(value["new_recommendations_allowed"])

    def test_legacy_snapshot_not_called_canonical(self):
        self.service.repository.snapshots = lambda day: [{**snapshot(), "decision_schema_version": "legacy"}]
        self.assertEqual(self.service._base("20261014")["decision_status"], "unverified_snapshot")


if __name__ == "__main__":
    unittest.main()
