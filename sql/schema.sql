-- 板块成交占比历史表
-- 每个交易日收盘后写入，用于计算 3日/5日成交占比变化
CREATE TABLE IF NOT EXISTS board_amount_ratio (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    board_type VARCHAR(20) NOT NULL,
    board_code VARCHAR(50),
    board_name VARCHAR(100) NOT NULL,
    pct_chg NUMERIC,
    amount NUMERIC,
    amount_ratio NUMERIC,
    turnover NUMERIC,
    up_count INTEGER,
    down_count INTEGER,
    leader_name VARCHAR(100),
    leader_pct_chg NUMERIC,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trade_date, board_type, board_name)
);

CREATE INDEX IF NOT EXISTS idx_board_ratio_date ON board_amount_ratio(trade_date);
CREATE INDEX IF NOT EXISTS idx_board_ratio_type_date ON board_amount_ratio(board_type, trade_date);


-- 个股所属行业/概念映射表
-- 每周更新一次，通过 AkShare 板块成分股接口抓取
CREATE TABLE IF NOT EXISTS stock_board_map (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(100),
    board_type VARCHAR(20) NOT NULL,
    board_name VARCHAR(100) NOT NULL,
    source VARCHAR(50),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (code, board_type, board_name)
);

CREATE INDEX IF NOT EXISTS idx_sbm_code ON stock_board_map(code);
CREATE INDEX IF NOT EXISTS idx_sbm_board ON stock_board_map(board_type, board_name);


-- 每日报告表
-- 存储每次生成的报告内容
CREATE TABLE IF NOT EXISTS daily_report (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    report_mode VARCHAR(20),
    report_type VARCHAR(50),
    content TEXT,
    confidence_score NUMERIC,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- 数据质量日志表
-- 记录每日数据质量检查结果
CREATE TABLE IF NOT EXISTS data_quality_log (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    stock_count INTEGER,
    industry_count INTEGER,
    concept_count INTEGER,
    has_board_amount_ratio BOOLEAN,
    has_stock_board_map BOOLEAN,
    has_3d_history BOOLEAN,
    has_5d_history BOOLEAN,
    ma_missing_ratio NUMERIC,
    confidence_score NUMERIC,
    issues TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- 观察信号表
-- 记录每只观察池个股的风险等级和操作信号
CREATE TABLE IF NOT EXISTS stock_signal (
    id SERIAL PRIMARY KEY,
    signal_id TEXT,
    signal_schema_version TEXT,
    source_run_id TEXT,
    decision_id TEXT,
    decision_schema_version TEXT,
    final_decision_layer TEXT,
    trade_date DATE NOT NULL,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(100),
    strategy VARCHAR(100),
    signal_type VARCHAR(50),
    industry VARCHAR(100),
    concepts TEXT,
    hot_board_hits TEXT,
    close_price NUMERIC,
    pct_chg NUMERIC,
    volume_ratio NUMERIC,
    turnover NUMERIC,
    ma5 NUMERIC,
    ma10 NUMERIC,
    ma20 NUMERIC,
    pct_5d NUMERIC,
    pct_20d NUMERIC,
    observe_low NUMERIC,
    observe_high NUMERIC,
    pressure_price NUMERIC,
    invalid_price NUMERIC,
    risk_level VARCHAR(20),
    action_signal VARCHAR(20),
    entry_reasons TEXT,
    risk_reasons TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trade_date, code, strategy)
);

ALTER TABLE stock_signal
    ADD COLUMN IF NOT EXISTS signal_id TEXT,
    ADD COLUMN IF NOT EXISTS signal_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS source_run_id TEXT,
    ADD COLUMN IF NOT EXISTS decision_id TEXT,
    ADD COLUMN IF NOT EXISTS decision_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS final_decision_layer TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_signal_signal_id
    ON stock_signal(signal_id)
    WHERE signal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_stock_signal_decision_id
    ON stock_signal(decision_id);


-- 任务运行日志表
-- 记录每次 job 的运行状态、耗时、错误信息
CREATE TABLE IF NOT EXISTS job_run_log (
    id SERIAL PRIMARY KEY,
    run_id TEXT,
    run_schema_version TEXT,
    job_name VARCHAR(100) NOT NULL,
    trade_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds NUMERIC,
    error_message TEXT
);

ALTER TABLE job_run_log
    ADD COLUMN IF NOT EXISTS run_id TEXT,
    ADD COLUMN IF NOT EXISTS run_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS metadata_json JSONB;

CREATE UNIQUE INDEX IF NOT EXISTS uq_job_run_log_run_id
    ON job_run_log(run_id)
    WHERE run_id IS NOT NULL;


-- 确保 stock_signal 唯一约束存在（幂等）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_stock_signal_trade_code_strategy'
    ) THEN
        ALTER TABLE stock_signal
        ADD CONSTRAINT uq_stock_signal_trade_code_strategy
        UNIQUE (trade_date, code, strategy);
    END IF;
