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
    UNIQUE (trade_date, code, strategy)
);


-- 任务运行日志表
-- 记录每次 job 的运行状态、耗时、错误信息
CREATE TABLE IF NOT EXISTS job_run_log (
    id SERIAL PRIMARY KEY,
    job_name VARCHAR(100) NOT NULL,
    trade_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds NUMERIC,
    error_message TEXT
);
