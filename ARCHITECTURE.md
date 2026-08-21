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

---

## 六、 数据库全景架构与运维

位于 `alpha_operator_framework/database/`：
- **单一主库架构**：`data/alpha_research.db` 统一管理 17 张核心表/视图；
- **零提交规范 (Zero-Commit Policy)**：`.db` 严格加入 `.gitignore`，通过 `python init_db.py` 自动化创建与种子填充；
- **WAL 并发调优**：启用 `journal_mode = WAL`、`synchronous = NORMAL`、`busy_timeout = 30000`；
- **自动化存储回收 (`DatabaseCleaner`)**：支持按失败状态清理废弃记录，并在 autocommit 模式下执行 `PRAGMA wal_checkpoint(TRUNCATE)` 与 `VACUUM` 彻底释放磁盘空间。
