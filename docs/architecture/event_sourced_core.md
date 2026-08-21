# Alpha 研究内核（事件溯源重构）设计

## 1. 目标与边界

本方案将 Alpha 研究视为一个独立、可重放的实验操作系统，而非给既有挖掘脚本加功能。目标是让任何“从字段发现到提交”的结论都能由不可变事件重新构建、比较和审计，并允许多个分支/策略并行运行而不污染彼此的统计自由度。

```text
Research Policy → Planner → Experiment Graph → Worker Queue → Event Store
      ↘ Artifact Store / Feature Snapshots / Platform Adapter ↗
                          → Projection Models → Decision Gate
```

该方案不复用现有 SQLite 表作为事实来源；旧库只作为导入源或只读查询源。现有平台适配器、AST 解析器和部分领域函数可作为纯适配组件复用。

## 2. 设计原则

- **事实不可变：** 生成、评分、回测、人工决定均是事件，状态表只是可重建投影。
- **统计隔离：** 每个 research policy 定义自身的时间分区、预算、可用数据、试验家族与停止规则；不同分支不可共享 OOS 作为调参材料。
- **策略可比较：** 两个生成/排序策略在完全相同的数据快照、预算和 locked OOS 下运行，形成公平的 A/B 对照。
- **异步可恢复：** 平台提交是外部副作用，采用 outbox、幂等键和 saga，不依赖内存轮询状态。

## 3. 核心对象

```text
ResearchPolicy
  policy_id, version, objective, universe_policy, data_policy,
  validation_policy, budget_policy, selection_policy, stop_policy

ExperimentGraph
  graph_id, policy_id, nodes(candidate/validation/decision), edges(parentage),
  frozen_partitions, random_seed, code_sha

Artifact
  immutable content-addressed blob: field snapshot, AST, config, payload,
  result, report, or returns matrix

Event
  event_id, stream_id, type, schema_version, payload_ref, occurred_at, actor

Projection
  materialized read model: candidate status, family statistics,
  batch queue, metrics dashboard, submission registry
```

每个候选不是一行指标，而是一条 graph node；其所有评分与平台结果都附带 artifact hash，因此可以重放某一时点的决策。

## 4. 事件模型

最小事件集合：

```text
PolicyCreated, PartitionLocked, FieldSnapshotCaptured, HypothesisRegistered,
CandidateGenerated, CandidateRejectedByRule, CandidateScored,
BatchAllocated, SimulationRequested, SimulationAccepted, SimulationPolled,
SimulationCompleted, ValidationComputed, CorrelationChecked,
DecisionProposed, DecisionApproved, DecisionRejected,
SubmissionRequested, SubmissionConfirmed, MonitoringObserved, CandidateRetired
```

外部 API 调用采用 outbox：`SimulationRequested` 先持久化，worker 以 `policy_id + candidate_sha + settings_sha + partition_id` 生成 idempotency key；拿到 Location 后写 `SimulationAccepted`。worker 崩溃后读取未完成事件继续，而不是重新提交。

## 5. 策略层：从假设到批次

`ResearchPolicy` 允许同一个核心引擎承载完全不同的研究策略：

```yaml
objective: discover_low_correlation_alphas
budget:
  simulations_per_round: 300
  exploration_fraction: 0.6
  exploitation_fraction: 0.3
  novelty_fraction: 0.1
validation:
  discovery_is: [2016-01-01, 2021-12-31]
  validation: [2022-01-01, 2023-12-31]
  locked_oos: [2024-01-01, 2025-12-31]
selection:
  unit: factor_family
  max_structural_neighbors: 3
  score: robust_oos_score
stopping:
  min_trials_per_family: 40
  stop_if_posterior_hit_rate_below: 0.02
```

假设只是 `CandidateGenerated` 的来源标签，可由人工、文献、LLM 或纯探索规则产生；任何路径都必须落到相同的 policy、预算和验证纪律中。Planner 对候选执行类型/量纲/滞后/复杂度规则，随后使用多臂老虎机或贝叶斯最优实验分配额度：保留最小探索，优先验证不确定性高且潜在回报高的因子族。

## 6. 验证与决策

### 6.1 阶段证据

```text
structural_valid → prior_ranked → platform_is → validation → locked_oos
                                             ↘ rejected / deferred
locked_oos → correlation_and_capacity → human_gate → submitted → monitored
```

