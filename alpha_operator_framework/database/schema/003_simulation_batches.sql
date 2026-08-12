-- Version 003: durable multi-simulation batches and per-expression results.
CREATE TABLE IF NOT EXISTS simulation_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_batch_id TEXT UNIQUE, platform_location TEXT, status TEXT NOT NULL DEFAULT 'created',
    settings_json TEXT NOT NULL, requested_count INTEGER NOT NULL DEFAULT 0,
    completed_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0,
    progress_json TEXT, result_json TEXT, error_message TEXT,
    submitted_at TEXT, last_polled_at TEXT, completed_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS simulation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL, sequence_no INTEGER NOT NULL,
    expression_sha TEXT NOT NULL, alpha_sha TEXT NOT NULL, expression TEXT NOT NULL, decay REAL NOT NULL DEFAULT 0.0,
    platform_child_url TEXT, alpha_id TEXT, status TEXT NOT NULL DEFAULT 'created',
    result_json TEXT, error_message TEXT, completed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(batch_id, sequence_no), FOREIGN KEY(batch_id) REFERENCES simulation_batches(id)
);
