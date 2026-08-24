# Alpha Factor Operator Framework 用户与实战操作指南 (Usage Guide)

> 本指南帮助您全面掌握 **Alpha Factory** 全生命周期量化因子研发的完整流水线，涵盖从 **全新 DDD 投研生命周期 (`research-cycle`)**、**全自动无人值守流水线 (`auto-pilot`)**、**分层地毯式挖掘 (`mine`)**、**前沿学术文献研报转化 (`research`)** 到 **超级因子正交化组合 (`simulate-super`)** 与 **数据库运维释放空间 (`clean-db`)** 的完整实战操作。

---

## 目录

1. [环境与认证配置](#1-环境与认证配置)
2. [CLI 统一命令速查表](#2-cli-统一命令速查表)
3. [核心场景 1: 全新 DDD 10 阶段投研生命周期 (`research-cycle`) 🌟](#3-核心场景-1-全新-ddd-10-阶段投研生命周期-research-cycle-)
4. [核心场景 2: 全自动无人值守投研流水线 (`auto-pilot`) 🚀](#4-核心场景-2-全自动无人值守投研流水线-auto-pilot-)
5. [核心场景 3: 分层地毯式挖掘与自优化 (`mine`)](#5-核心场景-3-分层地毯式挖掘与自优化-mine)
6. [核心场景 4: 学术文献研报认知转化流水线 (`research`)](#6-核心场景-4-学术文献研报认知转化流水线-research)
7. [核心场景 5: 超级组合因子与正交化配置 (`simulate-super`)](#7-核心场景-5-超级组合因子与正交化配置-simulate-super)
8. [核心场景 6: 基础生成、回测与轮询 (`discover` / `prepare` / `simulate`)](#8-核心场景-6-基础生成回测与轮询-discover--prepare--simulate)
9. [核心场景 7: 投研恢复与上线外箱派发 (`research-worker` / `submission-dispatch`)](#9-核心场景-7-投研恢复与上线外箱派发-research-worker--submission-dispatch)
10. [数据库维护、清理与磁盘物理空间释放 (`clean-db`)](#10-数据库维护清理与磁盘物理空间释放-clean-db)
11. [Python 高阶 API 参考](#11-python-高阶-api-参考)
12. [常见问题与故障排查 (FAQ)](#12-常见问题与故障排查-faq)

---

## 1. 环境与认证配置

### 1.1 Python 环境
```bash
# 运行环境需要 Python 3.10+
python --version
pip install -r requirements.txt
```

### 1.2 WorldQuant BRAIN 凭据配置
项目根目录维护 `.brain.json` 凭据文件：
```json
{
  "email": "your_email@example.com",
  "password": "your_password"
}
```
- 首次发起平台请求时，系统会自动登录并将会话 Cookie 缓存至 `.brain_session.json`。
- 后续请求将直接复用会话，实现毫秒级免密连接。若提示凭据失效，只需删除 `.brain_session.json` 即可自动重新登录。

### 1.3 数据库初始化 (零提交规范)
系统主库位于 [`data/alpha_research.db`](file:///d:/quant/alpha_factory/data/alpha_research.db)（已加入 `.gitignore`，严禁提交二进制 db 到代码库）。
拉取代码后执行一键初始化：
```bash
python init_db.py           # 默认初始化或增量升级数据表结构与索引
python init_db.py --verify  # 校验数据库完整性与已应用的 Schema 版本
```

---

## 2. CLI 统一命令速查表

| 子命令 | 命令类型 | 核心功能 | 是否消耗回测配额 |
| :--- | :---: | :--- | :---: |
| **`research-cycle`** 🌟 | 工业级流水线 | 全新 DDD 10 阶段标准化投研生命周期 (4 大纯抽样算法 & 2D 跨字段共识后剪枝) | 仅在指定 `--execute` 时消耗 |
| **`auto-pilot`** 🚀 | 无人值守流水线 | 一键串联: 预检 ➔ 真实并发挖掘 ➔ 6 维证据终审 ➔ 空间清理 ➔ 生产研报汇总 | 仅在指定 `--execute` 时消耗 |
| **`mine`** 🌟 | 工业级流水线 | 10 大模板族分层抽样、分批安全回测、流式落库、智能剪枝与自优化 | 仅在指定 `--execute` 时消耗 |
| **`research`** 🌟 | 工业级流水线 | PDF/MD 论文假说提取、动态字段对齐、在线回测与 AlphaJudge 终审 | 仅在指定 `--execute` 时消耗 |
| **`status`** 📊 | 生产看板 | 查看当前 Alpha 库统计、夏普分布、模板沉淀与批次状态 | ❌ 零消耗 (本地操作) |
| **`init-db`** 🛠️ | 运维与环境 | 一键初始化/校验 SQLite 研究数据库 17 张核心数据表与索引 | ❌ 零消耗 (本地操作) |
| **`clean-db`** 🧹 | 运维与环境 | 清理失败任务、剪枝项或历史数据，并执行 VACUUM 释放物理磁盘空间 | ❌ 零消耗 (本地操作) |
| **`drill-recovery`** 🛡️ | 治理与演练 | 执行事件溯源小批崩溃恢复与 6 维提交证据审批全流程演练 | ❌ 零消耗 (隔离沙盒) |
| **`research-worker`** 🔄 | 异步断点恢复 | 恢复并执行已提交、未终态的 event-led 研究批次 | 仅在指定 `--execute` 时消耗 |
| **`submission-dispatch`** 🚀 | 上线外箱 | 派发已审批的提交 outbox，安全幂等提交上线 | 消耗提交配额 |
| **`discover`** | 基础探索 | 检索目标市场全量可用字段（按覆盖度、用户数、类型筛选） | ❌ 零消耗 (只读) |
| **`prepare`** | 基础生成 | 字段原子包装、一阶特征矩阵展开、配置多重 Decay 生成任务池 | ❌ 零消耗 (本地计算) |
| **`simulate`** | 平台仿真 | 安全并发提交回测任务并轮询 IS 绩效与 18 项 Checks | 仅在指定 `--execute` 时消耗 |
| **`filter`** | 质量门禁 | 按 Sharpe、Fitness、Turnover、Margin 离线过滤潜力因子 | ❌ 零消耗 (本地计算) |
| **`simulate-super`** | 资产组合 | 将多个异构 Alpha 通过 Gram-Schmidt 正交化与 HRP 算法合成为 Super Alpha | 仅在指定 `--execute` 时消耗 |

---

## 3. 核心场景 1: 全新 DDD 10 阶段投研生命周期 (`research-cycle`) 🌟

严格遵循领域驱动设计 4 大限界上下文与 10 阶段流水线，提供 4 大纯抽样算法与 2D 跨字段共识剪枝：

```bash
# 1. 默认试运行 (Dry-run, 推荐使用 D-Optimal 最大信息增益覆盖抽样)
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal \
    --sample-per-family 4

# 2. 使用 Thompson 贝叶斯自适应多臂老虎机探索
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm thompson \
    --sample-per-family 4

# 3. 在线并发执行真实平台回测并记录遥测数据
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal \
    --sample-per-family 4 \
    --execute \
    --telemetry-file runs/telemetry.jsonl
```

---

## 4. 核心场景 2: 全自动无人值守投研流水线 (`auto-pilot`) 🚀

一键串联：环境自检 ➔ 真实并发回测 ➔ 6 维证据终审 ➔ 空间释放 (VACUUM) ➔ 汇总研报生成：

```bash
# 1. 命令行直接运行:
python alpha_machine.py auto-pilot \
    --region GBR --universe TOP700 \
    --datasets analyst7 \
    --sample-per-family 4 --batch-size 5 \
    --execute

# 2. Linux / macOS 后台一键无人值守启动 (自动后台运行并持久化日志):
./run_autopilot.sh GBR TOP700 "analyst7,fundamental31" 4 5 SUBINDUSTRY

# 3. Windows PowerShell 后台启动 (带色彩高亮与日志流):
.\run_autopilot.ps1 -Region GBR -Universe TOP700 -Datasets "analyst7" -SamplePerFamily 4 -BatchSize 5
```

---

## 5. 核心场景 3: 分层地毯式挖掘与自优化 (`mine`)

针对指定市场（如英国 GBR）与纯另类数据集（如高管交易、形态识别、基本面等），实现全自动地毯式生成、均衡分层抽样、分批安全回测与正信号自进化：

```bash
# 真实在线分批回测与全闭环自优化 (消耗回测额度)
python alpha_machine.py mine \
    --region GBR \
    --universe TOP700 \
    --datasets "insider_agg_matrix,pattern_scores,fundamental31" \
    --sample-per-family 4 \
    --batch-size 5 \
    --decay 12 \
    --neutralization SUBINDUSTRY \
    --execute \
    --output runs/reports/gbr_carpet_mining_report.md
```

### 10 大生成族群简介
1. `ts_momentum`（时序动量）
2. `mean_reversion`（均值反转）
3. `macd_velocity`（MACD 加速度）
4. `relative_ratio`（截面相对比率）
5. `asymmetric_risk`（不对称波动风险）
6. `sector_decomposition`（行业-特质正交分解）
7. `three_tier_scaling`（三层架构尺度标准化）
8. `cross_interaction`（多源跨数据集协同）
9. `symbolic_evolution`（递归 AST 符号自由杂交）
10. `evolved_distillation`（数据库沉淀模板动态实例化）

---

## 6. 核心场景 4: 学术文献研报认知转化流水线 (`research`)

直接将学术论文（PDF 或 Markdown）转化为在线实测 Alpha 并完成 AlphaJudge 终审与入库：

```bash
# 1. 基础文献解析与对齐
python alpha_machine.py research \
    --paper docs/academic_paper.pdf \
    --region GBR \
    --datasets "model30,risk71" \
    --decay 10 \
    --neutralization SUBINDUSTRY \
    --execute \
    --output data/gbr_paper_report.md

# 2. 启用大模型 (DeepSeek / OpenAI / Qwen) 深度因果提取与失败反思
python alpha_machine.py research \
    --paper docs/academic_paper.pdf \
    --region GBR \
    --datasets "model30,risk71" \
    --use-llm \
    --provider deepseek \
    --model deepseek-chat \
    --execute \
    --output data/gbr_paper_report.md
```

---

## 7. 核心场景 5: 超级组合因子与正交化配置 (`simulate-super`)

将多个经过实测的异构高收益因子，通过 Gram-Schmidt 信号正交化与 HRP 资产配置组合成 Super Alpha：

```bash
# 1. 从普通回测候选准备 Super Alpha 候选
python alpha_machine.py prepare-super \
    --region GBR --universe TOP700 \
    --max-candidates 6 \
    --output data/super_candidates.json

# 2. 提交回测 Super Alpha 候选
python alpha_machine.py simulate-super \
    --region GBR --universe TOP700 \
    --candidates data/super_candidates.json \
    --execute \
    --output data/super_results.json
```

---

## 8. 核心场景 6: 基础生成、回测与轮询 (`discover` / `prepare` / `simulate`)

适合细粒度定制单步流程的研究员：

```bash
# 1. 发现字段
python alpha_machine.py discover \
    --region GBR --universe TOP700 --dataset analyst7 \
    --min-coverage 0.8 --output runs/fields.json

# 2. 准备任务
python alpha_machine.py prepare \
    --fields runs/fields.json \
    --decays 6,12 --output runs/tasks.json

# 3. 提交仿真
python alpha_machine.py simulate \
    --region GBR --universe TOP700 \
    --tasks runs/tasks.json --execute \
    --output runs/results.json
```

---

## 9. 核心场景 7: 投研恢复与上线外箱派发 (`research-worker` / `submission-dispatch`)

```bash
# 恢复中断的投研批次
python alpha_machine.py research-worker --round-id <ROUND_ID>

# 派发已审批合格的提交任务 (Saga 异步外箱)
python alpha_machine.py submission-dispatch --limit 50
```

---

## 10. 数据库维护、清理与磁盘物理空间释放 (`clean-db`)

随着海量回测与地毯式挖掘的推进，SQLite 主库可能会积累失败/剪枝任务与 WAL 日志。系统提供细粒度清理与物理空间彻底回收能力：

```bash
# 1. 综合清理失败任务、被剪枝淘汰项与孤儿 Checks 数据并执行 VACUUM (默认)
python clean_db.py --mode stale

# 2. 安全预览模式 (Dry-Run: 仅统计将删除的行数与文件大小变化，不实际删除)
python clean_db.py --mode stale --dry-run

# 3. 仅清理失败项
python clean_db.py --mode failed

# 4. 清空全部历史回测实验数据 (保留表结构、模板库与剪枝规则)
python clean_db.py --mode all_data

# 5. 或通过主 CLI 调用
python alpha_machine.py clean-db --mode stale
```

---

## 11. Python 高阶 API 参考

### 11.1 分层地毯式挖掘 API
```python
from alpha_operator_framework.carpet_mining import run_stratified_carpet_mining

result = run_stratified_carpet_mining(
    region="GBR",
    universe="TOP700",
    datasets=["insider_agg_matrix", "pattern_scores", "fundamental31"],
    sample_per_family=4,
    batch_size=5,
    decay=12,
    neutralization="SUBINDUSTRY",
    execute=True,
    output_report_path="data/gbr_carpet_mining_report.md",
)
print(result.summary_markdown())
```

### 11.2 DDD 投研周期 API
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

use_case = ResearchCycleUseCase(
    research_repo=SqliteResearchRepository(),
    experiment_repo=SqliteExperimentRepository(),
    knowledge_repo=SqliteKnowledgeRepository(),
    backtest_gateway=BrainBacktestGateway(execute=False),
    submission_gateway=BrainSubmissionGateway(),
)
result = use_case.execute(ResearchCycleRequest(region="GBR", universe="TOP700", algorithm="d_optimal"))
print(f"生成的候选数: {len(result.round.candidates)}")
```

---

## 12. 常见问题与故障排查 (FAQ)

### Q1: 回测时遇到 `sqlite3.OperationalError: database is locked`？
- **机制**：框架底层已全面启用 WAL 模式 (`PRAGMA journal_mode = WAL`) 并设置 30 秒等待超时，初始化 DDL 具备幂等守卫，杜绝并发锁表。

### Q2: 为什么 `alpha_machine.py mine` 或 `research-cycle` 没有指定 `--execute` 时瞬间完成？
- **机制**：默认运行为 **Dry-Run 模式**（毫秒级完成公式生成与抽样预览），**绝不浪费您的平台回测配额**。确认任务符合预期后，加上 `--execute` 即可开始真实回测。

### Q3: 另类数据集中的稀疏字段（如事件型数据）出现报错怎么处理？
- **机制**：框架的 AST 编译器已内置原子包装机制：对于稀疏向量/事件数据，自动采用 `winsorize(ts_backfill(vec_avg({field}), 120), std=4.0)` 进行前向填充与去极值，确保 100% 语法合规与稳健计算。
