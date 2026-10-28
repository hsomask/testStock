"""Read-only release checks against a running web service, never the business pipeline."""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile, BadZipFile

from analysis.web_review_data import valid_date


def check_release(base_url, day, fetch=None):
    valid_date(day)
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid_base_url")
    base_url = base_url.rstrip("/")

    def request(path, method="GET"):
        try:
            with urlopen(Request(base_url + path, method=method), timeout=30) as response:
                return response.status, response.read(8 * 1024 * 1024 + 1)
        except HTTPError as error:
            return error.code, b""

    fetch = fetch or request
    checks = []

    def record(name, passed):
        checks.append({"check": name, "passed": bool(passed)})

    def data(path):
        status, body = fetch(path)
        if status != 200 or len(body) > 8 * 1024 * 1024:
            return {}
        try:
            result = json.loads(body)
            return result if isinstance(result, dict) else {}
        except (ValueError, UnicodeError):
            return {}

    try:
        record("homepage", fetch("/")[0] == 200)
        record("process_health", data("/healthz").get("status") == "ok")
        dates = data("/api/dates")
        record("database_available", dates.get("database_status") == "available")
        record("expected_date_available", day in (dates.get("dates") or []))
        daily = data(f"/api/daily/{day}")
        record("report_date", daily.get("trade_date") == day)
        record("market_complete", daily.get("readiness", {}).get("market") == "complete")
        record("themes_recorded", daily.get("readiness", {}).get("themes") in {"available", "empty"})
        record("canonical_plan", daily.get("sources", {}).get("trade_plan") == "available"
               and daily.get("saved_plan_status") == "canonical")
        record("no_source_conflict", daily.get("source_conflict") is False)
        record("market_news_readable", daily.get("market_events_status") in {"available", "empty", "expired"})
        record("strategy_query", data(f"/api/strategies/{day}").get("status") == "available")
        candidates = daily.get("candidates") or []
        if candidates:
            code = candidates[0].get("code", "")
            stock = data(f"/api/stock/{code}?date={day}")
            record("stock_kline", stock.get("sources", {}).get("kline") == "available")
            record("stock_history", stock.get("sources", {}).get("history") == "available")
        for asset in ("app.js", "app.css", "vendor/lightweight-charts.js", "vendor/lucide.js"):
            record(f"asset:{asset}", fetch("/static/" + asset)[0] == 200)
        status, body = fetch(f"/api/export/{day}/md")
        record("markdown_export", status == 200 and day.encode() in body)
        status, body = fetch(f"/api/export/{day}/xlsx")
        valid_excel = False
        try:
            with ZipFile(BytesIO(body)) as archive:
                valid_excel = "xl/workbook.xml" in archive.namelist()
        except BadZipFile:
            pass
        record("excel_export", status == 200 and valid_excel)
        for path in ("/.env", "/reports/", "/logs/"):
            record(f"private_path:{path}", fetch(path)[0] == 404)
        record("read_only", fetch("/api/dates", "POST")[0] == 405)
    except Exception as error:
        # Exception strings can contain private addresses or connection details.
        checks.append({"check": "request_completed", "passed": False, "error_type": type(error).__name__})
    return {"status": "pass" if all(c["passed"] for c in checks) else "fail",
            "trade_date": day, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--date", required=True, help="Expected completed report date, not necessarily today")
    args = parser.parse_args()
    result = check_release(args.url, args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
