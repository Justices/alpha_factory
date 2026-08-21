# 先验驱动 Alpha 研究闭环（渐进式分层）设计

## 1. 目标与边界

在保留现有 AST、模板、BRAIN 平台网关及 SQLite 主库的前提下，建立一条可批量探索、可审计、不可将弱证据误报为有效 Alpha 的研究闭环：

```text
字段画像 → 假设规格 → 受约束批量生成 → 先验排序/分层抽样
  → 实验账本 → 平台 IS → 验证/OOS → 决策状态机 → 反馈分配
```

本设计不试图在没有收益标签时断言预测有效；无真实数据阶段仅生成 `prior_score`，真实 BRAIN 回测才产生 `platform_is` 证据，锁定的验证集才产生 `validated` 证据。

## 2. 方案特性

- **渐进接入：** 新模块以服务和新表形式接入，现有 `carpet_mining.py`、`platform_simulator.py`、`AlphaDatabase` 可继续使用。
- **批量优先：** 每轮仍允许数百至数千候选，但按假设族、字段族、结构族均衡抽样。
- **防止证据混淆：** 沙盒与合成结果永远不能进入 `alpha_submission_candidates`。
- **完整谱系：** 每条候选可追溯到字段快照、假设、模板、生成规则、参数、父代、代码版本和所有试验。

## 3. 模块边界

| 模块 | 责任 | 输入 | 输出 |
|---|---|---|---|
| `FieldProfiler` | 将字段元数据转为可比较质量画像 | datafields、字段元数据快照 | `FieldProfile` |
| `HypothesisRegistry` | 管理可证伪研究假设及预算 | 人工/LLM 提取的规格 | `HypothesisSpec` |
| `ConstrainedGenerator` | 在约束内生成 AST | 假设、字段、模板、算子规则 | `CandidateSpec` |
| `PriorScorer` | 仅作未验证候选排序 | CandidateSpec、画像、已有候选 | `PriorAssessment` |
| `BatchAllocator` | 按预算与信息价值选批 | assessment、历史试验结果 | `ExperimentBatch` |
| `ExperimentLedger` | 记录不可变的生成/提交/结果事件 | 所有模块事件 | 可审计研究谱系 |
| `ValidationService` | 管理 IS、validation、locked OOS 证据 | 平台/本地真实收益结果 | `ValidationReport` |
| `DecisionEngine` | 证据等级状态机，控制晋级 | evidence、checks、相关性 | `Decision` |
| `LearningService` | 回写字段/模板/算子族统计 | 已完成实验 | 后验统计与下一轮配额 |

## 4. 数据模型

新增表均使用 append-only 事件或版本号；原有 `alpha_expressions` 和 `alpha_details` 保持兼容。

```text
hypothesis_specs
  id, version, title, mechanism, expected_sign, holding_horizon,
  market_scope_json, field_constraints_json, operator_constraints_json,
  falsification_rules_json, budget_json, status, created_at

field_profiles
  field_snapshot_id, field_id, region, delay, availability_lag,
  coverage, missingness, update_frequency, semantic_tags_json,
  crowding_score, quality_score, profile_version, created_at

experiment_runs
  run_id, hypothesis_id, code_sha, config_sha, data_snapshot_id,
  universe_snapshot_id, seed, stage, parent_run_id, created_at

candidate_evidence
  candidate_sha, run_id, evidence_level, prior_score, platform_alpha_id,
  metrics_json, checks_json, validation_partition, result_status, created_at

research_events
  event_id, aggregate_type, aggregate_id, event_type, payload_json,
  occurred_at

family_posteriors
  family_key, context_json, trials, successes, failures,
  posterior_alpha, posterior_beta, novelty_score, updated_at
```

`candidate_sha` 使用规范化 AST SHA；`run_id` 是唯一的研究上下文，禁止仅以表达式哈希覆盖不同市场、时间段或参数配置的证据。

## 5. 假设与先验评分

`HypothesisSpec` 是一个可证伪的研究约束，不是正确性声明，最小内容为：

```json
{
  "mechanism": "analyst revision diffusion",
  "expected_sign": "positive",
  "holding_horizon_days": [5, 20],
  "market_scope": ["USA/TOP3000", "GBR/TOP700"],
  "allowed_field_tags": ["analyst_revision", "estimate_change"],
  "allowed_operator_families": ["ts_smooth", "rank", "group_neutralize"],
  "forbidden_patterns": ["same_field_ratio", "nested_rank_depth_gt_2"],
  "falsification": "two locked OOS folds have opposite sign or median OOS Sharpe <= 0"
}
```

`PriorScorer` 不读取未来收益，其分数仅用于队列排序：

