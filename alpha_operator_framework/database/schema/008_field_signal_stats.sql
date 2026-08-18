-- 008: 字段级信号统计表 (研究闭环 P0 — 第6步沉淀回流到第1步)
-- 用途: 记录每个字段在每轮/区域/股票池下的回测次数与"通过信号门"次数,
--       供下一轮字段加权采样使用 (把上一轮学到的"哪些字段真出信号"带回来)。

CREATE TABLE IF NOT EXISTS field_signal_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL,
    universe TEXT NOT NULL DEFAULT '',
    delay INTEGER NOT NULL DEFAULT 1,
    round INTEGER NOT NULL DEFAULT 0,

    trials INTEGER NOT NULL DEFAULT 0,          -- 该字段参与回测次数
    signal_count INTEGER NOT NULL DEFAULT 0,    -- 通过信号门次数
    hit_rate REAL NOT NULL DEFAULT 0.0,         -- signal_count / trials
    avg_sharpe REAL NOT NULL DEFAULT 0.0,
    max_sharpe REAL NOT NULL DEFAULT 0.0,
    min_sharpe REAL NOT NULL DEFAULT 0.0,
    avg_fitness REAL NOT NULL DEFAULT 0.0,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(field_id, dataset_id, region, universe, delay, round)
);

CREATE INDEX IF NOT EXISTS idx_field_signal_hit ON field_signal_stats(region, round, hit_rate DESC);
CREATE INDEX IF NOT EXISTS idx_field_signal_field ON field_signal_stats(field_id, dataset_id);