END $$;


-- 个股历史K线缓存表
-- 按天增量同步，首次全量回填后可避免重复抓取
CREATE TABLE IF NOT EXISTS stock_hist_kline (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    name TEXT,
    open NUMERIC,
    close NUMERIC,
    high NUMERIC,
    low NUMERIC,
    volume NUMERIC,
    pre_close NUMERIC,
    pct_chg NUMERIC,
    amount NUMERIC,
    turnover NUMERIC,
    limit_ratio NUMERIC,
    limit_up_price NUMERIC,
    limit_down_price NUMERIC,
    is_limit_up BOOLEAN,
    is_limit_down BOOLEAN,
    is_touched_limit_up BOOLEAN,
    is_failed_limit_up BOOLEAN,
    data_source TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_hist_kline_code_date ON stock_hist_kline(code, trade_date);

ALTER TABLE stock_hist_kline
    ADD COLUMN IF NOT EXISTS name TEXT,
    ADD COLUMN IF NOT EXISTS pre_close NUMERIC,
    ADD COLUMN IF NOT EXISTS pct_chg NUMERIC,
    ADD COLUMN IF NOT EXISTS amount NUMERIC,
    ADD COLUMN IF NOT EXISTS turnover NUMERIC,
    ADD COLUMN IF NOT EXISTS limit_ratio NUMERIC,
    ADD COLUMN IF NOT EXISTS limit_up_price NUMERIC,
    ADD COLUMN IF NOT EXISTS limit_down_price NUMERIC,
    ADD COLUMN IF NOT EXISTS is_limit_up BOOLEAN,
    ADD COLUMN IF NOT EXISTS is_limit_down BOOLEAN,
    ADD COLUMN IF NOT EXISTS is_touched_limit_up BOOLEAN,
    ADD COLUMN IF NOT EXISTS is_failed_limit_up BOOLEAN,
    ADD COLUMN IF NOT EXISTS data_source TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;


-- 涨停生态个股池
-- 每日记录个股涨停/触板/炸板/连板状态
CREATE TABLE IF NOT EXISTS limitup_stock_pool (
    trade_date DATE NOT NULL,
    code TEXT NOT NULL,
    name TEXT,

    close NUMERIC,
    pct_chg NUMERIC,
    high NUMERIC,
    low NUMERIC,
    pre_close NUMERIC,

    limit_ratio NUMERIC,
    limit_up_price NUMERIC,
    limit_down_price NUMERIC,

    is_limit_up BOOLEAN,
    is_limit_down BOOLEAN,
    is_touched_limit_up BOOLEAN,
    is_failed_limit_up BOOLEAN,

    consecutive_limit_up_count INTEGER,
    limitup_status TEXT,

    data_source TEXT,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (trade_date, code)
);
CREATE INDEX IF NOT EXISTS idx_limitup_pool_date ON limitup_stock_pool(trade_date);
CREATE INDEX IF NOT EXISTS idx_limitup_pool_code_date ON limitup_stock_pool(code, trade_date);


-- 涨停生态每日聚合表
-- 日报直接读取该表，避免主链路临时全市场拉历史K线
CREATE TABLE IF NOT EXISTS limitup_daily_stats (
    trade_date DATE PRIMARY KEY,

    limit_up_count INTEGER,
    limit_down_count INTEGER,

    touched_limit_up_count INTEGER,
    failed_limit_up_count INTEGER,
    failed_limit_up_rate NUMERIC,

    max_consecutive_limit_up INTEGER,
    three_board_plus_count INTEGER,

    yesterday_limit_up_avg_return NUMERIC,
    yesterday_limit_up_win_rate NUMERIC,

    data_source TEXT,
    coverage_ratio NUMERIC,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- 信号表现追踪表
-- 追踪 stock_signal 中每条信号的后续表现
CREATE TABLE IF NOT EXISTS signal_performance (
    id SERIAL PRIMARY KEY,
    signal_id TEXT,
    trade_date DATE NOT NULL,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(100),
    strategy VARCHAR(100),
    signal_close NUMERIC,
    next_trade_date DATE,
    close_t1 NUMERIC,
    close_t3 NUMERIC,
    close_t5 NUMERIC,
    return_t1 NUMERIC,
    return_t3 NUMERIC,
    return_t5 NUMERIC,
    max_high_5d NUMERIC,
    max_return_5d NUMERIC,
    min_low_5d NUMERIC,
    max_drawdown_5d NUMERIC,
    risk_level VARCHAR(20),
    action_signal VARCHAR(20),
    hit_pressure BOOLEAN,
    hit_invalid BOOLEAN,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trade_date, code, strategy)
);

ALTER TABLE signal_performance
    ADD COLUMN IF NOT EXISTS signal_id TEXT;

CREATE INDEX IF NOT EXISTS idx_signal_performance_signal_id
    ON signal_performance(signal_id);


-- 观察池评价明细表
-- 保存每条 signal 的评价结果，通过 upsert 可重复运行
CREATE TABLE IF NOT EXISTS watchlist_evaluation_result (
    id SERIAL PRIMARY KEY,

    eval_mode TEXT NOT NULL,
    eval_start_date TEXT,
    eval_end_date TEXT,
    signal_trade_date TEXT NOT NULL,
    as_of_date TEXT,

    signal_key TEXT NOT NULL,
    signal_id TEXT,
    decision_id TEXT,
    evaluation_run_id TEXT,
    code TEXT NOT NULL,
    name TEXT,
    strategy TEXT,
    watchlist_layer TEXT,
    risk_level TEXT,
    action_signal TEXT,

    entry_close NUMERIC,
    next_1d_return NUMERIC,
    next_3d_return NUMERIC,
    max_3d_return NUMERIC,
    max_3d_drawdown NUMERIC,

    is_mature_1d BOOLEAN,
    is_mature_3d BOOLEAN,
    price_status TEXT,
    missing_reason TEXT,
    verification_tag TEXT,
    feedback_label TEXT,
    feedback_score NUMERIC,
    attribution_tags JSONB,
    attribution_text TEXT,

    confidence_level TEXT,
    conclusion_level TEXT,

    data_source TEXT DEFAULT 'get_stock_history',
    evaluated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE (eval_mode, eval_start_date, eval_end_date, signal_trade_date, signal_key, as_of_date)
);


-- T+1 feedback attribution fields (idempotent migration)
ALTER TABLE watchlist_evaluation_result
    ADD COLUMN IF NOT EXISTS feedback_label TEXT,
    ADD COLUMN IF NOT EXISTS feedback_score NUMERIC,
    ADD COLUMN IF NOT EXISTS attribution_tags JSONB,
    ADD COLUMN IF NOT EXISTS attribution_text TEXT;

ALTER TABLE watchlist_evaluation_result
    ADD COLUMN IF NOT EXISTS signal_id TEXT,
    ADD COLUMN IF NOT EXISTS decision_id TEXT,
    ADD COLUMN IF NOT EXISTS evaluation_run_id TEXT,
    ADD COLUMN IF NOT EXISTS t3_run_id TEXT;

CREATE INDEX IF NOT EXISTS idx_watchlist_evaluation_signal_id
    ON watchlist_evaluation_result(signal_id);

-- Evaluation lifecycle v2: T+1 is frozen; T+3 is an independent maturity patch.
ALTER TABLE watchlist_evaluation_result
    ADD COLUMN IF NOT EXISTS evaluation_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS target_1d_date TEXT,
    ADD COLUMN IF NOT EXISTS target_3d_date TEXT,
    ADD COLUMN IF NOT EXISTS t1_evaluated_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS t3_evaluated_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS t3_price_status TEXT,
    ADD COLUMN IF NOT EXISTS t3_missing_reason TEXT,
    ADD COLUMN IF NOT EXISTS verification_tag_3d TEXT,
    ADD COLUMN IF NOT EXISTS feedback_label_3d TEXT,
    ADD COLUMN IF NOT EXISTS feedback_score_3d NUMERIC,
    ADD COLUMN IF NOT EXISTS attribution_tags_3d JSONB,
    ADD COLUMN IF NOT EXISTS attribution_text_3d TEXT;


-- 迁移旧唯一键（幂等）
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'watchlist_evaluation_result_eval_mode_signal_key_as_of_date_key'
    ) THEN
        ALTER TABLE watchlist_evaluation_result
        DROP CONSTRAINT watchlist_evaluation_result_eval_mode_signal_key_as_of_date_key;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_watchlist_eval_result_scope_signal'
    ) THEN
        ALTER TABLE watchlist_evaluation_result
        ADD CONSTRAINT uq_watchlist_eval_result_scope_signal
        UNIQUE (eval_mode, eval_start_date, eval_end_date, signal_trade_date, signal_key, as_of_date);
    END IF;
