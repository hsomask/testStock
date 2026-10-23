"""Email/web integration checks without SMTP or task-ledger writes."""
import os
import sys
import unittest
import tempfile
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from analysis import email_sender


class EmailWebTests(unittest.TestCase):
    def test_link_pins_report_date(self):
        with patch.dict(os.environ, {"WEB_PUBLIC_URL": "http://example.com:8081/"}):
            self.assertEqual(email_sender.web_report_link("20261021"), "http://example.com:8081/?date=20261021")
            self.assertIsNone(email_sender.web_report_link("20260230"))

    def test_invalid_or_secret_url_not_sent(self):
        for value in ("", "javascript:alert(1)", "https://user:pass@example.com", "https://example.com/?token=secret"):
            with patch.dict(os.environ, {"WEB_PUBLIC_URL": value}):
                self.assertIsNone(email_sender.web_report_link("20261021"))

    def test_dry_run_never_starts_ledger(self):
        with patch.object(sys, "argv", ["email_sender", "--dry-run"]), patch.object(
                email_sender, "_main", return_value="dry_run"), patch(
                "analysis.task_ledger.start_task", side_effect=AssertionError("unexpected ledger")):
            self.assertEqual(email_sender.main(), "dry_run")

    def test_real_preview_preserves_same_date_attachments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "daily_report_20261021.md").write_text("# A股每日复盘\n日期：2026-10-21\n", encoding="utf-8")
            (root / "daily_report_20261021_appendix.md").write_text("明细", encoding="utf-8")
            (root / "board_trend_tracker_20261021.xlsx").write_bytes(b"fixture")
            output = StringIO()
            with patch.object(email_sender, "REPORTS_DIR", root), patch.object(sys, "argv", [
                    "email_sender", "--date", "20261021", "--dry-run"]), patch.dict(os.environ, {
                        "WEB_PUBLIC_URL": "http://example.com:8081/"}), patch(
                    "analysis.trade_calendar.is_trade_day", return_value=True), patch(
                    "analysis.task_ledger.start_task", side_effect=AssertionError("ledger")), patch.object(
                    email_sender, "send_email", side_effect=AssertionError("SMTP")), redirect_stdout(output):
                self.assertEqual(email_sender.main(), "dry_run")
            text = output.getvalue()
            self.assertIn("?date=20261021", text)
            self.assertIn("daily_report_20261021_appendix.md", text)
            self.assertIn("board_trend_tracker_20261021.xlsx", text)


if __name__ == "__main__":
    unittest.main()
