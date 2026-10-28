"""Delivery policy shared by orchestration and reconciliation."""
import os


def daily_email_enabled():
    channel = os.getenv("REPORT_DELIVERY", "email").strip().lower()
    if channel not in {"email", "web"}:
        raise ValueError("REPORT_DELIVERY must be email or web")
    return channel == "email"
