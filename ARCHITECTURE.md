# Alpha Factory 架构与技术全景设计文档 (System Architecture)

本文档系统性阐述 **Alpha Factory** 的整体架构、设计哲学、领域分层模型、事件溯源内核、6 维证据边界与防过拟合防御体系。

---

## 一、 系统架构总览 (System Architecture Overview)

框架采用**领域驱动设计 (Domain-Driven Design, DDD)** 结合 **事件溯源 (Event Sourcing)** 架构模式，解耦量化因果逻辑、AST语法编译、多阶算子组合、真实平台回测网关与提交治理体系。

```mermaid
flowchart TD
    subgraph INPUT["一、 输入层 (Multi-Modal Inputs)"]
        P1["前沿学术研报 / 论文 (PDF / Markdown / TXT)"]
        P2["指定市场与另类数据集 (Region / Universe / Datasets)"]
        P3["字段质量与冷门度画像 (Field Quality Profiling)"]
    end

    subgraph EVENT_CORE["二、 事件溯源研究内核 (Event-Sourced Research Core)"]
        EV1["不可变事实流 (Append-Only Event Store)"]
        EV2["CAS 乐观锁与并发控制 (Optimistic Lock)"]
        EV3["内容寻址工件库 (ArtifactStore CAS SHA256)"]
        EV4["Outbox Saga 平台网关 (Crash Resilient Worker)"]
        EV5["物化视图重放引擎 (Projection Engine 100% Replay)"]
        EV6["Fail-Closed A/B 分支科学对照 (Yield per Budget)"]
    end

    subgraph DOMAIN["三、 领域与治理层 (Domain & Governance)"]
        D1["AST 规范编译器 (Parser / Canonicalizer / SHA)"]
        D2["6 维提交证据审批引擎 (SubmissionApprovalEngine)"]
        D3["持久化试验账本 (Persistent TrialLedger)"]
        D4["结构族内相关性折损 (Effective Trials Neff)"]
        D5["动态统计防过拟合 (DSR / PSR / Haircut Sharpe / PBO)"]
    end

    subgraph PIPELINES["四、 业务流水线 (Research Pipelines)"]
        PL1["文献认知提炼流水线 (Literature Pipeline)"]
        PL2["分层地毯式挖掘流水线 (Stratified Carpet Miner)"]
        PL3["组合与正交化超级因子 (Gram-Schmidt & HRP)"]
        PL4["自进化闭环与负向剪枝 (Negative Learning & Mutation)"]
    end

    subgraph STORAGE["五、 持久化与运维 (Persistence & Tooling)"]
        DB[("SQLite 单一主库 data/alpha_research.db\n• 17 张核心数据表/视图\n• schema_version / event_log / trial_ledger")]
        OPS["运维工具箱:\n• init_db.py (全新初始化/重置)\n• clean_db.py (数据清理与 VACUUM 释放空间)"]
    end

    INPUT --> EVENT_CORE
    EVENT_CORE --> DOMAIN
    DOMAIN --> PIPELINES
    PIPELINES --> STORAGE
```

---

## 二、 事件溯源研究内核 (Event-Sourced Research Core)

位于 `alpha_operator_framework/core/`，是整个研究平台的**唯一事实来源 (Single Source of Truth)**：

### 1. 不可变事件事实 (`events.py`)
- 所有研究活动均表示为不可篡改的事件实体 `Event(event_id, stream_id, event_type, payload, payload_ref, actor, created_at)`。
- 事件类型覆盖 6 大生命周期：
  - **策略与实验图**：`PolicyCreated`, `PartitionLocked`, `FieldSnapshotCaptured`, `HypothesisRegistered`
  - **候选生成与打分**：`CandidateGenerated`, `CandidateRejectedByRule`, `CandidateScored`
  - **平台仿真 Outbox**：`BatchAllocated`, `SimulationRequested`, `SimulationAccepted`, `SimulationPolled`, `SimulationCompleted`
  - **验证与相关性**：`ValidationComputed`, `CorrelationChecked`
  - **决策与审批**：`DecisionProposed`, `DecisionApproved`, `DecisionRejected`
  - **提交与监控**：`SubmissionRequested`, `SubmissionConfirmed`, `CandidateRetired`

