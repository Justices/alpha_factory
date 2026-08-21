-- 模板淘汰规则库: 存表达式模式, 在 survey 生成表达式时匹配过滤
-- 比 template_library.active=0 更彻底 —— 能淘汰模式的所有变体
CREATE TABLE IF NOT EXISTS template_prune_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    pattern_type TEXT NOT NULL DEFAULT 'prefix',
    family TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'static',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(pattern, pattern_type)
);
