"""R1 regression checks for truthful email delivery and report idempotency."""

from contextlib import contextmanager
from unittest.mock import patch

from analysis import daily_report, email_sender


class _SMTPFixture:
    fail = False
    sent = 0

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def login(self, *_args):
        if self.fail:
            raise RuntimeError("smtp fixture failure")

    def sendmail(self, *_args):
        type(self).sent += 1


class _CursorFixture:
    def __init__(self):
        self.calls = []
        self.closed = False

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def close(self):
        self.closed = True


class _ConnectionFixture:
    def __init__(self):
        self.cursor_fixture = _CursorFixture()
        self.commits = 0

    def cursor(self):
        return self.cursor_fixture

    def commit(self):
        self.commits += 1


@contextmanager
def _email_config(**overrides):
    values = {
        "SMTP_HOST": "smtp.example.invalid",
        "SMTP_USER": "sender@example.invalid",
        "SMTP_PASSWORD": "secret",
        "EMAIL_TO": "receiver@example.invalid",
    }
    values.update(overrides)
    with patch.multiple(email_sender, **values):
        yield


def main():
    errors = []

    with _email_config(SMTP_HOST=""):
        if email_sender.send_email("subject", "body") != "skipped_config_missing":
            errors.append("missing SMTP configuration is not reported as skipped_config_missing")

    _SMTPFixture.fail = True
    with _email_config(), patch.object(email_sender.smtplib, "SMTP_SSL", _SMTPFixture):
        if email_sender.send_email("subject", "body") != "failed":
            errors.append("SMTP exception is not reported as failed")

    _SMTPFixture.fail = False
    _SMTPFixture.sent = 0
    with _email_config(), patch.object(email_sender.smtplib, "SMTP_SSL", _SMTPFixture):
        if email_sender.send_email("subject", "body") != "success":
            errors.append("successful SMTP delivery is not reported as success")
        if _SMTPFixture.sent != 1:
            errors.append(f"successful SMTP path sent {_SMTPFixture.sent} messages instead of 1")

    conn = _ConnectionFixture()
    daily_report._persist_daily_report(conn, "20260810", "unified", "first", 0.8)
    daily_report._persist_daily_report(conn, "20260810", "unified", "second", 0.9)
    calls = conn.cursor_fixture.calls
    if len(calls) != 2 or conn.commits != 2:
        errors.append("report persistence did not execute and commit both rerenders")
    elif any("ON CONFLICT (trade_date, report_mode, report_type)" not in sql for sql, _ in calls):
        errors.append("report persistence is not keyed by canonical date/mode/type identity")
    elif calls[-1][1] != ("20260810", "unified", "daily", "second", 0.9):
        errors.append("report rerender did not preserve the legacy payload fields")
    if not conn.cursor_fixture.closed:
        errors.append("report persistence cursor was not closed")

    if errors:
        print("[FAIL] R1 delivery/persistence regression check")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("[OK] R1 delivery/persistence regression check")


if __name__ == "__main__":
    main()
