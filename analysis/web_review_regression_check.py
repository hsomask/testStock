"""Offline API and presentation checks; no database or email writes."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

import psycopg2

from analysis.web_review_server import create_app
from analysis.web_review_service import ReviewService, continuity, group_candidates
from analysis.web_review_events import EventCache, normalize_events, safe_url
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


if __name__ == "__main__":
    unittest.main()
