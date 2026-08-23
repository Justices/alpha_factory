# 目录与模块调整方案（深化设计后）

> 背景：把散落的因子挖掘能力，重构为「字段选择 → 表达式合成 → 批量回测 → 信号优化 → 提交 → 沉淀与抽象」的**研究闭环**。
> 本文给出目标目录分层、现状映射与渐进迁移路径。

## 一、设计原则

1. **按职责分层，不按流程步骤分**。一个模块可能被多步复用（如 `pruning` 同时服务于字段选择和信号优化），所以按「领域 / 生成 / 平台 / 蒸馏 / 编排」分层，而非「第1步/第2步」。
2. **纯函数与网络隔离**。领域层（字段/算子/模板/密度/剪枝/评价/优化）零网络访问；平台交互集中在 `platform/`。
3. **稳定 API 不破**。`alpha_operator_framework/__init__.py` 持续 re-export，旧的 `from alpha_operator_framework import X` 全部兼容，目录搬迁不影响下游。
4. **沉淀可回放**。蒸馏层产物带 `round` / `source_expression_sha` / 时间戳。

## 二、目标目录结构

```
alpha_factory/
├── alpha_machine.py                    # 统一 CLI 入口 (auto-pilot / research-cycle / init-db / clean-db)
│
├── alpha_operator_framework/           # 核心框架包
│   ├── application/                    # 应用编排层 (薄用例时序控制，无硬编码业务逻辑) ★ DDD
│   │   ├── ports.py                    #   抽象端口定义
│   │   └── research_cycle.py           #   ResearchCycleUseCase (串联 8 阶段标准时序)
│   │
│   ├── research/                       # 探索轮次与候选构造领域层 ★ DDD
│   │   ├── round.py                    #   ResearchRound, ResearchPolicy, Candidate 聚合
│   │   ├── policy.py                   #   ResearchPolicy 与抽样算法工厂
│   │   ├── selection.py                #   4 大纯抽样算法 (Stratified / Diversity / Thompson / UCB)
│   │   ├── pruning.py                  #   AstPrePruner 语法与规范重复预剪枝
│   │   ├── construction.py             #   AstCandidateBuilder 候选生成
│   │   ├── field_loader.py             #   真实市场字段动态加载
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
│   │   ├── brain.py                    #   BrainBacktestGateway, BrainSubmissionGateway (平台网关与 Dry-run 防护)
│   │   ├── submission.py               #   SubmissionOutboxWorker (Saga 异步外箱)
│   │   └── telemetry.py                #   ResearchTelemetry 度量指标
│   │
│   ├── core/                           # 底层事件溯源内核 (Event Sourced Research Core)
│   │   ├── events.py                   #   不可变事件定义
│   │   ├── event_store.py              #   EventStore 追加流
│   │   └── artifacts.py                #   ArtifactStore 内容寻址工件
│   │
│   ├── domain/                         # 纯函数量化领域组件 (AST/沙盒/防过拟合)
│   │   ├── ast/                        #   AST 语法树引擎 (解析/规范化/等价去重/校验)
│   │   ├── sandbox/                    #   本地向量化快速预筛沙盒 (毫秒级 Rank IC/Sharpe)
│   │   ├── overfitting.py              #   统计防过拟合 (DSR / PSR / PBO / CSCV / Haircut)
│   │   └── orthogonalization.py        #   施密特正交残差化与 HRP 组合
│   │
│   ├── platform/                       # 平台交互与并发调度
│   ├── database/                       # 存储与连接层 (SQLite WAL 模式)
│   └── cache/                          # 平台元数据缓存
│
├── cnhkmcp/                            # 平台底层通信连接器
├── data/                               # 数据资产 (主库 data/alpha_research.db)
├── docs/                               # 完整架构与指南文档
├── runs/                               # 运行输出与研报
└── tests/                              # 全套自动化测试 (226+ 项测试 100% 通过)
```

## 三、现状 → 目标映射

| 现状（扁平，38 个 .py） | 目标归属 | 搬迁方式 |
|------------------------|----------|----------|
| fields / economic_rules / operators / families / semantic_pairs / paired_bases / density / pruning / evaluation / optimize | `domain/` | 移动 + 相对 import 改写 |
| creation_strategy / template_library / super_alpha | `generation/` | 移动 + 相对 import 改写 |
| alpha_source / datafield_ingest / local_fields / platform_config / simulation_tracker | `platform/` | 移动 + 相对 import 改写 |
| **distill/field_signals.py（新增）** | `distill/` | ✅ 已落地 |
| **distill/template_abstractor.py（新增）** | `distill/` | ✅ 已落地 |
| **loop.py（新增）** | 顶层 | ✅ 已落地 |
| database / cache / strategies | 原位保留 | 不动 |
| orchestrator / ai_workflow | 顶层 | 不动 |

## 四、迁移执行（已完成，设计期一次性清理）

按老刘要求「设计期不考虑兼容、直接清理」，本次为**一次性推倒重来**，不留兼容层：

1. 18 个扁平模块按映射搬入 `domain/`（10）、`generation/`（3）、`platform/`（5）。
2. 全部相对 import 统一改为绝对 import（`from alpha_operator_framework.<层>.<模块>`），消除跨层反向依赖（`platform → ai_workflow` 的 `filter_*` 便捷函数下沉到 `domain/optimize.py`）。
3. 顶层 `__init__.py` 从新路径 re-export，公共 API 不变。
4. 外部引用（`alpha_machine.py`、`examples/`、`tests/`）同步改写。
5. 验证：包导入 OK、`alpha_machine` 导入 OK、离线测试全绿、`demo_workflow` 跑通。

## 五、本轮已落地（P0 沉淀回流 + 目录重构）

| 产物 | 说明 |
|------|------|
| `distill/field_signals.py` | `aggregate_field_signals`（按字段聚合信号命中率）+ `weighted_field_sample`（hit_rate 加权采样） |
| `distill/template_abstractor.py` | `abstract_template` / `abstract_templates`（达标表达式 → 模板骨架，按 support 去重） |
| `database/schema/008_field_signal_stats.sql` | 字段信号统计表（版本化留档） |
| `database/repository.py` | `upsert_field_signal_stats`（支持 accumulate 累积）+ `get_field_signal_stats` |
| `loop.py` | `LoopConfig` + `run_research_loop` + `distill_and_plan_next` + `distill_templates_round`（平台回测接入点留 TODO） |
| `tests/test_distill.py` | 12 项离线测试，全绿 |
| `latest_schema.sql` | 已同步 field_signal_stats 快照 |
| `domain/` `generation/` `platform/` | 目录重构完成，18 模块归位 |
| `distill/template_abstractor.py` | `to_template` + `distill_templates_into_library`（P1：达标表达式 → 骨架 → 回填 `template_library`） |

## 六、后续路线

- ~~**P1（模板抽象回流闭环）**~~ ✅ 已完成：`distill_templates_into_library` 把达标表达式抽象回填 `template_library`（family=`distilled`，name=`distilled_<sha12>` 幂等），`template_creation_strategy` 用 `families=("distilled",)` 即可消费。
- **P2（多轮编排）**：`loop._run_round_survey` 接入 `run_full_workflow` / `alpha_machine`，跑通多轮「回测→沉淀→加权采样」真实闭环。
