import unittest
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd

from analysis.learning_experiment import FEATURES, prepare, experiment, fit_predict, fixed_comparison
from analysis import stock_board_mapper


def samples():
    rows = []
    for i, day in enumerate(pd.bdate_range("2026-01-01", periods=40)):
        for code in ("000001", "000002"):
            rows.append({**{f: float(i % 5) for f in FEATURES},
                         "trade_date": day.strftime("%Y%m%d"),
                         "as_of_date": (day + pd.offsets.BDay()).strftime("%Y%m%d"),
                         "code": code, "strategy": "test", "train_eligible": 1,
                         "next_1d_return": 0.01 if code == "000001" else -0.01,
                         "decision_score": 1 if code == "000001" else 0,
                         "base_layer": "候选低吸", "final_layer": "只观察"})
    return pd.DataFrame(rows)


class LearningTests(unittest.TestCase):
    def test_duplicate_strategy_does_not_inflate_stock_count(self):
        data = samples()
        self.assertEqual(len(prepare(pd.concat([data, data]))), len(data))

    def test_empty_corrected_group_is_not_zero_return(self):
        result = fixed_comparison(prepare(samples()))
        self.assertIsNone(result["dates"][0]["corrected_mean"])

    def test_temporal_split_and_future_labels(self):
        data = prepare(samples())
        result, predictions = experiment(data)
        self.assertEqual(result["status"], "shadow_only")
        for fold in result["folds"]:
            self.assertLess(fold["latest_train_label"], fold["test_start"])
        changed = data.copy()
        cutoff = predictions.trade_date.min()
        changed.loc[changed.trade_date >= cutoff, "next_1d_return"] = 999
        _, newer = experiment(changed)
        first_dates = sorted(predictions.trade_date.unique())[:5]
        np.testing.assert_allclose(predictions[predictions.trade_date.isin(first_dates)].prediction,
                                   newer[newer.trade_date.isin(first_dates)].prediction)

    def test_preprocessing_does_not_fit_test_data(self):
        data = prepare(samples())
        train, test = data.iloc[:50], data.iloc[50:52].copy()
        a = fit_predict(train, test)
        other = test.copy()
        other[FEATURES] = 100000
        b = fit_predict(train, pd.concat([test, other]))
        np.testing.assert_allclose(a, b[:2])

    def test_insufficient_dates_does_not_train(self):
        result, _ = experiment(prepare(samples().head(6)))
        self.assertEqual(result["status"], "insufficient_dates")

    def test_board_source_failure_is_reported(self):
        with patch.object(stock_board_mapper, "DATABASE_DSN", "test"), \
             patch.object(stock_board_mapper.psycopg2, "connect", return_value=MagicMock()), \
             patch.object(stock_board_mapper, "update_industry_stock_map", side_effect=RuntimeError("source down")), \
             patch.object(stock_board_mapper, "update_concept_stock_map", return_value=(0,0,0,0,0,0)), \
             patch("builtins.print") as output:
            with self.assertRaisesRegex(RuntimeError, "industry"):
                stock_board_mapper.update_all_stock_board_map()
        self.assertTrue(any("数据源失败数：1" in str(c) for c in output.call_args_list))


if __name__ == "__main__":
    unittest.main()