END $$;


-- 观察池评价汇总表
-- 保存每次评价任务的 summary 和 diagnostics
CREATE TABLE IF NOT EXISTS watchlist_evaluation_summary (
    id SERIAL PRIMARY KEY,

    eval_mode TEXT NOT NULL,
    eval_start_date TEXT,
    eval_end_date TEXT,
    signal_date TEXT,
    as_of_date TEXT NOT NULL,

    total_signals INTEGER,
    eligible_1d INTEGER,
    evaluated_1d INTEGER,
    eligible_3d INTEGER,
    evaluated_3d INTEGER,
    coverage_1d NUMERIC,
    coverage_3d NUMERIC,
    price_fetch_failed INTEGER,

    avg_next_1d_return NUMERIC,
    win_rate_1d NUMERIC,
    avg_next_3d_return NUMERIC,
    win_rate_3d NUMERIC,
    avg_max_3d_return NUMERIC,
    avg_max_3d_drawdown NUMERIC,

    confidence_level TEXT,
    conclusion_level TEXT,

    layer_inversion_warning BOOLEAN,
    risk_warning BOOLEAN,

    diagnostics_json JSONB,
    summary_json JSONB,

    generated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE (eval_mode, eval_start_date, eval_end_date, signal_date, as_of_date)
);