### 2. 内容寻址工件库 (`artifacts.py`)
- 大体积回测 JSON、LLM 生成元数据、策略配置等全部通过 SHA256 哈希作为键存入 `ArtifactStore`；
- 事件日志中仅记录工件引用指针 `payload_ref: "art:sha256..."`，确保事件流轻量高效。

### 3. 追加写入事件存储 (`event_store.py`)
- 基于 SQLite `event_log` 表的只追加存储，支持流读取、全局读取与快照版本控制。

### 4. 平台 Outbox 异步 Worker (`outbox_worker.py`)
- 采用 **Outbox + 幂等键 Saga 模式** 与平台交互；
- **崩溃断点恢复**：`SIMULATION_ACCEPTED` 保持幂等键处于进行中并持久化 Location，Worker 重启自动从挂起任务断点续传；仅终态（`COMPLETED` / `FAILED`）关闭幂等键；
- **Mock 净化**：内置 Mock 强制仅产出 `synthetic` 等级；升级 `platform_is` 必须严格核验真实平台 `alpha_id`。

### 5. 物化视图重放与投影 (`projections.py`)
- 具备 **100% 确定性重放一致性**：从任意时间点的原始事件流重放，即可完整重建当前因子池、候选状态、因子族表现统计与实验图谱。

### 6. Fail-Closed A/B 科学对照引擎 (`engine.py`)
- 严格校验两分支的基础配置：若 `discovery_is` / `validation` / `locked_oos` 锁死时间分区、市场区域或股票宇宙不一致，直接拦截并拒绝比较；
- 主指标采用 **单位预算合格 Locked-OOS 因子产出率 (`yield_per_budget`)** 与 **因子族多样性**，彻底消除基于 IS 夏普判胜导致的过拟合伪胜出。

---

## 三、 证据边界与 6 维提交治理体系

位于 `alpha_operator_framework/domain/evidence.py`：

### 1. 严格的证据可信度等级 (`EvidenceLevel`)
```
1. SYNTHETIC (语法/合成测试)
      ↓
2. SANDBOX_DIAGNOSTIC (本地快速截面 IC 与单调性诊断)
      ↓
3. PLATFORM_IS (WorldQuant BRAIN 官方服务器样本内真实回测)
      ↓
4. PLATFORM_OS (平台锁死样本外 Locked-OOS 测试)
      ↓
5. SUBMISSION_READY (通过 6 维证据终审的正式提交候选)
```
- **提交资格红线**：`EvidenceLevel.is_eligible_for_submission` 仅对 `SUBMISSION_READY` 开放，彻底杜绝 `platform_is` 绕过 OOS 门禁直接提交。

### 2. 显式有向状态机 (`DecisionState` & `STATE_TRANSITIONS`)
严格执行单向拓扑流转，禁止跨阶段越级：
$$\text{DRAFT} \longrightarrow \text{SIMULATED} \longrightarrow \text{DIAGNOSED} \longrightarrow \text{CHECKS\_VERIFIED} \longrightarrow \text{SUBMISSION\_READY} \longrightarrow \text{SUBMITTED}$$
任何阶段均可因不达标流转至 $\text{REJECTED}$。

### 3. 6 维提交证据审批引擎 (`SubmissionApprovalEngine`)
候选因子要提升至 `SUBMISSION_READY`，必须同时通过 6 大维度的严格核验：
1. **Locked-OOS 证据**：具备 `PLATFORM_OS` 或通过锁死 OOS 样本检验（$\text{Sharpe}_{\text{OOS}} \ge 1.25$）；
2. **18 项 Checks 全部 PASS**；
3. **相关性门槛**：自相关 $\text{SC} \le 0.70$，母本相关性 $\text{PC} \le 0.70$；
4. **交易摩擦与容量**：换手率 $\in [1\%, 70\%]$，Margin $\ge 4.0\text{bp}$；
5. **谱系 DAG 完整性**：具备完整的父级变异与演进溯源图；
6. **终审裁决**：AlphaJudge / 人工评级为 `READY`。

