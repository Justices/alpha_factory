-- Version 001: initial SQLite research schema.
CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alpha_expressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expression_sha TEXT NOT NULL UNIQUE,
    expression TEXT NOT NULL,
    settings TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alpha_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alpha_id TEXT NOT NULL UNIQUE,
    expression_sha TEXT NOT NULL,
    expression TEXT NOT NULL,
    region TEXT, universe TEXT, delay INTEGER DEFAULT 1, decay REAL DEFAULT 0.0,
    neutralization TEXT, truncation REAL DEFAULT 0.0,
    sharpe REAL DEFAULT 0.0, fitness REAL DEFAULT 0.0, turnover REAL DEFAULT 0.0,
    margin REAL DEFAULT 0.0, pnl REAL DEFAULT 0.0, returns REAL DEFAULT 0.0,
    drawdown REAL DEFAULT 0.0, long_count INTEGER DEFAULT 0, short_count INTEGER DEFAULT 0,
    grade TEXT, stage_platform TEXT, status_platform TEXT,
    sc_result TEXT, sc_value REAL, pc_result TEXT, pc_value REAL, checks_json TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alpha_checks (
    alpha_id TEXT NOT NULL, check_name TEXT NOT NULL, result TEXT,
    "limit" REAL, value REAL, extra_json TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (alpha_id, check_name)
);

CREATE TABLE IF NOT EXISTS alpha_optimization_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, alpha_id TEXT NOT NULL, expression TEXT NOT NULL,
    sharpe REAL DEFAULT 0.0, fitness REAL DEFAULT 0.0, turnover REAL DEFAULT 0.0, margin REAL DEFAULT 0.0,
    failed_checks TEXT, failed_ra_count INTEGER DEFAULT 0, failed_ppa_count INTEGER DEFAULT 0,
    optimization_hints TEXT, status TEXT DEFAULT 'pending', priority INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alpha_submission_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, alpha_id TEXT NOT NULL UNIQUE, expression TEXT NOT NULL,
    sharpe REAL DEFAULT 0.0, fitness REAL DEFAULT 0.0, turnover REAL DEFAULT 0.0, margin REAL DEFAULT 0.0,
    sc_value REAL, pc_value REAL, local_sc REAL, local_sc_grade TEXT,
    robustness_status TEXT, robustness_notes TEXT, needs_optimization INTEGER DEFAULT 0,
    is_submitted INTEGER DEFAULT 0, submitted_at TEXT, pyramid_category TEXT,
    pyramid_multiplier REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
