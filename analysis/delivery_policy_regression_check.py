"""Offline web delivery checks; never sends mail or writes the task ledger."""
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from analysis.delivery_policy import daily_email_enabled
from analysis.daily_reconciliation import _email_status
from analysis import pipeline_runner as runner


class DeliveryTests(unittest.TestCase):
    def test_policy(self):
        with patch.dict(os.environ, {"REPORT_DELIVERY": "web"}):
            self.assertFalse(daily_email_enabled())
            self.assertEqual(_email_status(0, 1), "not_applicable")
        with patch.dict(os.environ, {"REPORT_DELIVERY": "email"}):
            self.assertTrue(daily_email_enabled())
            self.assertEqual(_email_status(0, 1), "missing")
        with patch.dict(os.environ, {"REPORT_DELIVERY": "typo"}):
            with self.assertRaises(ValueError):
                daily_email_enabled()

    def test_direct_email_disabled_before_ledger(self):
        from analysis import email_sender
        with patch.dict(os.environ, {"REPORT_DELIVERY": "web"}), patch.object(
                email_sender, "_main") as send, patch("analysis.task_ledger.start_task") as ledger:
            self.assertEqual(email_sender.main(), "skipped_web_delivery")
            send.assert_not_called()
            ledger.assert_not_called()

    def test_completion_gate(self):
        self.assertTrue(runner._pipeline_completion_gate(False, True, False, False))
        self.assertFalse(runner._pipeline_completion_gate(False, False, False, False))

    def test_web_pipeline_does_not_send_or_check_email(self):
        calls = []
        with patch.dict(os.environ, {"REPORT_DELIVERY": "web"}), patch.object(
                runner, "_pipeline_already_completed", return_value=False), patch.object(
                runner, "start_task", return_value={"run_id": "test"}), patch.object(
                runner, "finish_task"), patch.object(runner, "_email_already_sent") as sent, patch.object(
                runner, "_evaluation_status", return_value="success"):
            result = runner.run_daily("20261028", calendar_status_getter=lambda _: "open",
                stale_recoverer=lambda *a, **k: None,
                executor=lambda command, **k: calls.append(command) or SimpleNamespace(returncode=0))
        self.assertEqual(result["status"], "success")
        self.assertFalse(any("analysis.email_sender" in c for c in calls))
        sent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