---

## 四、 统计防过拟合防御体系 (Anti-Overfitting Defense)

位于 `alpha_operator_framework/domain/overfitting.py`：

### 1. 持久化试验账本 (`TrialLedger`)
- 自动持久化至 SQLite `trial_ledger` 表，记录全生命周期所有生成、变异、规则剪枝与回测试验，支持跨进程与跨分支累计。

### 2. 结构族内相关性折损
根据同模板族内的结构同质性，计算真实有效试验次数：
$$N_{eff} = 1 + (N - 1)(1 - \bar{\rho}_{family})$$
（默认族内相关性 $\bar{\rho} \approx 0.35$）。

### 3. 纯 Python / NumPy 原生统计指标
- **Deflated Sharpe Ratio (DSR)**：基于极值理论校正多重测试偏差与非正态偏度/峰度；
- **Probabilistic Sharpe Ratio (PSR)**：超越基准夏普的统计显著性概率；
- **Haircut Sharpe Ratio**：Harvey & Liu 多重测试惩罚折损夏普；
- **CPCV / PBO**：组合净化交叉验证计算过拟合概率。

---

## 五、 AST 规范编译器与字段合规

位于 `alpha_operator_framework/domain/ast/`：
- **AST 语法解析与校验**：递归构建语法树，校验数据类型与算子兼容性；
- **FASTEXPR 规范化转译**：消除空格、括号、操作数顺序等表面差异，生成全局唯一标准规范化字符串与 SHA256 哈希；
- **废弃字段全面拦截**：在 AST 编译与字段摄取阶段**全面拦截 `close`、`open`、`high`、`low`**，强制采用 `returns`、`vwap`、`volume`、`market_cap`、`sharesout` 等标准字段。

## 六、 数据库全景架构与运维

位于 `alpha_operator_framework/database/`：
- **单一主库架构**：`data/alpha_research.db` 统一管理 17 张核心表/视图；
- **零提交规范 (Zero-Commit Policy)**：`.db` 严格加入 `.gitignore`，通过 `python init_db.py` 自动化创建与种子填充；
- **WAL 并发调优**：启用 `journal_mode = WAL`、`synchronous = NORMAL`、`busy_timeout = 30000`；
- **自动化存储回收 (`DatabaseCleaner`)**：支持按失败状态清理废弃记录，并在 autocommit 模式下执行 `PRAGMA wal_checkpoint(TRUNCATE)` 与 `VACUUM` 彻底释放磁盘空间。

---

## 七、 平台网关追踪、看门狗与无人值守架构

### 1. 真实平台仿真追踪器与看门狗 (`SimulationTracker`)
位于 `alpha_operator_framework/platform/simulation_tracker.py`：
- **终态语义一致性**：将子任务平台错误（`ERROR`、`FAILED`、`CANCELLED`）直接映射为失败终态，避免顶层失败而子任务卡在 `running`；
- **无重提交超时看门狗 (`mark_stalled_if_expired`)**：当批次在平台长期停滞超过 TTL 时，标记为 `stalled` 状态并写入告警日志，**严禁自动重提**，仅允许重试轮询既有 Location 或人工介入，杜绝平台配额浪费。

---

---

## 八、 DDD 领域驱动设计投研生命周期 (DDD Research Cycle Architecture)

系统依据 [`docs/superpowers/specs/2026-08-23-research-round-domain-design.md`](docs/superpowers/specs/2026-08-23-research-round-domain-design.md) 与 [`docs/superpowers/specs/2026-08-23-production-research-loop-design.md`](docs/superpowers/specs/2026-08-23-production-research-loop-design.md) 构建，确立了**三大真实领域聚合内核**、**轻量应用编排层**与**强保证基础设施层**：