ALTER TABLE watchlist_evaluation_summary
    ADD COLUMN IF NOT EXISTS evaluation_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS evaluation_phase TEXT,
    ADD COLUMN IF NOT EXISTS run_as_of_date TEXT,
    ADD COLUMN IF NOT EXISTS target_1d_date TEXT,
    ADD COLUMN IF NOT EXISTS target_3d_date TEXT,
    ADD COLUMN IF NOT EXISTS t1_frozen_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS t3_updated_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS evaluation_run_id TEXT,
    ADD COLUMN IF NOT EXISTS t3_run_id TEXT;

-- One lifecycle row per signal date. Prefer v2; legacy fallback uses the
-- earliest T+1 observation instead of a later time-travelled rerun.
CREATE OR REPLACE VIEW canonical_daily_evaluation_summary AS
SELECT DISTINCT ON (signal_date) *
FROM watchlist_evaluation_summary
WHERE eval_mode = 'daily'
ORDER BY
    signal_date,
    CASE WHEN evaluation_schema_version = 'evaluation_v2' THEN 0 ELSE 1 END,
    as_of_date ASC,
    generated_at DESC;

CREATE OR REPLACE VIEW canonical_daily_evaluation_result AS
SELECT r.*
FROM watchlist_evaluation_result r
JOIN canonical_daily_evaluation_summary s
  ON r.eval_mode = 'daily'
 AND r.signal_trade_date = s.signal_date
 AND r.as_of_date = s.as_of_date
