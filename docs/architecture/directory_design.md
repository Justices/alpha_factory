# Alpha Factory 代码分层目录规范与 DDD 架构设计 (Directory Design)

> **定位**: 定义 Alpha Factory 代码库的分层职责、DDD 限界上下文归属与包隔离准则。

---

## 一、 设计原则

1. **按职责与限界上下文分层**：清晰划分领域层（纯函数与实体）、应用层（薄时序用例）、基础设施层（外部适配与持久化）、内核层（事件溯源与工件）与生成/平台层。
2. **纯函数与外部 IO 严格隔离**：领域层（`research/`、`experiment/`、`knowledge/`、`domain/`、`distill/`）零网络与零直接 SQL 访问；外部平台交互集中在 `platform/` 与 `infrastructure/`。
3. **稳定 API 不破坏向下兼容**：`alpha_operator_framework/__init__.py` 持续统一 re-export 常用工具与实体。
4. **沉淀全量可审计与可重放**：所有研究轮次、实验批次与知识库快照均带版本戳与 SHA 指纹。

---

## 二、 完整代码目录全景

```text
alpha_factory/
├── alpha_machine.py                    # 统一 CLI 入口 (research-cycle / auto-pilot / mine / research...)
├── run_autopilot.sh                    # Linux/macOS 后台无人值守启动脚本
├── run_autopilot.ps1                   # Windows PowerShell 后台无人值守启动脚本
├── init_db.py                          # 数据库一键初始化/校验入口
├── clean_db.py                         # 数据库数据清理与 VACUUM 释放物理空间入口
│
├── alpha_operator_framework/           # 核心框架包
│   ├── application/                    # 应用编排层 (薄用例时序控制，无硬编码业务逻辑) ★ DDD
│   │   ├── ports.py                    #   抽象端口定义
│   │   ├── research_cycle.py           #   ResearchCycleUseCase (串联 10 阶段标准时序)
│   │   ├── research_runtime.py         #   运行时上下文管理
│   │   └── research_worker.py          #   事件驱动异步恢复 Worker
│   │
│   ├── research/                       # 探索轮次与候选构造领域层 ★ DDD
│   │   ├── round.py                    #   ResearchRound, ResearchPolicy, Candidate 聚合
│   │   ├── policy.py                   #   ResearchPolicy 与抽样算法工厂
│   │   ├── selection.py                #   4 大纯抽样算法 (Stratified / Diversity / Thompson / UCB / D-Optimal)
│   │   ├── pruning.py                  #   AstPrePruner 语法与规范重复预剪枝
│   │   ├── construction.py             #   AstCandidateBuilder 候选生成
│   │   ├── field_loader.py             #   真实市场字段动态加载与画像
│   │   └── pipeline.py                 #   文献研发流水线 (ingest_literature_to_alphas)
│   │
│   ├── experiment/                     # 实验批次与评估治理领域层 ★ DDD
│   │   ├── models.py                   #   ExperimentBatch, BacktestTask, BacktestResult, EvaluationRecord
│   │   ├── lifecycle.py                #   ExperimentBatchStateMachine (SUBMITTED ➔ ACCEPTED ➔ EVALUATED ➔ MUTATED)
│   │   ├── evaluation.py               #   6 维证据硬门禁与 ParetoRank 非支配排序
│   │   └── mutation.py                 #   NSGA2Mutator 优胜候选变异提议生成
│   │
│   ├── knowledge/                      # 知识蒸馏与准入领域层 ★ DDD
│   │   ├── models.py                   #   KnowledgeBase, KnowledgeSnapshot, PruneRuleEvidence
│   │   ├── distillation.py             #   SignalDistiller 泛化母版抽象 ({a}, {b})
│   │   └── submission.py               #   SubmissionApprovalService & SubmissionCase (Fail-Closed 审批)
│   │
│   ├── infrastructure/                 # 基础设施与外部适配器层 ★ DDD
│   │   ├── sqlite.py                   #   SqliteResearchRepository, SqliteExperimentRepository (快照与审计)
│   │   ├── brain.py                    #   BrainBacktestGateway (平台网关与 Dry-run 防护)
│   │   ├── submission.py               #   SubmissionOutboxWorker (Saga 异步外箱)
│   │   └── telemetry.py                #   ResearchTelemetry 度量指标
│   │
│   ├── core/                           # 底层事件溯源内核 (Event Sourced Research Core)
│   │   ├── events.py                   #   不可变事件定义
│   │   ├── event_store.py              #   EventStore 追加流
│   │   ├── artifacts.py                #   ArtifactStore 内容寻址工件 (SHA256)
│   │   ├── outbox_worker.py            #   Outbox Saga 异步 Worker
│   │   ├── engine.py                   #   Fail-Closed A/B 科学对照引擎
│   │   └── projections.py              #   物化视图确定性重放
│   │
│   ├── domain/                         # 纯函数量化领域组件 (AST/沙盒/防过拟合/证据)
│   │   ├── ast/                        #   AST 语法树引擎 (解析/规范化/等价去重/校验/breeder)
│   │   ├── judge/                      #   AlphaJudge 终审裁决器
│   │   ├── sandbox.py                  #   本地向量化快速预筛沙盒 (毫秒级 Rank IC/Sharpe)
│   │   ├── overfitting.py              #   统计防过拟合 (DSR / PSR / PBO / CSCV / Haircut)
│   │   ├── evidence.py                 #   6 维证据状态机与等级
│   │   └── orthogonalization.py        #   施密特正交残差化与 HRP 组合
│   │
│   ├── distill/                        # 信号聚合与模板抽象
│   │   ├── field_signals.py            #   字段信号统计与加权抽样
│   │   ├── operator_signals.py         #   算子信号统计
│   │   ├── template_abstractor.py      #   表达式去标识化模板抽象
│   │   └── template_pruner.py          #   2D 共识负向剪枝
│   │
│   ├── generation/                     # 假说与母版生成层 (CreationStrategy, TemplateLibrary, SuperAlpha)
│   ├── platform/                       # 平台通信层 (BrainClient, PlatformSimulator, SimulationTracker)
│   ├── database/                       # 数据库连接、仓储与迁移 (SQLite WAL 模式, 17 表/视图)
│   └── cache/                          # 平台元数据缓存 (Datafields, Operators, Universes)
│
├── cnhkmcp/                            # 平台底层通信连接器
├── data/                               # 运行时数据资产 (主库 data/alpha_research.db)
├── docs/                               # 完整架构与指南文档
├── runs/                               # 运行输出与研报
└── tests/                              # 全套自动化测试 (242 项测试 100% 通过)
```