```text
prior_score =
  0.25 * field_quality
+ 0.20 * semantic_alignment
+ 0.15 * availability_safety
+ 0.15 * structural_robustness
+ 0.15 * novelty
+ 0.10 * family_information_value
- complexity_penalty
- leakage_risk_penalty
- redundant_structure_penalty
```

评分同时输出证据而非黑箱总分：被选字段的滞后和覆盖、被允许的算子、复杂度、近邻表达式数、以及任何拒绝理由。

## 6. 批量生成与预算分配

1. 每个活跃假设先生成大池；生成器通过 AST 类型、单位、嵌套深度、字段复用、缺失处理和禁用模式进行硬过滤。
2. 以 `(hypothesis_id, field-family, template-family, operator-signature)` 定义结构族；同族近重复候选只保留少数代表。
3. `BatchAllocator` 用分层抽样，先保证每个活跃假设族有最小探索份额，再将剩余额度分配给高不确定且潜在价值高的族。
4. 真实结果返回后使用 Beta-Binomial 命中率、稳定性分数与相关性惩罚更新 `family_posteriors`；不得将单轮最高 Sharpe 直接视作机制成立。

默认配额策略：60% 探索（高不确定/高先验）、30% 利用（历史较优且未完成 OOS）、10% 保留给新字段或异常市场状态。所有比例通过 run config 固化。

## 7. 证据等级与状态机

```text
generated
  → prior_qualified | rejected_prior
  → platform_is_complete | platform_failed
  → validation_pending | rejected_is
  → locked_oos_complete | rejected_validation
  → correlation_pending
  → submission_ready | needs_human_approval | rejected
  → submitted | monitored | retired
```

约束：

- `synthetic`、`sandbox` 和 `prior_qualified` 仅能进入实验队列；
- `platform_is_complete` 仅表示已获得真实 IS；
- `submission_ready` 必须有锁定 OOS、全部 required checks、相关性结果、谱系完整性和人工批准标志；
- 任意 stage 变更均写入 `research_events`，并携带证据记录 ID。

## 8. 验证规则

- IS 仅用于初筛与有限结构选择；对每个候选记录其所属试验家族和真实尝试次数。
- Validation 使用连续滚动时间窗；OOS 分区在 run 创建时锁定，进入后不得用于调参。
- 因子族使用中位 OOS Sharpe、分期符号一致率、换手/成本约束、参数邻域稳定性和跨市场稳定性共同判定。
- DSR/PSR 必须使用真实有效样本数、收益序列的偏度/峰度，以及 `ExperimentLedger` 的有效试验数；报告 PBO/CSCV 时必须保存使用的收益矩阵与切分配置哈希。
- 任何验证失败都回写明确失败码，如 `sign_flip_oos`、`parameter_fragility`、`high_family_correlation`，供生成器学习。

## 9. 平台与数据库接入

- `PlatformGateway` 包装现有 simulator，并通过 `simulation_batches` / `simulation_results` 实现幂等提交、轮询恢复与子任务状态记录。
- 每个提交 payload 绑定 `run_id`、`candidate_sha`、settings hash；同一幂等键重试不得创建新平台 simulation。
- 平台返回的 IS metrics、checks、SC/PC 原始 payload 写入 evidence 表，同时保留原始 JSON hash。
- `alpha_submission_candidates` 的写入口仅由 `DecisionEngine.approve_for_submission()` 提供；数据库加 trigger 或应用层强校验，拒绝低证据等级写入。

## 10. 测试与验收

1. **隔离测试：** 任意 sandbox/synthetic evidence 尝试写入提交候选池均失败。
2. **可复现测试：** 相同 input snapshot、config、seed、代码版本生成相同 canonical candidate 集与相同 batch 选择。
3. **谱系测试：** 任一候选可在一次查询中返回完整 hypothesis、字段快照、模板、父代、运行参数与所有 evidence。
4. **统计测试：** DSR 的 trial_count 来自 ledger；增加 1,000 次同族生成后，报告的有效试验数同步增加而非固定为 50。
5. **恢复测试：** 提交中断后重启，只轮询或重试缺失子任务，不重复创建成功的 simulation。
6. **批次公平性测试：** 给定配额，活跃假设族获得至少最小探索样本且同结构近重复不超过上限。

## 11. 迁移顺序

1. 引入 evidence level、run ID 和不可变 ledger，先封住错误晋级路径。
2. 接入 `FieldProfiler`、`HypothesisRegistry` 和 `PriorScorer`，让新候选先走新队列。
3. 实现批次分配、平台幂等恢复和 validation 状态机。
4. 最后接入后验学习和提交后监控；旧流程保留为兼容模式，但标记为 `legacy_untracked`。
