"""Offline fault injection for acquisition, publication and notification."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from analysis.acquisition_guard import CN, board_frame, prepare, require_live_day
from analysis.report_publication import publish, record_state
from analysis.web_review_data import DailyArtifactReader
from analysis.web_review_service import ReviewService
from analysis.trade_plan import _market_restrictions


class AcquisitionTests(unittest.TestCase):
    def test_name_only_is_not_quotes(self):
        for frame in (pd.DataFrame(), pd.DataFrame({"board_name": ["测试"], "pct_chg": [None]})):
            result, available = board_frame(lambda: frame)
            self.assertFalse(available)
            self.assertTrue(result.empty)

    def test_disconnect_degrades(self):
        def failed():
            raise ConnectionError("upstream")
        self.assertFalse(board_frame(failed)[1])

    def test_valid_quotes_unchanged(self):
        frame = pd.DataFrame({"board_name": ["测试"], "pct_chg": [1.2]})
        result, available = board_frame(lambda: frame)
        self.assertTrue(available)
        self.assertIs(result, frame)

    def test_retries_have_total_budget(self):
        times = iter([0, 0, 10, 15])
        with patch("analysis.acquisition_guard.require_live_day"), patch("time.sleep") as sleep:
            calls = []
            def execute(command, **kwargs):
                calls.append(kwargs["timeout"])
                return SimpleNamespace(returncode=1)
            self.assertFalse(prepare("20261028", budget=20, execute=execute, clock=lambda: next(times), sleep=sleep))
        self.assertEqual(calls, [20, 5])
        sleep.assert_called_once_with(5)

    def test_timeout_is_degraded(self):
        with patch("analysis.acquisition_guard.require_live_day"):
            def execute(*a, **k):
                raise subprocess.TimeoutExpired("board", 1)
            self.assertFalse(prepare("20261028", execute=execute, sleep=lambda _: None))

    def test_historical_live_quotes_rejected(self):
        now = datetime(2026, 10, 28, 16, tzinfo=CN)
        require_live_day("20261028", now)
        with self.assertRaises(RuntimeError):
            require_live_day("20261027", now)
        with self.assertRaises(RuntimeError):
            require_live_day("20261028", now.replace(hour=10))

    def test_degradation_disables_new_positions_without_changing_score(self):
        market = {"score": 90, "up_count": 4000, "down_count": 1000}
        result = _market_restrictions(market, {"confidence_score": 100, "board_data_unavailable": True})
        self.assertFalse(result["allow_real_trade"])
        self.assertEqual(result["max_position_pct"], 0)
        self.assertEqual(market["score"], 90)

    def test_board_selector_not_called_when_unavailable(self):
        from analysis import selector
        names = ["select_first_breakout", "select_n_latent", "select_n_breakout", "select_short_strong", "select_snowball_trend"]
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(selector, name, return_value=pd.DataFrame()))
            board = stack.enter_context(patch.object(selector, "select_board_linkage"))
            result = selector.run_all_selectors(pd.DataFrame(), board_available=False)
            board.assert_not_called()
            self.assertTrue(result["板块联动"].empty)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.day = "20261028"
        self.summary = {"trade_date": self.day, "themes": [], "quality": {"issues": []}, "market": {
            "score": 90, "up_count": 4000, "down_count": 1000, "limit_up": 60, "limit_down": 2}}
        self.plan = {"trade_date": self.day, "decision": {"schema_version": "daily_decision_v1",
            "mode": {"code": "empty"}, "plans": {}, "restrictions": {"allow_real_trade": False}}}
        self.write("daily_summary", self.summary)
        self.write("trade_plan", self.plan)
        self.write("daily_intelligence", {"trade_date": self.day, "market_read": {"score": 90}})

    def write(self, prefix, data):
        (self.root / f"{prefix}_{self.day}.json").write_text(json.dumps(data), encoding="utf-8")

    def test_publish_valid_and_failed_attempt_preserves_bundle(self):
        self.assertEqual(publish(self.day, self.root), "success")
        record_state(self.day, "running", root=self.root)
        self.write("daily_summary", {"trade_date": self.day})
        with self.assertRaises(ValueError):
            publish(self.day, self.root)
        record_state(self.day, "failed", root=self.root)
        reader = DailyArtifactReader(self.root)
        self.assertEqual(reader.daily(self.day)["market"]["score"], 90)
        self.assertEqual(reader.publication_status()["status"], "failed")

    def test_unpublished_partial_files_not_read(self):
        record_state(self.day, "failed", root=self.root)
        self.assertEqual(DailyArtifactReader(self.root).daily(self.day)["sources"]["summary"], "unpublished")
        self.assertNotIn(self.day, ReviewService(self.root).dates()["dates"])

    def test_mismatch_cannot_publish(self):
        self.write("daily_intelligence", {"trade_date": self.day, "market_read": {"score": 5}})
        with self.assertRaises(ValueError):
            publish(self.day, self.root)
        self.assertFalse((self.root / f"published_{self.day}.json").exists())

    def test_optional_missing_values_are_null_but_core_missing_is_rejected(self):
        self.plan["optional_indicator"] = float("nan")
        self.write("trade_plan", self.plan)
        publish(self.day, self.root)
        bundle = json.loads((self.root / f"published_{self.day}.json").read_text(encoding="utf-8"))
        self.assertIsNone(bundle["artifacts"]["trade_plan"]["optional_indicator"])
        self.summary["market"]["score"] = float("nan")
        self.write("daily_summary", self.summary)
        with self.assertRaises(ValueError):
            publish(self.day, self.root)

    def test_pipeline_to_public_api_without_email(self):
        from analysis import pipeline_runner as runner
        calls = []
        def execute(command, **kwargs):
            calls.append(command)
            if "analysis.report_dispatcher" in command:
                publish(self.day, self.root)
            return SimpleNamespace(returncode=0)
        with patch.dict(os.environ, {"REPORT_DELIVERY": "web"}), patch.object(
                runner, "_pipeline_already_completed", return_value=False), patch.object(
                runner, "start_task", return_value={"run_id": "test"}), patch.object(
                runner, "finish_task"), patch.object(runner, "_evaluation_status", return_value="success"):
            result = runner.run_daily(self.day, executor=execute, calendar_status_getter=lambda _: "open",
                stale_recoverer=lambda *a, **k: None,
                observer=lambda day, status, **kwargs: record_state(day, status, root=self.root, **kwargs))
        self.assertEqual(result["status"], "success")
        self.assertFalse(any("analysis.email_sender" in c for c in calls))
        value = ReviewService(self.root).daily(self.day)
        self.assertEqual(value["market"]["score"], 90)
        self.assertEqual(ReviewService(self.root).dates()["publication"]["status"], "success")

    def test_pipeline_report_failure_leaves_previous_publication(self):
        from analysis import pipeline_runner as runner
        publish(self.day, self.root)
        with patch.dict(os.environ, {"REPORT_DELIVERY": "web"}), patch.object(
                runner, "_pipeline_already_completed", return_value=False), patch.object(
                runner, "start_task", return_value={"run_id": "test"}), patch.object(
                runner, "finish_task"), patch.object(runner, "_evaluation_status", return_value="success"):
            result = runner.run_daily(self.day, calendar_status_getter=lambda _: "open",
                stale_recoverer=lambda *a, **k: None,
                executor=lambda cmd, **k: SimpleNamespace(returncode=1 if "analysis.report_dispatcher" in cmd else 0),
                observer=lambda day, status, **kwargs: record_state(day, status, root=self.root, **kwargs))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(DailyArtifactReader(self.root).daily(self.day)["market"]["score"], 90)
        self.assertEqual(DailyArtifactReader(self.root).publication_status()["status"], "failed")

    def test_degraded_publication_is_explicit(self):
        self.summary["quality"]["board_data_unavailable"] = True
        self.summary["quality"]["issues"] = ["当日板块采集不完整：暂停新增推荐"]
        self.write("daily_summary", self.summary)
        self.assertEqual(publish(self.day, self.root), "partial")
        self.assertEqual(DailyArtifactReader(self.root).publication_status()["status"], "partial")

    def test_rerender_without_market_interpretation_does_not_invent_it(self):
        self.write("daily_intelligence", {"trade_date": self.day, "source": "rendered_report_fallback", "market_read": {}})
        self.assertEqual(publish(self.day, self.root), "success")
        self.assertIsNone(DailyArtifactReader(self.root).intelligence(self.day)["market_read"]["score"])

    def test_notification_disabled_without_side_effects(self):
        from analysis.report_failure_notice import notify
        with patch.dict(os.environ, {"REPORT_FAILURE_EMAIL": "0"}), patch("psycopg2.connect") as conn:
            self.assertEqual(notify(self.day), "disabled")
            conn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
