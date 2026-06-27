"""Persist final candidate feature snapshots for future ML training."""
import json
import logging
from datetime import datetime

import numpy as np
import pandas as pd
import psycopg2

from data.config import DATABASE_DSN


logger = logging.getLogger(__name__)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS candidate_feature_snapshot (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    strategy TEXT NOT NULL,
    rule_layer TEXT,
    primary_direction TEXT,

    market_status TEXT,
    market_score NUMERIC,
    trade_mode TEXT,
    position_cap NUMERIC,
    sentiment_score NUMERIC,
    sentiment_stage TEXT,
    data_confidence NUMERIC,

    close_price NUMERIC,
    pct_chg NUMERIC,
    pct_5d NUMERIC,
    pct_20d NUMERIC,
    volume_ratio NUMERIC,
    turnover NUMERIC,
    ma5 NUMERIC,
    ma10 NUMERIC,
    ma20 NUMERIC,

    risk_level TEXT,
    action_signal TEXT,
    entry_reason TEXT,
    risk_reasons TEXT,

    observe_low NUMERIC,
    observe_high NUMERIC,
    pressure_price NUMERIC,
    invalid_price NUMERIC,

    strategy_feedback_score NUMERIC,
    strategy_feedback_status TEXT,
    strategy_feedback_win_rate_1d NUMERIC,
    strategy_feedback_failed_rate NUMERIC,
    strategy_feedback_sample_count INTEGER,

    feature_json JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (trade_date, code, strategy)
)
"""


def _to_sql_date(date_text):
    text = str(date_text or "").strip().replace("-", "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _num(value):
    try:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            return float(value)
        return float(value)
    except Exception:
        return None


def _text(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _trade_mode(trade_plan):
    restrictions = (trade_plan or {}).get("market_restrictions", {})
    max_position = restrictions.get("max_position_pct", 0)
    allow_trade = restrictions.get("allow_real_trade", True)
    try:
        max_position = float(max_position or 0)
    except Exception:
        max_position = 0
    if not allow_trade and max_position <= 0:
        return "空仓"
    if max_position <= 1:
        return "防守"
    return "观察"


def _build_selector_lookup(selector_result):
    lookup = {}
    for pool_name, pool_df in (selector_result or {}).items():
        if pool_df is None or pool_df.empty:
            continue
        for _, row in pool_df.iterrows():
            code = str(row.get("code", ""))
            if not code:
                continue
            lookup[(code, str(pool_name))] = row
            lookup.setdefault((code, ""), row)
    return lookup


def _feature_json(plan_item, selector_row, context):
    payload = {
        "plan": plan_item,
        "context": context,
    }
    if selector_row is not None:
        row_dict = {}
        for key, value in selector_row.to_dict().items():
            if isinstance(value, (np.integer, np.floating)):
                row_dict[key] = value.item()
            elif isinstance(value, (pd.Timestamp, datetime)):
                row_dict[key] = value.isoformat()
            elif isinstance(value, float) and pd.isna(value):
                row_dict[key] = None
            else:
                try:
                    if pd.isna(value):
                        row_dict[key] = None
                    else:
                        row_dict[key] = value
                except Exception:
                    row_dict[key] = value
        payload["selector_row"] = row_dict
    return json.dumps(payload, ensure_ascii=False)


def ensure_table(conn):
    cur = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    cur.close()


def save_candidate_feature_snapshot(
    trade_date,
    trade_plan,
    selector_result,
    market,
    sentiment,
    quality,
    db_conn=None,
):
    """Save final trade_plan candidates as ML-ready feature snapshots."""
    if not DATABASE_DSN and db_conn is None:
        return 0

    conn = db_conn if db_conn is not None and not getattr(db_conn, "closed", False) else None
    close_conn = False
    if conn is None:
        conn = psycopg2.connect(DATABASE_DSN)
        close_conn = True

    try:
        ensure_table(conn)
        selector_lookup = _build_selector_lookup(selector_result)
        restrictions = (trade_plan or {}).get("market_restrictions", {})
        context = {
            "market_status": market.get("status"),
            "market_score": market.get("score"),
            "trade_mode": _trade_mode(trade_plan),
            "position_cap": restrictions.get("max_position_pct"),
            "sentiment_score": sentiment.get("score"),
            "sentiment_stage": sentiment.get("stage") or sentiment.get("status"),
            "data_confidence": quality.get("confidence_score"),
        }

        cur = conn.cursor()
        written = 0
        for rule_layer, items in (trade_plan or {}).get("plans", {}).items():
            for item in items or []:
                code = str(item.get("code", ""))
                strategy = str(item.get("strategy", ""))
                if not code or not strategy:
                    continue
                row = selector_lookup.get((code, strategy))
                if row is None:
                    row = selector_lookup.get((code, ""))
                get = row.get if row is not None else (lambda key, default=None: default)
                close_price = item.get("close", get("close"))
                cur.execute(
                    """
                    INSERT INTO candidate_feature_snapshot (
                        trade_date, code, name, strategy, rule_layer, primary_direction,
                        market_status, market_score, trade_mode, position_cap,
                        sentiment_score, sentiment_stage, data_confidence,
                        close_price, pct_chg, pct_5d, pct_20d, volume_ratio, turnover,
                        ma5, ma10, ma20,
                        risk_level, action_signal, entry_reason, risk_reasons,
                        observe_low, observe_high, pressure_price, invalid_price,
                        strategy_feedback_score, strategy_feedback_status,
                        strategy_feedback_win_rate_1d, strategy_feedback_failed_rate,
                        strategy_feedback_sample_count, feature_json, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, NOW()
                    )
                    ON CONFLICT (trade_date, code, strategy)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        rule_layer = EXCLUDED.rule_layer,
                        primary_direction = EXCLUDED.primary_direction,
                        market_status = EXCLUDED.market_status,
                        market_score = EXCLUDED.market_score,
                        trade_mode = EXCLUDED.trade_mode,
                        position_cap = EXCLUDED.position_cap,
                        sentiment_score = EXCLUDED.sentiment_score,
                        sentiment_stage = EXCLUDED.sentiment_stage,
                        data_confidence = EXCLUDED.data_confidence,
                        close_price = EXCLUDED.close_price,
                        pct_chg = EXCLUDED.pct_chg,
                        pct_5d = EXCLUDED.pct_5d,
                        pct_20d = EXCLUDED.pct_20d,
                        volume_ratio = EXCLUDED.volume_ratio,
                        turnover = EXCLUDED.turnover,
                        ma5 = EXCLUDED.ma5,
                        ma10 = EXCLUDED.ma10,
                        ma20 = EXCLUDED.ma20,
                        risk_level = EXCLUDED.risk_level,
                        action_signal = EXCLUDED.action_signal,
                        entry_reason = EXCLUDED.entry_reason,
                        risk_reasons = EXCLUDED.risk_reasons,
                        observe_low = EXCLUDED.observe_low,
                        observe_high = EXCLUDED.observe_high,
                        pressure_price = EXCLUDED.pressure_price,
                        invalid_price = EXCLUDED.invalid_price,
                        strategy_feedback_score = EXCLUDED.strategy_feedback_score,
                        strategy_feedback_status = EXCLUDED.strategy_feedback_status,
                        strategy_feedback_win_rate_1d = EXCLUDED.strategy_feedback_win_rate_1d,
                        strategy_feedback_failed_rate = EXCLUDED.strategy_feedback_failed_rate,
                        strategy_feedback_sample_count = EXCLUDED.strategy_feedback_sample_count,
                        feature_json = EXCLUDED.feature_json,
                        updated_at = NOW()
                    """,
                    (
                        _to_sql_date(trade_date), code, item.get("name"), strategy,
                        rule_layer, item.get("primary_direction"),
                        context["market_status"], _num(context["market_score"]),
                        context["trade_mode"], _num(context["position_cap"]),
                        _num(context["sentiment_score"]), context["sentiment_stage"],
                        _num(context["data_confidence"]),
                        _num(close_price),
                        _num(item.get("pct_chg", get("pct_chg"))),
                        _num(get("pct_5d")),
                        _num(get("pct_20d")),
                        _num(get("volume_ratio")),
                        _num(get("turnover")),
                        _num(get("ma5")),
                        _num(get("ma10")),
                        _num(get("ma20")),
                        _text(item.get("risk_level", get("risk_level"))),
                        _text(item.get("action_signal", get("action_signal"))),
                        _text(item.get("reason", get("entry_reason"))),
                        _text(item.get("risk_reasons", get("risk_reasons"))),
                        _num(item.get("observe_low", get("observe_low"))),
                        _num(item.get("observe_high", get("observe_high"))),
                        _num(item.get("pressure_price", get("pressure_price"))),
                        _num(item.get("invalid_price", get("invalid_price"))),
                        _num(item.get("feedback_score")),
                        _text(item.get("feedback_status")),
                        _num(item.get("feedback_win_rate_1d")),
                        _num(item.get("feedback_failed_rate")),
                        int(item["feedback_sample_count"]) if item.get("feedback_sample_count") is not None else None,
                        _feature_json(item, row, context),
                    ),
                )
                written += 1
        conn.commit()
        cur.close()
        return written
    except Exception:
        conn.rollback()
        logger.exception("candidate_feature_snapshot 写入失败")
        return 0
    finally:
        if close_conn:
            conn.close()
