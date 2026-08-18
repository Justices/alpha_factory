-- Fresh SQLite schema snapshot. Version 007. Existing databases use 001--007 migrations.
CREATE TABLE IF NOT EXISTS schema_version (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alpha_expressions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, expression_sha TEXT NOT NULL UNIQUE, expression TEXT NOT NULL,
 expression_origin TEXT NOT NULL DEFAULT '', settings TEXT NOT NULL, batch_id INTEGER,
 fields TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','failed','pruned')),
 first_operator TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alpha_details (
 id INTEGER PRIMARY KEY AUTOINCREMENT, alpha_id TEXT NOT NULL UNIQUE, expression_sha TEXT NOT NULL,
 alpha_sha TEXT NOT NULL DEFAULT '', expression TEXT NOT NULL, region TEXT, universe TEXT, delay INTEGER DEFAULT 1,
 decay REAL DEFAULT 0, neutralization TEXT, truncation REAL DEFAULT 0, sharpe REAL DEFAULT 0, fitness REAL DEFAULT 0,
 turnover REAL DEFAULT 0, margin REAL DEFAULT 0, pnl REAL DEFAULT 0, returns REAL DEFAULT 0, drawdown REAL DEFAULT 0,
 long_count INTEGER DEFAULT 0, short_count INTEGER DEFAULT 0, grade TEXT, stage_platform TEXT, status_platform TEXT,
 wf_stage TEXT NOT NULL DEFAULT 'pending_validation',
 sc_result TEXT, sc_value REAL, pc_result TEXT, pc_value REAL, checks_json TEXT,
 ra_failed INTEGER NOT NULL DEFAULT 0, ppa_failed INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alpha_checks (
 alpha_id TEXT NOT NULL, check_name TEXT NOT NULL, result TEXT, "limit" REAL, value REAL, extra_json TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(alpha_id, check_name));
CREATE TABLE IF NOT EXISTS template_library (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, title TEXT NOT NULL DEFAULT '',
 family TEXT NOT NULL DEFAULT '', template_type TEXT NOT NULL DEFAULT 'placeholder',
 expression_template TEXT NOT NULL, template_index INTEGER NOT NULL DEFAULT 0,
 fields_per_alpha INTEGER NOT NULL DEFAULT 0, expression_origin TEXT NOT NULL DEFAULT '',
 field_types_json TEXT NOT NULL DEFAULT '[]', categories_json TEXT NOT NULL DEFAULT '[]',
 dataset_families_json TEXT NOT NULL DEFAULT '[]', placeholders_json TEXT NOT NULL DEFAULT '{}',
 group_slots_json TEXT NOT NULL DEFAULT '[]', slot_count INTEGER NOT NULL DEFAULT 0,
 description TEXT NOT NULL DEFAULT '', rationale TEXT NOT NULL DEFAULT '',
 example_expression TEXT NOT NULL DEFAULT '', settings_hint_json TEXT NOT NULL DEFAULT '{}',
 field_candidates_json TEXT NOT NULL DEFAULT '{}', operators_used_json TEXT NOT NULL DEFAULT '[]',
 source_json TEXT NOT NULL DEFAULT '{}', active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS datafields (
 field_id TEXT NOT NULL, dataset_id TEXT NOT NULL DEFAULT '', dataset_name TEXT NOT NULL DEFAULT '',
 description TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'MATRIX', region TEXT NOT NULL,
 delay INTEGER NOT NULL DEFAULT 1, universes_json TEXT NOT NULL DEFAULT '[]', coverage REAL DEFAULT 0.0,
 user_count INTEGER DEFAULT 0, alpha_count INTEGER DEFAULT 0, category TEXT NOT NULL DEFAULT '',
 expression_shas_json TEXT NOT NULL DEFAULT '[]',
 last_fetched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (field_id, dataset_id, region, delay));
CREATE TABLE IF NOT EXISTS simulation_batches (
 id INTEGER PRIMARY KEY AUTOINCREMENT, platform_batch_id TEXT UNIQUE, platform_location TEXT,
 simulation_type TEXT NOT NULL DEFAULT 'REGULAR', status TEXT NOT NULL DEFAULT 'created', settings_json TEXT NOT NULL,
 requested_count INTEGER NOT NULL DEFAULT 0, completed_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0,
 progress_json TEXT, result_json TEXT, error_message TEXT, submitted_at TEXT, last_polled_at TEXT, completed_at TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS simulation_results (
 id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL, sequence_no INTEGER NOT NULL, expression_sha TEXT NOT NULL,
 alpha_sha TEXT NOT NULL DEFAULT '', expression TEXT NOT NULL, task_json TEXT NOT NULL DEFAULT '{}', decay REAL NOT NULL DEFAULT 0,
 platform_child_url TEXT, alpha_id TEXT, status TEXT NOT NULL DEFAULT 'created', result_json TEXT, error_message TEXT,
 completed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(batch_id, sequence_no),
 FOREIGN KEY(batch_id) REFERENCES simulation_batches(id));
CREATE TABLE IF NOT EXISTS super_alpha_candidates (
 id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_sha TEXT NOT NULL UNIQUE, component_ids_json TEXT NOT NULL,
 selection_name TEXT NOT NULL, selection TEXT NOT NULL, combo_name TEXT NOT NULL, combo TEXT NOT NULL, settings_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'prepared', alpha_id TEXT, result_json TEXT, error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alpha_optimization_queue (
 id INTEGER PRIMARY KEY AUTOINCREMENT, alpha_id TEXT NOT NULL, expression TEXT NOT NULL, sharpe REAL DEFAULT 0, fitness REAL DEFAULT 0,
 turnover REAL DEFAULT 0, margin REAL DEFAULT 0, failed_checks TEXT, failed_ra_count INTEGER DEFAULT 0, failed_ppa_count INTEGER DEFAULT 0,
 optimization_hints TEXT, status TEXT DEFAULT 'pending', priority INTEGER DEFAULT 0, retry_count INTEGER DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alpha_submission_candidates (
 id INTEGER PRIMARY KEY AUTOINCREMENT, alpha_id TEXT NOT NULL UNIQUE, expression TEXT NOT NULL, sharpe REAL DEFAULT 0,
 fitness REAL DEFAULT 0, turnover REAL DEFAULT 0, margin REAL DEFAULT 0, sc_value REAL, pc_value REAL, local_sc REAL,
 local_sc_grade TEXT, robustness_status TEXT, robustness_notes TEXT, needs_optimization INTEGER DEFAULT 0,
 is_submitted INTEGER DEFAULT 0, submitted_at TEXT, pyramid_category TEXT, pyramid_multiplier REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_expr_sha ON alpha_expressions(expression_sha);
CREATE INDEX IF NOT EXISTS idx_detail_sha ON alpha_details(expression_sha);
CREATE INDEX IF NOT EXISTS idx_detail_sharpe ON alpha_details(sharpe);
CREATE INDEX IF NOT EXISTS idx_detail_fitness ON alpha_details(fitness);
CREATE INDEX IF NOT EXISTS idx_detail_stage ON alpha_details(stage_platform);
CREATE INDEX IF NOT EXISTS idx_detail_wf_stage ON alpha_details(wf_stage);
CREATE INDEX IF NOT EXISTS idx_checks_alpha ON alpha_checks(alpha_id);
CREATE INDEX IF NOT EXISTS idx_checks_name ON alpha_checks(check_name);
CREATE INDEX IF NOT EXISTS idx_sim_batch_status ON simulation_batches(status);
CREATE INDEX IF NOT EXISTS idx_sim_result_batch ON simulation_results(batch_id);
CREATE INDEX IF NOT EXISTS idx_sim_result_alpha ON simulation_results(alpha_id);
CREATE INDEX IF NOT EXISTS idx_sim_result_alpha_sha ON simulation_results(alpha_sha);
CREATE INDEX IF NOT EXISTS idx_super_candidate_status ON super_alpha_candidates(status);
CREATE INDEX IF NOT EXISTS idx_opt_queue_alpha ON alpha_optimization_queue(alpha_id);
CREATE INDEX IF NOT EXISTS idx_opt_queue_status ON alpha_optimization_queue(status);
CREATE INDEX IF NOT EXISTS idx_opt_queue_priority ON alpha_optimization_queue(priority);
CREATE INDEX IF NOT EXISTS idx_sub_cand_alpha ON alpha_submission_candidates(alpha_id);
CREATE INDEX IF NOT EXISTS idx_sub_cand_submitted ON alpha_submission_candidates(is_submitted);
CREATE INDEX IF NOT EXISTS idx_sub_cand_sharpe ON alpha_submission_candidates(sharpe);
CREATE INDEX IF NOT EXISTS idx_datafields_region ON datafields(region);
CREATE INDEX IF NOT EXISTS idx_datafields_dataset ON datafields(dataset_id);
CREATE INDEX IF NOT EXISTS idx_datafields_type ON datafields(type);
CREATE INDEX IF NOT EXISTS idx_expr_batch ON alpha_expressions(batch_id);
CREATE INDEX IF NOT EXISTS idx_expr_status ON alpha_expressions(status);
CREATE INDEX IF NOT EXISTS idx_tpl_family ON template_library(family);
CREATE INDEX IF NOT EXISTS idx_tpl_active ON template_library(active);
CREATE TABLE IF NOT EXISTS field_signal_stats (
 id INTEGER PRIMARY KEY AUTOINCREMENT, field_id TEXT NOT NULL, dataset_id TEXT NOT NULL DEFAULT '',
 region TEXT NOT NULL, universe TEXT NOT NULL DEFAULT '', delay INTEGER NOT NULL DEFAULT 1,
 round INTEGER NOT NULL DEFAULT 0, trials INTEGER NOT NULL DEFAULT 0, signal_count INTEGER NOT NULL DEFAULT 0,
 hit_rate REAL NOT NULL DEFAULT 0, avg_sharpe REAL NOT NULL DEFAULT 0, max_sharpe REAL NOT NULL DEFAULT 0,
 min_sharpe REAL NOT NULL DEFAULT 0, avg_fitness REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, UNIQUE(field_id, dataset_id, region, universe, delay, round));
CREATE INDEX IF NOT EXISTS idx_field_signal_hit ON field_signal_stats(region, round, hit_rate DESC);
CREATE INDEX IF NOT EXISTS idx_field_signal_field ON field_signal_stats(field_id, dataset_id);
CREATE TABLE IF NOT EXISTS pair_signal_stats (
 id INTEGER PRIMARY KEY AUTOINCREMENT, pair_spec TEXT NOT NULL, pair_kind TEXT NOT NULL DEFAULT '',
 region TEXT NOT NULL, universe TEXT NOT NULL DEFAULT '', delay INTEGER NOT NULL DEFAULT 1,
 round INTEGER NOT NULL DEFAULT 0, trials INTEGER NOT NULL DEFAULT 0, signal_count INTEGER NOT NULL DEFAULT 0,
 hit_rate REAL NOT NULL DEFAULT 0, avg_sharpe REAL NOT NULL DEFAULT 0, max_sharpe REAL NOT NULL DEFAULT 0,
 min_sharpe REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(pair_spec, region, universe, delay, round));
CREATE INDEX IF NOT EXISTS idx_pair_signal_hit ON pair_signal_stats(region, round, hit_rate DESC);
CREATE INDEX IF NOT EXISTS idx_pair_signal_spec ON pair_signal_stats(pair_spec);
