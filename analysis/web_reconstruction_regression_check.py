"""Historical reconstruction stays separate from published recommendations."""
import json
import tempfile
import unittest
from pathlib import Path

from analysis.web_review_service import ReviewService


class ReconstructionTests(unittest.TestCase):
    def test_reconstruction_is_selectable_without_recommendations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "daily").mkdir()
            material = root / "reconstructed" / "20261026"
            material.mkdir(parents=True)
            payload = {"trade_date": "20261026", "training_eligible": False,
                       "stocks": [], "indices": [], "stock_count": 0}
            (material / "review.json").write_text(json.dumps(payload), encoding="utf-8")
            service = ReviewService(root / "daily")
            self.assertIn("20261026", service.dates()["dates"])
            result = service.daily("20261026")
            self.assertEqual(result["reconstruction"], payload)
            self.assertFalse(result["new_recommendations_allowed"])
            self.assertEqual(result["publication_status"], "unpublished")
            self.assertEqual(result["featured"], [])
            payload["trade_date"] = "20261027"
            (material / "review.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                service.daily("20261026")


if __name__ == "__main__":
    unittest.main()
