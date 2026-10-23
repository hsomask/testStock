"""Offline regression checks for public daily artifact reading."""
import json
import tempfile
import unittest
from pathlib import Path

from analysis.web_review_data import DailyArtifactReader


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reader = DailyArtifactReader(self.root)
        self.day = "20261013"

    def write(self, prefix, value):
        path = self.root / f"{prefix}_{self.day}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def plan(self, mode="offensive"):
        return {"trade_date": self.day, "market_restrictions": {"allow_real_trade": True},
                "decision": {"schema_version": "daily_decision_v1", "mode": {"code": mode},
                             "execution": {"execution_allowed": True},
                             "plans": {"候选低吸": [{"code": "600000"}, {"code": "300001"}]}}}

    def test_no_fabricated_market_or_recommendations_when_missing(self):
        value = self.reader.daily(self.day)
        self.assertIsNone(value["market"]["up_count"])
        self.assertFalse(value["new_recommendations_allowed"])
        self.assertEqual(value["sources"]["summary"], "missing")

    def test_canonical_and_research_scope(self):
        self.write("trade_plan", self.plan())
        rows = self.reader.daily(self.day)["candidates"]
        self.assertTrue(rows[0]["recommendation_eligible"])
        self.assertFalse(rows[1]["recommendation_eligible"])
        self.assertEqual(rows[1]["board_scope"], "research_only")

    def test_empty_mode_blocks_even_if_execution_flag_conflicts(self):
        self.write("trade_plan", self.plan("empty"))
        result = self.reader.daily(self.day)
        self.assertFalse(result["new_recommendations_allowed"])
        self.assertEqual(len(result["candidates"]), 2)
        self.assertFalse(any(r["recommendation_eligible"] for r in result["candidates"]))

    def test_legacy_is_not_promoted(self):
        value = self.plan()
        value["plans"] = value.pop("decision")["plans"]
        self.write("trade_plan", value)
        result = self.reader.daily(self.day)
        self.assertEqual(result["decision_status"], "unverified")
        self.assertFalse(result["new_recommendations_allowed"])

    def test_date_and_path_validation(self):
        for day in ("../../.env", "20260230", "20261013/", "2026-10-13"):
            with self.assertRaises(ValueError):
                self.reader.daily(day)
        self.write("daily_summary", {"trade_date": "20261014"})
        self.assertEqual(self.reader.daily(self.day)["sources"]["summary"], "date_mismatch")

    def test_corrupt_file_and_private_fields(self):
        path = self.write("daily_summary", {"trade_date": self.day, "password": "private",
                                           "market": {"score": 70, "dsn": "private"}})
        self.assertNotIn("private", json.dumps(self.reader.daily(self.day)))
        path.write_text("{bad", encoding="utf-8")
        self.assertEqual(self.reader.daily(self.day)["sources"]["summary"], "invalid")

    def test_nested_objects_cannot_bypass_public_fields(self):
        self.write("daily_summary", {"trade_date": self.day,
                                    "market": {"score": {"password": "hidden"}},
                                    "quality": {"issues": [{"dsn": "hidden"}, "known issue"]}})
        value = self.reader.daily(self.day)
        self.assertIsNone(value["market"]["score"])
        self.assertEqual(value["quality"]["issues"], ["known issue"])

    def test_existing_file_is_not_proof_of_complete_market(self):
        self.write("daily_summary", {"trade_date": self.day, "market": {"score": 70}})
        value = self.reader.daily(self.day)
        self.assertEqual(value["sources"]["summary"], "available")
        self.assertEqual(value["readiness"]["market"], "partial")
        self.assertIn("up_count", value["readiness"]["market_missing_fields"])
        self.assertEqual(value["readiness"]["themes"], "missing")

    def test_empty_themes_and_zero_breadth_are_not_missing(self):
        self.write("daily_summary", {"trade_date": self.day, "themes": [],
                                    "market": dict.fromkeys(("score", "up_count", "down_count", "limit_up", "limit_down"), 0)})
        value = self.reader.daily(self.day)
        self.assertEqual(value["readiness"]["market"], "complete")
        self.assertEqual(value["readiness"]["themes"], "empty")

    def test_non_numeric_market_values_are_missing(self):
        self.write("daily_summary", {"trade_date": self.day, "market": {"up_count": True, "score": "70"}})
        value = self.reader.daily(self.day)
        self.assertIsNone(value["market"]["up_count"])
        self.assertIsNone(value["market"]["score"])


if __name__ == "__main__":
    unittest.main()
