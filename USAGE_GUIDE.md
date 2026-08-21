# Alpha Factor Operator Framework 用户与实战操作指南

> 本指南帮助您快速掌握 Alpha 因子研发的全套流水线，涵盖从**一键分层地毯式挖掘 (`mine`)**、**前沿学术文献研报转化 (`research`)** 到 **传统三段式调研 (`survey` → `deepen` → `submit`)** 与 **超级因子组合 (`simulate-super`)** 的完整实战操作。

---

## 目录

1. [环境与认证配置](#1-环境与认证配置)
2. [一键 CLI 命令速查表](#2-一键-cli-命令速查表)
3. [核心场景 1: 一键分层地毯式挖掘与自优化 (`mine`)](#3-核心场景-1-一键分层地毯式挖掘与自优化-mine)
4. [核心场景 2: 一键学术文献研报端到端研发 (`research`)](#4-核心场景-2-一键学术文献研报端到端研发-research)
5. [核心场景 3: 传统三段式探索 (`survey` → `deepen` → `submit`)](#5-核心场景-3-传统三段式探索-survey--deepen--submit)
6. [核心场景 4: 超级组合因子与正交化配置 (`simulate-super`)](#6-核心场景-4-超级组合因子与正交化配置-simulate-super)
7. [Python 核心 API 参考](#7-python-核心-api-参考)
8. [数据库分析与 SQL 常用查询](#8-数据库分析与-sql-常用查询)
9. [常见问题与故障排查 (FAQ)](#9-常见问题与故障排查-faq)

---

## 1. 环境与认证配置

### 1.1 Python 环境
```powershell
# 运行环境需要 Python 3.10+
python --version
```

### 1.2 WorldQuant BRAIN 凭据配置
项目根目录维护 `.brain.json` 凭据文件：
```json
{
  "email": "your_email@example.com",
  "password": "your_password"
}
```
- 首次发起平台请求时，系统会自动完成登录并将会话 Cookie 缓存至 `.brain_session.json`。
- 后续请求将直接复用会话，实现毫秒级免密连接。若提示凭据失效，只需删除 `.brain_session.json` 即可自动重新登录。

### 1.3 数据库路径与一键初始化 (无需提交 .db)
系统主库位于 [`data/alpha_research.db`](file:///d:/quant/alpha_factory/data/alpha_research.db)（已加入 `.gitignore`，严禁提交二进制 db 到代码库）。
项目拉取后或需要校验数据库时，执行一键初始化：
```powershell
python init_db.py           # 默认初始化或增量升级数据表结构与索引
python init_db.py --verify  # 校验数据库完整性与已应用的 Schema 版本
```

---

## 2. 一键 CLI 命令速查表

| 子命令 | 命令类型 | 核心功能 | 是否消耗回测额度 |
| :--- | :---: | :--- | :---: |
| **`init-db`** 🛠️ | 运维与环境 | 一键初始化/校验 SQLite 研究数据库 17 张核心数据表与索引 | ❌ 零消耗 (本地操作) |
| **`clean-db`** 🧹 | 运维与环境 | 清理失败任务、剪枝表达式或历史数据，并执行 VACUUM 释放物理空间 | ❌ 零消耗 (本地操作) |
| **`mine`** 🌟 | 工业级流水线 | 一键海量生成、6 大模板族分层抽样、分批回测、实时流式落库、智能剪枝与正向自优化 | 仅在指定 `--execute` 时消耗 |
| **`research`** 🌟 | 工业级流水线 | 一键解析 PDF/Markdown 论文，提取因果假说，动态映射真实字段，在线回测与 AlphaJudge 终审落库 | 仅在指定 `--execute` 时消耗 |
| **`discover`** | 基础探索 | 检索目标市场全量可用字段（按覆盖度、用户数、类型筛选） | ❌ 零消耗 (只读) |
| **`prepare`** | 基础生成 | 字段原子包装、一阶特征矩阵展开、配置多重 Decay 生成任务池 | ❌ 零消耗 (本地计算) |
| **`simulate`** | 平台仿真 | 安全并发提交回测任务并轮询 IS 绩效与 18 项 Checks | 仅在指定 `--execute` 时消耗 |
| **`filter`** | 质量门禁 | 按 Sharpe、Fitness、Turnover、Margin 离线过滤潜力因子 | ❌ 零消耗 (本地计算) |
| **`simulate-super`** | 资产组合 | 将多个异构 Alpha 通过 Gram-Schmidt 正交化与 HRP 算法合成为 Super Alpha | 仅在指定 `--execute` 时消耗 |


---

## 3. 核心场景 1: 一键分层地毯式挖掘与自优化 (`mine`)

针对指定市场（如英国 GBR）与纯另类数据集（如高管交易、形态识别、基本面等），实现全自动地毯式生成、均衡分层抽样、分批安全回测与正信号自进化：

### 3.1 极速 Dry-Run 任务预览 (0.1秒，零额度消耗)
```powershell
python alpha_machine.py mine `
  --region GBR `
  --universe TOP700 `
  --datasets "insider_agg_matrix,pattern_scores,fundamental31" `
  --sample-per-family 3
```

### 3.2 真实在线分批回测与全闭环自优化 (消耗额度)
```powershell
python alpha_machine.py mine `
  --region GBR `
  --universe TOP700 `
  --datasets "insider_agg_matrix,pattern_scores,fundamental31,risk60" `
  --sample-per-family 4 `
  --batch-size 5 `
  --decay 12 `
  --neutralization SUBINDUSTRY `
  --execute `
  --output data/gbr_carpet_mining_report.md
```

### 3.3 关键参数详解
- `--datasets, -d`：指定要挖掘的数据集 ID（支持以逗号分隔传入多个另类数据集）；
- `--sample-per-family, -s`：**每一类表达式随机抽选的数量**（系统将表达式自动归为动量、均值回归、MACD、相对比率、不对称风险、跨源协同 6 大族）；
- `--batch-size, -b`：**平台回测每批任务数**（每跑完 1 批，立刻自动完成数据库存储，不怕网络意外中断）；
- `--execute, -e`：指定后正式向 BRAIN 官方服务器提交模拟。

---

## 4. 核心场景 2: 一键学术文献研报端到端研发 (`research`)

直接将学术论文（PDF 或 Markdown）转化为在线实测 Alpha 并完成评级落库：

### 4.1 运行指令
```powershell
python alpha_machine.py research `
  --paper "papers/2605.09712v1_Quantifying_the_Risk-Return_Tradeoff_in_Forecasting.pdf" `
  --region GBR `
  --datasets "model30,risk71" `
  --decay 10 `
  --neutralization SUBINDUSTRY `
  --execute `
  --output data/gbr_paper_report.md
```

### 4.2 启用大模型深度因果语义提炼
若需启用大模型（支持 DeepSeek / OpenAI / Qwen / Ollama）进行深度因果提取：
```powershell
python alpha_machine.py research `
  --paper "papers/2605.09712v1_Quantifying_the_Risk-Return_Tradeoff_in_Forecasting.pdf" `
  --region GBR `
  --datasets "model30,risk71" `
  --use-llm `
  --provider deepseek `
  --model deepseek-chat `
  --execute `
  --output data/gbr_paper_report.md
```

---

## 5. 核心场景 3: 传统三段式探索 (`survey` → `deepen` → `submit`)

使用编排器分步推进大样本探索：

```powershell
# 1. Survey 阶段: 调研全市场模板胜率密度
python -m alpha_operator_framework.orchestrator survey `
  --region GBR --universe TOP700 --delay 1 `
  --sample 80 --execute

# 2. Deepen 阶段: 针对高胜率模板深度挖掘
python -m alpha_operator_framework.orchestrator deepen `
  --density-out runs/survey_density.json `
  --sample 300 --execute

# 3. Submit 阶段: 触发平台 18 项 Checks 终审
python -m alpha_operator_framework.orchestrator submit `
  --kept-out runs/deepen_kept.json --execute
```

---

## 6. 核心场景 4: 超级组合因子与正交化配置 (`simulate-super`)

将多个经过实测的异构高收益因子，通过 Gram-Schmidt 信号正交化与 HRP 资产配置组合成 Super Alpha：

```powershell
python alpha_machine.py simulate-super `
  --alphas "9qXQPxOK,6XlbPWpO,MP7AqRL8" `
  --region GBR `
  --universe TOP700 `
  --method HRP `
  --execute `
  --output data/super_alpha_report.md
```

---

## 7. Python 核心 API 参考

### 7.1 分层地毯式挖掘 API
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

# 打印 Markdown 总结研报
print(result.summary_markdown())

# 获取第一代与优化后的全部结果
print(f"第一代实测: {len(result.first_gen_results)}, 二代优化: {len(result.optimized_results)}")
```

### 7.2 学术文献流水线 API
```python
from alpha_operator_framework.research import run_literature_research_pipeline

result = run_literature_research_pipeline(
    literature_source="papers/academic_paper.pdf",
    region="GBR",
    datasets=["model30", "risk71"],
    neutralization="SUBINDUSTRY",
    delay=1,
    decay=8,
    execute_on_platform=True,
    save_to_db=True,
    output_report_path="gbr_research_report.md",
)
```

---

## 8. 数据库维护、清理与磁盘空间释放

随着海量回测与地毯式挖掘的推进，SQLite 主库可能会积累失败/剪枝任务与 WAL 日志。系统提供了一整套命令行与 Python API 工具用于轻量化清理和磁盘物理空间释放。

### 8.1 快速 CLI 维护命令

```powershell
# 1. 释放磁盘物理空间 (执行 WAL Checkpoint + VACUUM，不删除任何业务数据)
python clean_db.py --mode vacuum

# 2. 清理失败/异常任务并自动释放磁盘空间 (默认模式)
python clean_db.py

# 3. 综合清理失败任务、被剪枝淘汰项与孤儿 Checks 数据
python clean_db.py --mode stale

# 4. 安全预览模式 (Dry-Run: 仅统计将删除的行数与文件大小变化，不实际删除)
python clean_db.py --mode stale --dry-run

# 5. 清空全部历史回测实验数据 (保留表结构、模板库与剪枝规则)
python clean_db.py --mode all_data

# 6. 或通过统一 CLI 调用
python alpha_machine.py clean-db --mode stale
```

### 8.2 Python API 调用方式

```python
from alpha_operator_framework.database import clean_alpha_research_db, vacuum_database

# 仅释放物理磁盘空间
report = vacuum_database()

# 综合清理并释放磁盘空间
report = clean_alpha_research_db(mode="stale", vacuum=True)
print(report.summary_text())
```

---

## 9. 数据库分析与 SQL 常用查询

主数据库位于 [`data/alpha_research.db`](file:///d:/quant/alpha_factory/data/alpha_research.db)。您可以使用 Python 或任何 SQLite GUI 工具（如 DBeaver, SQLiteStudio）执行分析。

### 常用查询 1: 查询夏普最高的前 10 个 Alpha
```sql
SELECT alpha_id, expression, sharpe, fitness, turnover, returns, drawdown, wf_stage
FROM alpha_details
ORDER BY sharpe DESC
LIMIT 10;
```

### 常用查询 2: 查询纯另类数据因子的表现榜单
```sql
SELECT d.alpha_id, e.expression_origin, d.expression, d.sharpe, d.fitness, d.turnover, d.returns, d.drawdown
FROM alpha_details d
JOIN alpha_expressions e ON d.expression_sha = e.expression_sha
WHERE e.expression_origin LIKE 'carpet_mining:%'
ORDER BY d.sharpe DESC;
```

### 常用查询 3: 检查指定 Alpha 的 18 项平台 Checks 状态
```sql
SELECT check_name, status, details
FROM alpha_checks
WHERE alpha_id = '9qXQPxOK'
ORDER BY status ASC;
```

---

## 10. 常见问题与故障排查 (FAQ)

### Q1: 回测时遇到 `sqlite3.OperationalError: disk I/O error` 或 `database is locked`？
- **原因**：Windows 环境下多个连接频繁重复执行 DDL (`CREATE TABLE`) 会导致表级锁冲突。
- **解决**：框架已全面启用 WAL 模式 (`PRAGMA journal_mode = WAL`) 并设置 30 秒等待超时，初始化 DDL 具备幂等守卫，确保高并发无锁运行。

### Q2: 为什么 `alpha_machine.py mine` 没有指定 `--execute` 时瞬间完成？
- **机制**：默认运行为 **Dry-Run 模式**（0.1 秒内完成 5,000+ 表达式生成与分层抽样预览），**绝不浪费您的平台回测配额**。确认候选任务符合预期后，加上 `--execute` 即可开始真实在线回测。

### Q3: 另类数据集中的稀疏字段（如事件型数据）出现报错怎么处理？
- **机制**：框架的 AST 编译器已内置原子包装机制：对于稀疏向量/事件数据，自动采用 `winsorize(ts_backfill(vec_avg({field}), 120), std=4.0)` 进行前向填充与去极值，确保 100% 语法合规与计算稳健。

