"""Public, read-only review application served by Waitress."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from io import BytesIO

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, send_file
from werkzeug.exceptions import HTTPException

from analysis.web_review_repository import ReviewRepository
from analysis.web_review_service import ReviewService


ROOT = Path(__file__).resolve().parents[1]


def create_app(service=None):
    app = Flask(__name__, static_folder=str(ROOT / "web" / "static"), static_url_path="/static")
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 1024
    if service is None:
        load_dotenv(ROOT / ".env")
        # Prefer a dedicated SELECT-only account in deployment.
        dsn = os.getenv("WEB_DATABASE_DSN") or os.getenv("DATABASE_DSN")
        service = ReviewService(ROOT / "reports" / "daily", ReviewRepository(dsn) if dsn else None)

    @app.before_request
    def readonly():
        if request.method not in ("GET", "HEAD"):
            return jsonify(error="read_only", message="此服务仅提供只读查询。"), 405

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ValueError)
    def invalid(_error):
        return jsonify(error="invalid_input", message="日期或股票代码格式不正确。"), 400

    @app.errorhandler(Exception)
    def failure(error):
        if isinstance(error, HTTPException):
            return jsonify(error="request_error", message="请求不可用。"), error.code
        app.logger.error("Review request failed: %s", type(error).__name__)
        return jsonify(error="unavailable", message="数据暂不可用，请稍后重试。"), 503

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "web", "index.html")

    @app.get("/healthz")
    def health():
        return jsonify(status="ok", mode="read_only")

    @app.get("/api/dates")
    def dates():
        return jsonify(service.dates())

    @app.get("/api/daily/<day>")
    def daily(day):
        return jsonify(service.daily(day))

    @app.get("/api/stock/<code>")
    def stock(code):
        return jsonify(service.stock(code, request.args.get("date", "")))

    @app.get("/api/strategies/<day>")
    def strategies(day):
        return jsonify(service.strategies(day))

    @app.get("/api/export/<day>/<kind>")
    def export(day, kind):
        from analysis.web_review_export import markdown, workbook
        if kind not in {"md", "xlsx"}:
            return jsonify(error="unsupported_export"), 404
        data = service.daily(day)
        payload = markdown(data) if kind == "md" else workbook(data)
        mimetype = "text/markdown; charset=utf-8" if kind == "md" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return send_file(BytesIO(payload), mimetype=mimetype, as_attachment=True,
                         download_name=f"web_review_{day}.{kind}")

    return app


def main():
    from waitress import serve
    parser = argparse.ArgumentParser(description="Read-only stock review workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    serve(create_app(), host=args.host, port=args.port, threads=2,
          connection_limit=64, channel_timeout=30, max_request_body_size=1024,
          max_request_header_size=16384)


if __name__ == "__main__":
    main()
