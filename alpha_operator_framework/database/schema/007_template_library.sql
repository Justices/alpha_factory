-- Version 007: template_library 模板类库表 + datafields.category。
-- 运行时实际迁移由 repository.py `_init_database()` 的 CREATE IF NOT EXISTS + ALTER-guard 完成;
-- 本脚本与 002-006 一样是版本化文档。
CREATE TABLE IF NOT EXISTS template_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    family TEXT NOT NULL DEFAULT '',
    template_type TEXT NOT NULL DEFAULT 'placeholder',
    expression_template TEXT NOT NULL,
    template_index INTEGER NOT NULL DEFAULT 0,
    fields_per_alpha INTEGER NOT NULL DEFAULT 0,
    expression_origin TEXT NOT NULL DEFAULT '',
    field_types_json TEXT NOT NULL DEFAULT '[]',
    categories_json TEXT NOT NULL DEFAULT '[]',
    dataset_families_json TEXT NOT NULL DEFAULT '[]',
    placeholders_json TEXT NOT NULL DEFAULT '{}',
    group_slots_json TEXT NOT NULL DEFAULT '[]',
    slot_count INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    example_expression TEXT NOT NULL DEFAULT '',
    settings_hint_json TEXT NOT NULL DEFAULT '{}',
    field_candidates_json TEXT NOT NULL DEFAULT '{}',
    operators_used_json TEXT NOT NULL DEFAULT '[]',
    source_json TEXT NOT NULL DEFAULT '{}',
    parent_template_id INTEGER,
    signal_constraints_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tpl_family ON template_library(family);
CREATE INDEX IF NOT EXISTS idx_tpl_active ON template_library(active);
ALTER TABLE datafields ADD COLUMN category TEXT NOT NULL DEFAULT '';
