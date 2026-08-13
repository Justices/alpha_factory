-- Version 004: durable Super Alpha candidate ledger and recoverable task payloads.
ALTER TABLE simulation_batches ADD COLUMN simulation_type TEXT NOT NULL DEFAULT 'REGULAR';
ALTER TABLE simulation_results ADD COLUMN task_json TEXT NOT NULL DEFAULT '{}';
CREATE TABLE IF NOT EXISTS super_alpha_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_sha TEXT NOT NULL UNIQUE,
    component_ids_json TEXT NOT NULL,
    selection_name TEXT NOT NULL,
    selection TEXT NOT NULL,
    combo_name TEXT NOT NULL,
    combo TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'prepared',
    alpha_id TEXT, result_json TEXT, error_message TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_super_candidate_status ON super_alpha_candidates(status);
