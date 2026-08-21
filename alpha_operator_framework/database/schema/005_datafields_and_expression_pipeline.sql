-- Version 005: datafields ledger, expression backtest pipeline columns, RA/PPA counts.
-- 运行时实际迁移由 repository.py `_init_database()` 的 CREATE IF NOT EXISTS + ALTER-guard 完成;
-- 本脚本与 002-004 一样是版本化文档, 供假想执行器 / 审计使用。

-- 有信号的数据字段表 (仅收录被 alpha 用到的字段; universe 聚合为 JSON 数组)
CREATE TABLE IF NOT EXISTS datafields (
    field_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL DEFAULT '',
    dataset_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'MATRIX',
    region TEXT NOT NULL,
    delay INTEGER NOT NULL DEFAULT 1,
    universes_json TEXT NOT NULL DEFAULT '[]',
    coverage REAL DEFAULT 0.0,
    user_count INTEGER DEFAULT 0,
    alpha_count INTEGER DEFAULT 0,
    expression_shas_json TEXT NOT NULL DEFAULT '[]',
    last_fetched_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (field_id, dataset_id, region, delay)
);

-- alpha_expressions 回测管线列
ALTER TABLE alpha_expressions ADD COLUMN batch_id INTEGER;
ALTER TABLE alpha_expressions ADD COLUMN fields TEXT NOT NULL DEFAULT '[]';
ALTER TABLE alpha_expressions ADD COLUMN status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE alpha_expressions ADD COLUMN first_operator TEXT NOT NULL DEFAULT '';

-- alpha_details RA/PPA 失败计数 (参考 WebDataScope failedNumRA/failedNumPPA)
ALTER TABLE alpha_details ADD COLUMN ra_failed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alpha_details ADD COLUMN ppa_failed INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_datafields_region ON datafields(region);
CREATE INDEX IF NOT EXISTS idx_datafields_dataset ON datafields(dataset_id);
CREATE INDEX IF NOT EXISTS idx_datafields_type ON datafields(type);
CREATE INDEX IF NOT EXISTS idx_expr_batch ON alpha_expressions(batch_id);
CREATE INDEX IF NOT EXISTS idx_expr_status ON alpha_expressions(status);
