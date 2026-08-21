-- 009: 配对级信号统计表 (研究闭环 P2 — 相反/复合配对的信号沉淀)
-- 用途: 记录每个配对 (pair_spec = kind:left:right[:denominator]) 在每轮/区域下的
--       回测次数与「通过信号门」次数, 供下一轮优先复用有信号的配对 (第6→2 回流)。

CREATE TABLE IF NOT EXISTS pair_signal_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_spec TEXT NOT NULL,
    pair_kind TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL,
    universe TEXT NOT NULL DEFAULT '',
    delay INTEGER NOT NULL DEFAULT 1,
    round INTEGER NOT NULL DEFAULT 0,
    trials INTEGER NOT NULL DEFAULT 0,
    signal_count INTEGER NOT NULL DEFAULT 0,
    hit_rate REAL NOT NULL DEFAULT 0.0,
    avg_sharpe REAL NOT NULL DEFAULT 0.0,
    max_sharpe REAL NOT NULL DEFAULT 0.0,
    min_sharpe REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(pair_spec, region, universe, delay, round)
);

CREATE INDEX IF NOT EXISTS idx_pair_signal_hit ON pair_signal_stats(region, round, hit_rate DESC);
CREATE INDEX IF NOT EXISTS idx_pair_signal_spec ON pair_signal_stats(pair_spec);
