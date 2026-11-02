"""Offline regression checks for automatic mature-price filling."""
import unittest
from unittest.mock import MagicMock, patch

from analysis import evaluation_maturity_backfill as backfill


def target(day="20261028", evaluated=2):
    return {"signal_date": day, "target_3d_date": "20261102",
            "total_signals": 16, "evaluated_3d_before": evaluated}


class MaturePriceTests(unittest.TestCase):
    @patch.object(backfill, "ensure_signal_kline_coverage")
    def test_fill_uses_t3_date_and_skips_complete_targets(self, fill):
        backfill.fill_target_prices([target(evaluated=16), target()], 300)
        self.assertEqual(fill.call_count, 1)
        self.assertEqual(fill.call_args.args, ("20261028", "20261102"))

    @patch.object(backfill.time, "monotonic", side_effect=[0, 1, 301])
    @patch.object(backfill, "ensure_signal_kline_coverage")
    def test_budget_is_shared(self, fill, clock):
        results = backfill.fill_target_prices([target(), target("20261027")], 300)
        self.assertEqual(fill.call_count, 1)
        self.assertEqual(fill.call_args.kwargs["time_budget"], 299)
        self.assertEqual(results[-1]["status"], "budget_exhausted")

    def test_dry_run_does_not_fill_or_apply(self):
        with patch.object(backfill, "DATABASE_DSN", "test"), \
             patch.object(backfill.psycopg2, "connect"), \
             patch.object(backfill, "load_targets", return_value=[]), \
             patch.object(backfill, "fill_target_prices") as fill, \
             patch.object(backfill, "_apply_target") as apply:
            result = backfill.run("20261102")
        fill.assert_not_called()
        apply.assert_not_called()
        self.assertEqual(result["price_fills"], [])

    def test_fill_precedes_cache_read_and_t3_evaluation(self):
        events = []
        conn = MagicMock()
        with patch.object(backfill, "DATABASE_DSN", "test"), \
             patch.object(backfill.psycopg2, "connect", return_value=conn), \
             patch.object(backfill, "load_targets", return_value=[target()]), \
             patch.object(backfill, "fill_target_prices", side_effect=lambda *a: events.append("fill") or []), \
             patch.object(backfill, "fetch_signals_for_date", return_value=[{"code": "000001"}]), \
             patch.object(backfill, "prime_history_cache_from_db", side_effect=lambda *a: events.append("cache")), \
             patch.object(backfill, "evaluate_records", return_value=([], None, None, None, 16, None)) as evaluate, \
             patch.object(backfill, "aggregate_metrics", return_value={}), \
             patch.object(backfill, "_apply_target", return_value=14):
            result = backfill.run("20261102", apply=True)
        self.assertEqual(events, ["fill", "cache"])
        self.assertEqual(evaluate.call_args.kwargs["horizon"], "t3")
        self.assertEqual(result["targets"][0]["evaluated_3d_after"], 16)
        conn.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
