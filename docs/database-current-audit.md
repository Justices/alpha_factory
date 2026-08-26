# 当前数据库梳理

配置 `configs/alpha-factory.yaml` 将所有运行时组件指向同一 SQLite 文件 `data/alpha_research.db`。问题不是两份数据库，而是同一个库中有两套独立的持久化模型。

## A. 事件与流程快照（运行时模型）

| 表 | 当前职责 | 主键/关联 |
| --- | --- | --- |
| `event_log` | 追加事件事实；候选生成、选择、提交、完成、评估都写入 | `global_offset`；`stream_id` 通常是 `round_id` |
| `research_round_snapshots` | 一轮研究的 JSON 快照，含全部 Candidate、选择与剪枝决定 | `round_id` |
| `experiment_batch_snapshots` | 一个研究批次的 JSON 快照，含任务、结果、评估、状态机 | `batch_id`（当前等于 `round_id`） |
| `knowledge_snapshot` | 当前知识快照 | 固定 `id=1` |
| `knowledge_snapshot_history` | 每轮后的知识版本历史 | `version`，含 `round_id` 与事件 offset |
| `template_promotions` | worker 蒸馏出的运行时模板 | `expression_template` |
| `submission_outbox` | 待提交平台 Alpha 的 outbox | `platform_alpha_id` |
| `schema_migrations` | 运行时迁移账本 | `version` |

## B. Alpha 目录与平台模拟明细（AlphaDatabase 模型）

| 表 | 当前职责 | 关键关联 |
| --- | --- | --- |
| `alpha_expressions` | 全量候选表达式目录；`status` 为回测状态，`pruning_status` 为剪枝状态 | `expression_sha` 唯一；`batch_id` 指向数值模拟批次但没有 FK |
| `simulation_batches` | 向平台提交的一批模拟 | 数值 `id` |
| `simulation_results` | 批内单条平台模拟结果 | `batch_id → simulation_batches.id`；表达式以 SHA 文本保存 |
| `alpha_details` | 平台 Alpha 的完整指标及平台状态 | `alpha_id` 唯一；有 `expression_sha` 但没有 FK |
| `alpha_checks` | 平台检查项 | `(alpha_id, check_name)` |
| `trial_ledger` | 多重检验试验账本 | `trial_id` |
| `datafields` | 平台字段元数据与表达式使用痕迹 | `(field_id, dataset_id, region, delay)` |
| `field_signal_stats` / `pair_signal_stats` / `operator_signal_stats` | 统计学习数据 | 各自的 region/universe/delay/round 复合唯一键 |
| `template_library` | 生成使用的模板库 | `name` 唯一 |
| `template_prune_rules` | 模板级剪枝规则 | `(pattern, pattern_type)` |
| `backtest_dataset_records` | 数据集回测计数 | region/universe/delay/dataset/strategy |
| `super_alpha_candidates` / `alpha_optimization_queue` / `alpha_submission_candidates` | 后续优化与提交队列 | 各自独立队列键 |
| `schema_version` | 旧 schema 账本 | `version` |

## 已打通的路径

`research-cycle` 当前会先全量写入 `alpha_expressions`，选择出的任务再写入 `simulation_batches` / `simulation_results`；worker 的平台结果会写入 `alpha_details`、`alpha_checks`，并更新 `alpha_expressions.status`。`event_log` 同时记录同一轮的事件。

## 当前断链与重复事实

1. `research_round_snapshots` 与 `alpha_expressions` 没有 `round_id` 或候选 ID 的结构化关联；只能用 JSON 或表达式文本/SHA 间接对应。
2. `experiment_batch_snapshots.batch_id` 是字符串 round ID，`simulation_batches.id` 是数值 ID；两者的关系仅藏在快照 JSON 的 `storage_batch_id`，没有数据库约束。
3. `event_log`、两个 snapshot 表和 Alpha 明细表都记录任务状态，但没有统一的“任务记录”表作为唯一事实来源。
4. `template_promotions` 与 `template_library` 分别保存运行时蒸馏模板和生成模板，worker 目前只写前者，生成器不会自动消费前者。
5. `knowledge_snapshot` 与三类 signal stats 分别积累评分，当前没有明确的投影/同步关系。
6. `alpha_expressions` 的唯一键只有 `expression_sha`；同一表达式在不同 region/universe/settings 下会共享一条目录记录，环境维度只能从 `simulation_results` / `alpha_details` 追溯。

## 建议的目标边界

保留 `event_log` 作为审计事实，保留 `alpha_expressions` 作为表达式目录，保留 `simulation_batches` / `simulation_results` 作为平台执行明细；将 `research_round_snapshots` 和 `experiment_batch_snapshots` 限定为可重建缓存，而不是第二套业务真相。

下一步应补三个显式键：`alpha_expressions.round_id`（或独立 `round_candidates` 表）、`simulation_batches.round_id`、`simulation_results.expression_sha → alpha_expressions.expression_sha` 外键；随后将模板提升和知识统计各自指定单一写入表与投影方向。