```mermaid
flowchart TD
    subgraph APP["应用层 (Application Layer: 薄用例编排)"]
        RC["ResearchCycleUseCase<br>• 控制 8 阶段标准时序<br>• 绝不包含平台/评分硬编码规则"]
    end

    subgraph DOMAIN["DDD 3 大核心领域聚合 (Zero I/O Pure Domain Layer)"]
        R1["1. 探索轮次 (ResearchRound)<br>聚合根: ResearchRound, ResearchPolicy<br>职责: 候选构造、语法预剪枝、4大选择策略<br>模块: research/round.py, selection.py, pruning.py"]
        R2["2. 实验批次 (ExperimentBatch)<br>聚合根: ExperimentBatch, BatchState<br>职责: 幂等回测、状态机流转、6维评估、Pareto排序、NSGA突变<br>模块: experiment/models.py, lifecycle.py, evaluation.py, mutation.py"]
        R3["3. 知识库 (KnowledgeBase)<br>聚合根: KnowledgeBase, KnowledgeSnapshot, SubmissionCase<br>职责: 胜出母版蒸馏、先验差量反馈、Fail-Closed上线审批<br>模块: knowledge/models.py, distillation.py, submission.py"]
    end

    subgraph INFRA["基础设施与适配器层 (Infrastructure Layer)"]
        I1["SqliteResearchRepository / SqliteExperimentRepository (快照与审计回放)"]
        I2["BrainBacktestGateway / BrainSubmissionGateway (平台网关与 Dry-run 防护)"]
        I3["SubmissionOutboxWorker / ResearchTelemetry (Saga 异步外箱与度量指标)"]
    end

    APP --> DOMAIN
    INFRA -.->|实现端口 ApplicationPorts| DOMAIN
```

### 1. 三大领域聚合根 (Domain Aggregates)
- **`ResearchRound` (`alpha_operator_framework/research/`)**：
  - 核心问题：**哪些假说值得分配平台回测预算？**
  - 管理不可变 `ResearchPolicy`、输入特征字段画像与 AST 候选因子池。
  - **双重剪枝时刻**：在回测前执行 `AstPrePruner`（拦截语法错误、类型不兼容、规范等价重复与已知失效模式）；在回测后配合后剪枝规则。
  - 内置 4 大纯抽样算法：`WeightedStratifiedSelector`（分层基准）、`DiversitySelector`（D-Optimal 最大特征空间覆盖）、`ThompsonSelector` / `UCBSelector`（贝叶斯多臂老虎机自适应探索）。
- **`ExperimentBatch` (`alpha_operator_framework/experiment/`)**：
  - 核心问题：**平台实际回测结果如何，哪些因子处于 Pareto 最优前沿并值得变异？**
  - 管理显式状态机流转：`SUBMITTED` $\to$ `ACCEPTED` $\to$ `EVALUATED` $\to$ `MUTATED`（或 `FAILED`）。
  - 执行 6 维证据硬门禁与非支配 Pareto 排序（Sharpe / Fitness / Turnover / Drawdown）。
  - 对 Rank-1 优胜候选由 `NSGA2Mutator` 生成带有谱系追踪的下一轮变异提议（`MutationProposal`）。
- **`KnowledgeBase` (`alpha_operator_framework/knowledge/`)**：
  - 核心问题：**系统从历史回测中沉淀了什么通用智慧，如何安全上线？**
  - 提炼胜出表达式为去标识化泛化骨架（`{a}`, `{b}`），持久化至知识库并导出不可变 `KnowledgeSnapshot` 供下一轮探索消费。
  - 管理 `SubmissionCase`，执行严格的 Fail-Closed 证据链核验（样本外证据、18项 Checks、自相关/母相关 $\le 0.70$、容量与换手率限制）。

### 2. 标准化应用流转时序
```text
刷新 FieldSnapshot + KnowledgeSnapshot
  → 构建 ResearchRound 聚合
  → AST 候选构造与语法预剪枝 (PrePruner)
  → 执行选定策略抽样入选 (SelectionPolicy)
  → 构建 ExperimentBatch 并提交回测 (SUBMITTED ➔ ACCEPTED)
  → 后剪枝、6 维评估与 Pareto 排序 (EVALUATED)
  → 优胜因子 NSGA-II 变异提议 (MUTATED)
  → 沉淀知识蒸馏与先验反馈更新 (KnowledgeBase)
  → (可选) 显式授权下的 Fail-Closed 正式上线提交 (SubmissionCase)
```



