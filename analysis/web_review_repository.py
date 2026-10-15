"""Bounded read-only queries for the review workbench. No pipeline imports."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

from analysis.web_review_data import valid_date


def sql_date(day):
    return datetime.strptime(valid_date(day), "%Y%m%d").date()


def json_value(value):
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


class ReviewRepository:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def connection(self):
        conn = psycopg2.connect(self.dsn, connect_timeout=5,
                               application_name="stock_review_readonly")
        try:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '5000ms'")
            yield conn
        finally:
            conn.close()

    def query(self, sql, params=()):
        with self.connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return json_value(cur.fetchall())

    def dates(self):
        return [r["day"].replace("-", "") for r in self.query(
            "SELECT DISTINCT trade_date AS day FROM candidate_feature_snapshot "
            "WHERE trade_date <= CURRENT_DATE ORDER BY day DESC LIMIT 366")]

    def previous_day(self, day):
        rows = self.query(
            "SELECT MAX(calendar_date) AS day FROM exchange_calendar "
            "WHERE exchange='CN_A' AND market_status='open' AND calendar_date < %s",
            (sql_date(day),))
        return rows[0]["day"].replace("-", "") if rows and rows[0]["day"] else None

    def snapshots(self, day, code=None):
        # Select public columns explicitly; feature_json/context may contain internal IDs.
        return self.query(
            "SELECT trade_date, code, name, strategy, canonical_final_layer AS source_layer, "
            "decision_schema_version, market_status, market_score, trade_mode, position_cap, "
            "sentiment_score, sentiment_stage, data_confidence, close_price AS close, pct_chg, "
            "pct_5d, pct_20d, volume_ratio, turnover, ma5, ma10, ma20, primary_direction, "
            "risk_level, entry_reason, risk_reasons, observe_low, observe_high, "
            "pressure_price, invalid_price, feature_json->'plan'->>'display_reason' AS display_reason, "
            "feature_json->'plan'->>'reason' AS reason "
            "FROM candidate_feature_snapshot WHERE trade_date=%s "
            "AND (%s IS NULL OR code=%s) ORDER BY code,strategy LIMIT 2000",
            (sql_date(day), code, code))

    def history(self, code, day):
        return self.query(
            "SELECT trade_date,code,name,strategy,canonical_final_layer AS source_layer, "
            "entry_reason,risk_reasons,observe_low,observe_high,invalid_price, "
            "feature_json->'plan'->>'display_reason' AS display_reason "
            "FROM candidate_feature_snapshot WHERE code=%s AND trade_date<=%s "
            "ORDER BY trade_date DESC,strategy LIMIT 100", (code, sql_date(day)))

    def kline(self, code, day):
        return list(reversed(self.query(
            "SELECT trade_date AS time,name,open,high,low,close,volume,pct_chg,data_source "
            "FROM stock_hist_kline WHERE code=%s AND trade_date<=%s "
            "ORDER BY trade_date DESC LIMIT 120", (code, sql_date(day)))))

    def evaluation(self, day, code=None):
        # Publication cutoff matters: late backfills must not masquerade as known that day.
        return self.query(
            "SELECT r.signal_trade_date,r.code,r.name,r.strategy,r.next_1d_return, "
            "r.target_1d_date,r.is_mature_1d,r.price_status,r.missing_reason, "
            "CASE WHEN r.target_3d_date<=%s AND r.t3_evaluated_at::date<=%s "
            "AND r.is_mature_3d THEN r.next_3d_return ELSE NULL END AS next_3d_return, "
            "s.coverage_1d "
            "FROM canonical_daily_evaluation_result r "
            "JOIN canonical_daily_evaluation_summary s ON s.signal_date=r.signal_trade_date "
            "WHERE r.evaluation_schema_version='evaluation_v2' "
            "AND r.target_1d_date<=%s AND r.signal_trade_date<=%s "
            "AND r.t1_evaluated_at::date<=%s AND (%s IS NULL OR r.code=%s) "
            "ORDER BY r.signal_trade_date DESC,r.code,r.strategy LIMIT 3000",
            (day, sql_date(day), day, day, sql_date(day), code, code))