WHERE (
    s.evaluation_schema_version = 'evaluation_v2'
    AND r.evaluation_schema_version = 'evaluation_v2'
) OR (
    s.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
    AND r.evaluation_schema_version IS DISTINCT FROM 'evaluation_v2'
);


-- 策略反馈滚动统计表
-- 基于 watchlist_evaluation_result 聚合最近 N 个交易日的策略表现
CREATE TABLE IF NOT EXISTS strategy_feedback_stats (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    strategy TEXT NOT NULL,
    window_days INTEGER NOT NULL,
    sample_count INTEGER,
    win_rate_1d NUMERIC,
    avg_next_1d_return NUMERIC,
    avg_max_3d_return NUMERIC,
    avg_max_3d_drawdown NUMERIC,
    strong_rate NUMERIC,
    failed_rate NUMERIC,
    feedback_score NUMERIC,
    status TEXT,
    reason TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (trade_date, strategy, window_days)
);


-- ML 候选特征快照表
-- 保存日报生成当下的最终 trade_plan 分层和候选特征，用于后续旁路机器学习训练。
CREATE TABLE IF NOT EXISTS candidate_feature_snapshot (
    id SERIAL PRIMARY KEY,
    signal_id TEXT,
    signal_schema_version TEXT,
    source_run_id TEXT,
    decision_id TEXT,
    snapshot_schema_version TEXT,
    decision_schema_version TEXT,
    canonical_final_layer TEXT,
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
);

ALTER TABLE candidate_feature_snapshot
    ADD COLUMN IF NOT EXISTS signal_id TEXT,
    ADD COLUMN IF NOT EXISTS signal_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS source_run_id TEXT,
    ADD COLUMN IF NOT EXISTS decision_id TEXT,
    ADD COLUMN IF NOT EXISTS snapshot_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS decision_schema_version TEXT;
ALTER TABLE candidate_feature_snapshot
    ADD COLUMN IF NOT EXISTS canonical_final_layer TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_snapshot_signal_id
    ON candidate_feature_snapshot(signal_id)
    WHERE signal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_candidate_snapshot_decision_id
    ON candidate_feature_snapshot(decision_id);

-- Canonical strategy-grain lineage. Historical gaps remain visible as NULL
-- snapshot/evaluation ids; they are never filled with hindsight features.
CREATE OR REPLACE VIEW canonical_signal_lineage AS
SELECT
    s.signal_id,
    s.signal_schema_version,
    s.source_run_id,
    s.trade_date,
    s.code,
    s.name,
    s.strategy,
    s.id AS stock_signal_row_id,
    c.id AS snapshot_row_id,
    c.rule_layer,
    c.snapshot_schema_version,
    c.decision_schema_version,
    r.id AS evaluation_row_id,
    r.as_of_date AS evaluation_as_of_date,
    r.evaluation_schema_version,
    s.decision_id,
    s.decision_schema_version AS stock_decision_schema_version,
    s.final_decision_layer,
    c.canonical_final_layer
FROM stock_signal s
LEFT JOIN candidate_feature_snapshot c
  ON c.signal_id = s.signal_id
LEFT JOIN canonical_daily_evaluation_result r
  ON r.signal_id = s.signal_id
WHERE s.signal_id IS NOT NULL;