每个阶段生成一个 `ValidationComputed` artifact，内容包括样本区间、数据版本、指标、试验家族数、收益序列 hash 和失败码。策略只接受下列条件全部成立的候选：

- locked OOS 的收益/IC 方向符合预注册目标；
- 多时间折的中位数指标超过阈值，并且分散度、参数敏感性与成本后换手可接受；
- effective trials、DSR/PSR、PBO/CSCV 来自同一 policy 的完整事件集合；
- 与已提交和本轮拟提交因子的相关性/暴露/容量在预算内；
- 人工审批事件已写入。

### 6.2 组合构建

组合服务读取 locked OOS 的收益 artifact 与风险暴露，而非 IS Sharpe。先按机制/字段/结构进行 cluster cap，再用稳健协方差收缩、相关性预算、单因子容量和换手约束优化权重；HRP 仅作为一个可比较的权重策略事件，而不是默认正确答案。

## 7. 存储与接口

推荐演进到 PostgreSQL：事件表按 `stream_id`、`occurred_at` 索引，artifact 可放对象存储或本地内容寻址目录。SQLite 只适合作为单用户原型或本地 cache；多 worker、分支对照与事件投影需要真正的多写入能力。

接口分为 command 与 query：

```text
POST /policies                 创建并冻结策略版本
POST /experiments              从策略创建实验图
POST /experiments/{id}/plan    生成并冻结候选/批次计划
POST /workers/platform         处理平台 outbox
POST /decisions/{id}/approve   写入人工审批事件
GET  /candidates/{sha}/lineage 查询完整谱系
GET  /experiments/{id}/compare 查询 A/B 对照与统计结论
```

## 8. A/B 分支实验设计

为保证比较的是策略，而非数据与运气：

1. 固定同一 `ResearchPolicy` 的数据快照、时间分区、候选上限、平台配额和随机种子；
2. 分支 A 和 B 只能替换一个明确组件，例如 `PriorScorer` 或 `BatchAllocator`；
3. 共享候选必须只计入一次有效试验，避免重复消耗统计自由度；
4. 主要比较指标为单位平台额度获得的 locked-OOS 合格因子族数、OOS 稳定性、增量相关性和复现率，不是 IS 最大 Sharpe；
5. 每次比较输出一个不可变 `ExperimentComparison` artifact，包含策略 commit、事件范围和结论。

## 9. 测试与验收

- **重放：** 从任意 event offset 重建投影后，候选状态、批次与决策完全一致。
- **幂等：** 同一 `SimulationRequested` 被 worker 处理多次，最多产生一个外部平台 simulation。
- **隔离：** 分支 B 无法读取分支 A 已解锁的 OOS 指标作为生成特征。
- **可比性：** 对照实验拒绝不同 data snapshot、partition、预算或 seed 的策略比较请求。
- **审计：** 给定 submission ID，可还原批准时所有可见证据、政策版本和人工 actor。
- **吞吐：** 在固定 worker 数下，可恢复地处理目标批量且不出现重复提交或丢失事件。

## 10. 迁移路线

1. 先在现有代码旁建立 event schema、artifact store 和 BRAIN outbox adapter，只做影子记录。
2. 将新生成器/排序器接入新内核，现有数据库继续接收兼容投影。
3. 选择一条小预算策略做端到端 A/B，验证重放、幂等和统计隔离。
4. 当新投影覆盖现有候选/批次/审批视图后，切换写入端；旧表保留只读归档。

## 11. 真实平台适配器与小批恢复演练

系统内置了标准生产适配层：
- **`BrainPlatformAdapter` (`platform/adapter.py`)**：封装了认证会话、平台批量模拟与自适应限流，将平台原始响应转换为 `EvidenceLevel.PLATFORM_IS` 证据载体。
- **`create_production_engine()`**：快速装配持久化 `EventStore`、`ArtifactStore`、`TrialLedger` 与生产网关。
- **小批崩溃恢复演练 (`python alpha_machine.py drill-recovery`)**：用于在正式投研前验证 `SimulationAccepted -> Crash -> Restart & Resume -> 6-Dimension Approval` 全生命周期闭环。

## 12. 代价与适用性

该方案的收益是严谨的可复现性、并行实验能力和长期研究资产沉淀；代价是引入事件建模、worker/outbox、投影维护与 PostgreSQL 运维。它适合准备长期运行多策略、多分支、多 worker 的 Alpha 工厂；若近期目标是尽快验证现有流程，应优先采用渐进式分层方案。

