"""Release gate tests via real Flask routes, with no network, DB or email writes."""
import json
from pathlib import Path
import tempfile
import unittest

from analysis.web_review_regression_check import Repository
from analysis.web_review_server import create_app
from analysis.web_review_service import ReviewService
from analysis.web_review_smoke import check_release
from analysis.web_review_events import EventCache


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.day = "20261014"
        self.summary = {"trade_date": self.day, "themes": [], "market": {
            "score": 35, "up_count": 10, "down_count": 20, "limit_up": 1, "limit_down": 2}}
        self.plan = {"trade_date": self.day, "decision": {
            "schema_version": "daily_decision_v1", "mode": {"code": "empty"}, "plans": {}}}
        self.write("daily_summary", self.summary)
        self.write("trade_plan", self.plan)
        self.write("daily_intelligence", {"trade_date": self.day, "market_read": {"score": 35}})
        from analysis.report_publication import publish
        publish(self.day, self.root)
        repo = Repository()
        repo.kline = lambda code, day: [{"time": "2026-10-14", "close": 10}]
        repo.history = lambda code, day: [{"trade_date": "20261014", "strategy": "趋势"}]
        service = ReviewService(self.root, repo)
        service.events = EventCache(self.root / "events")
        service.events.save("market", self.day, [], "empty", "2026-10-14T18:00:00+08:00")
        self.client = create_app(service).test_client()

    def write(self, prefix, value):
        (self.root / f"{prefix}_{self.day}.json").write_text(json.dumps(value), encoding="utf-8")

    def fetch(self, path, method="GET"):
        with self.client.open(path, method=method) as response:
            return response.status_code, response.get_data()

    def run_gate(self):
        return check_release("http://localhost:8081", self.day, self.fetch)

    def test_complete_release_passes(self):
        result = self.run_gate()
        self.assertEqual(result["status"], "pass", result)

    def test_process_health_does_not_mask_missing_market(self):
        (self.root / f"published_{self.day}.json").unlink()
        (self.root / f"publication_state_{self.day}.json").unlink()
        self.write("daily_summary", {"trade_date": self.day})
        result = self.run_gate()
        self.assertEqual(result["status"], "fail")
        self.assertIn({"check": "market_complete", "passed": False}, result["checks"])

    def test_canonical_snapshots_do_not_mask_legacy_plan(self):
        (self.root / f"published_{self.day}.json").unlink()
        (self.root / f"publication_state_{self.day}.json").unlink()
        self.write("trade_plan", {"trade_date": self.day, "plans": {}})
        result = self.run_gate()
        self.assertIn({"check": "canonical_plan", "passed": False}, result["checks"])

    def test_expected_date_is_not_replaced_with_latest(self):
        result = check_release("http://localhost:8081", "20261015", self.fetch)
        self.assertEqual(result["status"], "fail")
        self.assertIn({"check": "expected_date_available", "passed": False}, result["checks"])

    def test_errors_do_not_disclose_secrets(self):
        def broken(*args):
            raise OSError("private-connection-secret")
        result = check_release("http://localhost", self.day, broken)
        self.assertEqual(result["status"], "fail")
        self.assertNotIn("private-connection-secret", json.dumps(result))

    def test_unreadable_news_blocks_release(self):
        def fetch(path, method="GET"):
            status, body = self.fetch(path, method)
            if path == f"/api/daily/{self.day}":
                value = json.loads(body)
                value["market_events_status"] = "invalid"
                body = json.dumps(value).encode()
            return status, body
        result = check_release("http://localhost", self.day, fetch)
        self.assertIn({"check": "market_news_readable", "passed": False}, result["checks"])

    def test_invalid_date_and_url_rejected(self):
        for url in ("file:///etc/passwd", "http://user:secret@localhost"):
            with self.assertRaises(ValueError):
                check_release(url, self.day)
        with self.assertRaises(ValueError):
            check_release("http://localhost", "20260230")


if __name__ == "__main__":
    unittest.main()
