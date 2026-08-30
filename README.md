# Alpha Factory (Alpha Factor Operator Framework)

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-CI%20verified-brightgreen.svg)]()
[![Architecture](https://img.shields.io/badge/architecture-Event--Sourced%20Core%20%7C%20DDD-purple.svg)](ARCHITECTURE.md)
[![Database](https://img.shields.io/badge/database-SQLite%20(24%20Core%20+%205%20Runtime%20Tables)-orange.svg)](DATABASE_DESIGN.md)

工业级全生命周期量化 Alpha 因子研究与生产治理系统，深度对接 **WorldQuant BRAIN** 平台。系统融合**事件溯源不可变事实内核 (Event-Sourced Research Core)**、**领域驱动设计 (DDD)**、**统一 Alpha 构造策略体系 (Unified Construction Strategies)**、**Alpha AST 规范编译器**、**符号语法树自由杂交进化 (Symbolic Breeding)**、**大模型自主假说与反思闭环 (LLM Reflexion)**、**6 维证据准入状态机**、**动态 DSR 防过拟合引擎**、**Outbox Saga 异步平台网关**、**模板库闭环晋升 (Template Promotion Chain)** 与 **生产高可用运维体系**。

---

## 📚 核心文档导航树 (Documentation Index)

| 核心文档 | 核心内容与定位 | 快速链接 |
| :--- | :--- | :--- |
| **项目主页** | 系统定位、技术架构全景、核心能力、极速上手 | [README.md](README.md) |
| **自进化实战指南** 🌟 | **全自主进化、符号语法树自由杂交、大模型自反思与知识闭环** | [autonomous_evolution_guide.md](docs/guides/autonomous_evolution_guide.md) |
| **快速上手** | 5 分钟极速入门、常用单行 CLI 命令备忘清单 | [QUICKSTART.md](QUICKSTART.md) |
| **系统架构设计** ✨ v2.0 | DDD 五层架构、事件溯源不可变内核、证据边界、防过拟合体系、数据库设计、CLI 架构全景 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| **权威使用手册** ✨ v2.0 | 22 个 CLI 命令完整参数、6 大实战场景、Python API、SQL 速查、FAQ | [USAGE_GUIDE.md](USAGE_GUIDE.md) |
| **数据库设计** | 24 张核心数据表/视图 + 5 张事件运行时表结构、WAL 优化、Zero-Commit 规范 | [DATABASE_DESIGN.md](DATABASE_DESIGN.md) |
| **专题与归档索引** | 分页指南、AI 集成、筛选优化、生产部署、架构规范 | [docs/INDEX.md](docs/INDEX.md) |

---

## 🌟 全生命周期 10 阶段投研流程与架构全景

```mermaid
flowchart TD
    subgraph INPUT["一、 输入与特征画像 (Field Discovery & Profiling)"]
        P1["真实市场字段动态加载 (load_real_market_fields)"]
        P2["稀疏/事件字段安全包装 (winsorize + ts_backfill)"]
        P3["废弃价格字段强制拦截 (拦截 close / open / high / low)"]
    end

    subgraph CORE["二、 事件溯源研究内核 (Event-Sourced Core)"]
        E1["不可变事实流 (Append-Only Event Store)"]
        E2["CAS 乐观锁与并发控制 (Version Control)"]
        E3["内容寻址工件库 (ArtifactStore SHA256)"]
        E4["Outbox Saga 平台网关 (Idempotent Crash Recovery)"]
        E5["物化视图重放引擎 (Projection Replay)"]
        E6["Fail-Closed A/B 分支科学对照 (Yield per Budget)"]
    end

    subgraph ENGINE["三、 核心流水线与治理 (Research Pipelines)"]
        subgraph RESEARCH["1. 文献认知与大模型提炼"]
            R1["学术研报 PDF/MD 解析 (DocumentParser)"]
            R2["LLM 假说提取与字段动态对齐 (FieldGrounder)"]
            R3["失败病因自反思与二代变异 (LLMReflexionEngine)"]
        end

        subgraph MINING["2. 多族生成与符号杂交进化"]
            M1["10 大表达式生成族群 (动量/反转/MACD/特质正交等)"]
            M2["递归 AST 符号语法树自由杂交 (SymbolicTreeBreeder)"]
            M3["AST 语法解析、FASTEXPR 规范化与等价去重"]
        end

        subgraph SAMPLING["3. 纯抽样算法与语法预剪枝"]
            S1["4 大纯抽样算法 (D-Optimal / Thompson / UCB / Stratified)"]
            S2["AST 结构规范预剪枝 (AstPrePruner 消除语法冗余)"]
        end

        subgraph JUDGE["4. 6 维提交证据审批引擎"]
            J1["Locked-OOS 样本外验证 (Sharpe >= 1.25)"]
            J2["18 项 Checks 全部 PASS 审计"]
            J3["SC / PC 相关性门槛 (< 0.70)"]
            J4["换手率 (1%-70%) 与 Margin 摩擦 (>= 4.0bp)"]
            J5["谱系 DAG 变异溯源与 AlphaJudge 终审 READY"]
        end

        subgraph DEFENSE["5. 统计防过拟合防御"]
            D1["持久化试验账本 (Persistent TrialLedger)"]
            D2["结构族内相关性折损 (Effective Trials Neff)"]
            D3["动态 DSR / PSR / Haircut Sharpe / PBO (CSCV)"]
        end

        subgraph DISTILL["6. 自进化知识库与超级因子"]
            K1["达标公式去标识化骨架反向蒸馏 ({a}, {b})"]
            K2["沉淀持久化知识库 (template_library 跨数据集复用)"]
            K3["失败模式 2D 跨字段共识后剪枝 (template_prune_rules)"]
            K4["Gram-Schmidt 正交化 + HRP 分层风险平价 (Super Alpha)"]
        end
    end

    subgraph STORAGE["四、 存储与生产运维层 (Persistence & Ops)"]
        DB[("SQLite 单一主库 data/alpha_research.db\n• 24 张核心数据表/视图 + 5 张运行时表\n• schema_version / event_log / trial_ledger")]
        CLI["运维与调度工具箱:\n• init_db.py (全新初始化/增量升级/校验)\n• clean_db.py (数据清理与 VACUUM 释放物理空间)\n• auto-pilot / research-worker / submission-dispatch"]
    end

    INPUT --> CORE
    CORE --> ENGINE
    ENGINE --> STORAGE
    K2 -.->|经验回填| MINING
```

---

## ⚡ 极速开始 (Quick Start)

### 1. 数据库初始化 (首次运行必做)
本框架执行**数据库零提交 (Zero-Commit) 规范**（`.db` 文件不提交 Git），克隆代码后需先执行初始化：
```bash
python init_db.py
# 或使用主 CLI:
python alpha_machine.py init-db
```

### 2. 执行完整自动化测试
```bash
python -m pytest -q
```

### 3. 小批崩溃恢复演练 (推荐在首次生产运行前执行)
```bash
python alpha_machine.py drill-recovery
```

### 4. 显式策略 Alpha 投研生命周期 (`research-cycle`) 🌟
通过 `configs/alpha-factory.yaml` 显式组合数据库模板、多阶、多元与论文/LLM 策略。`order_depth` 是 AST 算子嵌套深度，`field_count` 是去重后的原始字段数；二者独立约束。每个叶子族每轮最多选择 8 条，平台固定按 8 条切片。

构建模式是预编排流程，而非临时算法开关：`template` 为数据库已验证模板的字段实例化，不升阶，但首批回测后仍会产生结构剪枝规则，剪掉尚未回测的同形低质量实例，幸存者继续下一批并进入人工候选池；`multi-stage` 为确定性原始字段一阶 → 信号筛选/剪枝 → 深度变换 → group 二阶 → rank/sign 验证；`ai-multi-stage` 将第一节点替换为受限算子下的 AI 经济裸信号，代码按字段类型落地表达式：MATRIX 直接标量化、EVENT 固定 `vec_avg`、VECTOR 在允许的 `vec_*` reducer 中按候选轮转；`multivariate` 为原始字段一阶 → 信号筛选/剪枝 → 多字段组合 → rank/sign 验证。每个已完成分片都会先落库，再执行无效结果门、作用域隔离的结构剪枝，以及按 Sharpe/Fitness/Margin 排序的多通道 PnL 相关性剪枝。只有 `Sharpe > 1.25`、`Fitness > 0.8` 且通过晋升门的表达式才进入下一节点；达到 `early_stop_signal_count` 时会跳过后续增强并直接进入终端验证。命中信号的原始结果也会进入本地人工优化队列；验证变体不会混入人工候选，更不会自动提交 Alpha。

`--algorithm diversity` 作用于**回测前**的候选选择，按字段、算子和模板结构做贪心多样化；它不是多阶开关，也不是结果 PnL 相关性。回测后的相关性多样化由 `research.construction.promotion.correlation` 独立控制，保留各指标通道剪枝结果的并集，并将 promote/reject/early-stop 理由写入 `promotion_decisions`。用于该剪枝的已完成 Alpha PnL 序列按平台 Alpha ID 缓存到本地数据库；缓存未命中才读取平台，恢复或后续分片不会重复拉取。
```bash
# 默认多阶 Dry-run（只生成、校验与落库，不发起平台回测）
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --mode multi-stage --algorithm d_optimal

# 模板模式：向 BRAIN 发起回测；不等同于生产 Alpha 提交
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --mode template --algorithm d_optimal \
    --execute

# 多元模式：一阶有信号后才进入字段组合节点
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --mode multivariate --execute

# AI 裸信号多阶：需要配置对应 LLM provider 的 API Key
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --mode ai-multi-stage --algorithm diversity --execute
```

中断后用同一个 `--round-id` 恢复：`python alpha_machine.py research-cycle --round-id <ID> --continue-research --execute`。仅需处理已提交回测时，可运行 `python alpha_machine.py research-worker --round-id <ID>`；常驻值守使用 `research-worker --watch --poll-seconds 30`。生产提交仍须另行提供授权证据并通过 `submission-dispatch`，不会由研究循环自动触发。

策略配置支持 `database_template`、`raw_first_order`、`ai_naked_signal`、`depth_construction`、`field_composition`、`group_second_order`、`signal_validation` 与 `literature_llm`。AI/LLM 只产出受限的经济假说或裸表达式；字段类型标量化、AST 校验、去重、配额和相关性剪枝均由代码统一执行。配置与组合示例见 [USAGE_GUIDE.md](USAGE_GUIDE.md)。

### 5. 全自动无人值守投研流水线 (`auto-pilot`) 🚀
一键串联：环境自检 ➔ 真实并发回测 ➔ 6 维证据终审 ➔ 空间释放 (VACUUM) ➔ 汇总研报生成：
```bash
python alpha_machine.py auto-pilot \
    --region GBR --universe TOP700 \
    --datasets analyst7 \
    --sample-per-family 4 --batch-size 5 \
    --execute
```

### 6. 文献认知提取流水线 (`research`)
从学术论文或研报提取 Alpha 假说并自动对齐平台可用字段；此命令只生成本地报告。平台回测必须在 `research-cycle` 配置中启用 `literature_llm` 策略，使 LLM 输出经过统一 AST 校验、去重、配额与持久化管线：
```bash
python alpha_machine.py research \
    --paper docs/academic_paper.pdf \
    --region GBR --universe TOP700 \
    --output data/paper_research_report.md
```

### 7. 分层地毯式挖掘 (`mine`)
对指定另类数据集进行多模板族分层均衡抽样与流式回测：
```bash
python alpha_machine.py mine \
    --region GBR --universe TOP700 \
    --datasets "insider_agg_matrix,pattern_scores,fundamental31" \
    --sample-per-family 4 --batch-size 5 \
    --execute
```

### 8. 数据库清理与磁盘空间彻底释放 (VACUUM)
```bash
# 试运行查看待清理的失败与剪枝记录:
python clean_db.py --mode stale --dry-run

# 正式清理并执行 WAL 截断与 VACUUM 释放物理磁盘空间:
python clean_db.py --mode stale
```

---

## 💻 Python API 调用示例

```python
from alpha_operator_framework.application.research_cycle import (
    ResearchCycleRequest,
    ResearchCycleUseCase,
)
from alpha_operator_framework.infrastructure.sqlite import (
    SqliteExperimentRepository,
    SqliteKnowledgeRepository,
    SqliteResearchRepository,
)
from alpha_operator_framework.infrastructure.brain import BrainBacktestGateway
from alpha_operator_framework.infrastructure.submission import BrainSubmissionGateway
from alpha_operator_framework.infrastructure.telemetry import JsonLinesTelemetrySink

# 1. 初始化 DDD 仓储与网关
research_repo = SqliteResearchRepository()
experiment_repo = SqliteExperimentRepository()
knowledge_repo = SqliteKnowledgeRepository()
backtest_gateway = BrainBacktestGateway(execute=False)  # 默认安全 Dry-run
submission_gateway = BrainSubmissionGateway()
telemetry = JsonLinesTelemetrySink()

# 2. 组装用例并执行 10 阶段标准化投研周期
use_case = ResearchCycleUseCase(
    research_repo=research_repo,
    experiment_repo=experiment_repo,
    knowledge_repo=knowledge_repo,
    backtest_gateway=backtest_gateway,
    submission_gateway=submission_gateway,
    telemetry_sink=telemetry,
)

request = ResearchCycleRequest(
    region="GBR",
    universe="TOP700",
    algorithm="d_optimal",
    sample_per_family=4,
    execute=False,
)
result = use_case.execute(request)
print(f"✅ 投研周期完成: 生成 {len(result.round.candidates)} 个候选，入库 {len(result.batch.tasks)} 个任务")
```

---

## 📁 项目结构全景 (Directory Structure)

```text
d:\quant\alpha_factory/
├── README.md                      # [核心 1] 项目主页与核心能力总览
├── QUICKSTART.md                  # [核心 2] 5分钟极速上手与日常命令速查
├── ARCHITECTURE.md                # [核心 3] 系统架构全景 (DDD + 事件溯源 + 证据边界)
├── USAGE_GUIDE.md                 # [核心 4] 完整操作指南 (全流程命令详解与DB维护)
├── DATABASE_DESIGN.md             # [核心 5] 数据库全景架构与 24 表/视图设计规范
│
├── init_db.py                     # 数据库一键初始化/重置入口
├── clean_db.py                    # 数据库数据清理与 VACUUM 释放物理空间入口
├── alpha_machine.py               # 统一研究 CLI 入口 (research-cycle, auto-pilot, mine, research...)
├── run_autopilot.sh               # Linux/macOS 后台无人值守启动脚本
├── run_autopilot.ps1              # Windows PowerShell 后台无人值守启动脚本
│
├── alpha_operator_framework/      # 核心源码包
│   ├── application/               # 应用编排层 (ResearchCycleUseCase, ResearchRuntime, Worker)
│   ├── research/                  # 探索轮次与候选构造 (统一构造策略, 结构约束, 抽样算法, AstPrePruner)
│   ├── experiment/                # 实验批次与评估治理 (ExperimentBatch 状态机, 6维硬门禁, NSGA2Mutator)
│   ├── knowledge/                 # 知识蒸馏与准入领域 (SignalDistiller, template_library, 提交审批)
│   ├── infrastructure/            # 基础设施适配器 (SQLite仓储, Brain网关, SubmissionOutbox, Telemetry)
│   ├── core/                      # 底层事件溯源内核 (EventStore, ArtifactStore CAS, Outbox Worker)
│   ├── domain/                    # 纯函数量化领域组件 (AST 编译器, 沙盒, 防过拟合 DSR/PSR/PBO, 裁决器)
│   ├── distill/                   # 信号聚合与模板抽象 (Diagnostic, Field/Operator 信号, TemplateAbstractor)
│   ├── generation/                # 假说与母版生成层 (CreationStrategy, TemplateLibrary, SuperAlpha)
│   ├── platform/                  # 平台通信层 (BrainClient, PlatformSimulator, SimulationTracker)
│   ├── database/                  # 数据库层 (AlphaDatabase 仓储, Cleaner, Models, Migrations, Schema/)
│   └── cache/                     # 平台元数据与算子缓存 (Datafields, Operators, Universes)
│
├── data/                          # 运行时数据目录 (.gitignore 忽略，由 init_db.py 生成)
│   └── alpha_research.db          # SQLite 统一主库 (24 张核心表/视图 + 5 张运行时表)
│
├── docs/                          # 分类专题文档库
│   ├── INDEX.md                   # 📚 文档全景导航与分类索引
│   ├── architecture/              # 🏗️ 架构与底层设计规范
│   ├── guides/                    # 📖 专项操作与集成指南
│   └── assessments/               # 📋 审计评审与历史报告
│
├── examples/                      # 示例与演练脚本
├── scripts/                       # 生产运维脚本 (Systemd 服务配置, Crontab 巡检矩阵)
└── tests/                         # 自动化测试套件 (465 个单元与集成测试, 100% 通过)
```

---

## 🔒 字段与数据合规声明
> [!IMPORTANT]
> **已弃用字段过滤提示**：平台已全面停用 `close`、`open`、`high`、`low` 等过时价格字段。本框架在 AST 编译器、动态字段对齐器及所有内置模板中**全面拦截并剔除 `close` 等字段**，统一使用 `returns`、`vwap`、`volume`、`market_cap`、`sharesout` 等标准收益流与量价字段。
