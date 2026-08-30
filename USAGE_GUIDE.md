# Alpha Factory — 用户指导手册 (Usage Guide)

> **版本**: v2.0 | **更新日期**: 2026-08-25 | **适用对象**: 量化研究人员 / 系统运维人员

---

## 目录

1. [环境准备与认证配置](#1-环境准备与认证配置)
2. [CLI 命令完整参考](#2-cli-命令完整参考)
3. [核心场景实战](#3-核心场景实战)
4. [Python API 调用参考](#4-python-api-调用参考)
5. [数据库运维与 SQL 速查](#5-数据库运维与-sql-速查)
6. [常见问题与故障排查](#6-常见问题与故障排查)

---

## 1. 环境准备与认证配置

### 1.1 Python 环境

```bash
# 运行环境需要 Python 3.10+
python --version
pip install -r requirements.txt
```

### 1.2 WorldQuant BRAIN 凭据

在项目根目录创建 `.brain.json`：

```json
{
  "email": "your_email@example.com",
  "password": "your_password"
}
```

> [!NOTE]
> 首次发起平台请求时系统自动登录并缓存会话至 `.brain_session.json`。若凭据失效，删除 `.brain_session.json` 即可自动重新登录。

### 1.3 数据库初始化（首次运行必做）

```bash
# 初始化 SQLite 主库并注入 30+ 模板种子
python init_db.py

# 或使用统一 CLI
python alpha_machine.py init-db

# 校验数据库完整性
python init_db.py --verify
```

### 1.4 验证安装

```bash
# 运行全套 465 项自动化测试（100% 通过）
python -m pytest -q

# 崩溃恢复演练（生产前推荐执行一次）
python alpha_machine.py drill-recovery

# 查看当前投研库状态
python alpha_machine.py status
```

---

## 2. CLI 命令完整参考

统一入口：`python alpha_machine.py <子命令> [选项]`

### 2.1 命令总览速查表

| 子命令 | 域 | 核心功能 | 消耗配额 |
|:---|:---:|:---|:---:|
| `research-cycle` | research | DDD 10 阶段标准化投研生命周期（4 大纯抽样算法） | `--execute` 才消耗 |
| `auto-pilot` | research | 全自动无人值守流水线（预检→回测→审批→清理→研报） | `--execute` 才消耗 |
| `mine` | research | 分层地毯式多模板族 Alpha 挖掘 | `--execute` 才消耗 |
| `research` | research | 学术文献 PDF 假说提取 + 字段对齐，本地报告 | 不访问平台 |
| `research-worker` | research | 断点恢复已提交批次 | `--execute` 才消耗 |
| `research-rebuild` | research | 从事件流重放重建特定轮次状态 | ❌ 本地 |
| `submission-dispatch` | submission | 派发已审批的 Outbox，幂等正式提交 | ✅ 消耗提交配额 |
| `discover` | fields | 检索目标市场全量可用字段 | ❌ 只读 |
| `prepare` | fields | 字段→一阶特征矩阵任务池生成 | ❌ 本地 |
| `filter` | fields | 多维条件离线过滤候选 Alpha | ❌ 本地 |
| `second-order` | fields | 二阶字段组合任务生成 | ❌ 本地 |
| `simulate` | simulation | 安全并发提交回测并轮询 IS 绩效 | `--execute` 才消耗 |
| `poll-simulation` | simulation | 查询已提交批次的最新状态 | ❌ 只读 |
| `prepare-super` | super_alpha | 从 Alpha 池筛选正交组合候选 | ❌ 本地 |
| `simulate-super` | super_alpha | 正交化超级因子回测 | `--execute` 才消耗 |
| `poll-super` | super_alpha | 查询超级因子回测状态 | ❌ 只读 |
| `init-db` | operations | 初始化/校验 SQLite 数据库 24+ 张核心/运行时表 | ❌ 本地 |
| `clean-db` | operations | 清理失败/剪枝数据并 VACUUM 释放磁盘 | ❌ 本地 |
| `storage-backup` | operations | 在线热备数据库文件 | ❌ 本地 |
| `storage-restore` | operations | 从备份恢复数据库 | ❌ 本地 |
| `drill-recovery` | operations | 崩溃恢复与 6 维证据审批全流程演练 | ❌ 沙盒 |
| `status` | operations | 查看生产投研看板统计 | ❌ 只读 |

---

### 2.2 research-cycle（DDD 10 阶段投研周期）

```bash
python alpha_machine.py research-cycle \
    --region <市场区域>          # GBR / USA / CHN ...（必需）
    --universe <股票宇宙>        # TOP700 / TOP2000 ...（必需）
    --delay <延迟天数>           # 默认 1
    --decay <衰减参数>
    --neutralization <中性化>    # SUBINDUSTRY / INDUSTRY / MARKET
    --truncation <截断比例>      # 默认 0.08
    --datasets <数据集>          # 逗号分隔，可选
    --mode <构建模式>            # template / multi-stage / multivariate
    --algorithm <抽样算法>       # stratified / d_optimal / thompson / ucb / diversity
    --seed <随机种子>            # 默认 42
    --round-id <轮次ID>          # 可选，用于追踪
    --config <配置文件路径>      # 默认 configs/alpha-factory.yaml
    --telemetry-file <遥测文件>  # 可选，JSON Lines 输出
    --execute                    # ⚠️ 授权真实回测（默认 Dry-run）
    --authorize-submission       # 授权审批通过后自动提交
    --submission-evidence-file <路径>
```

**典型用法**：

构建策略只能在 YAML 中显式声明；下面示例同时启用四类策略。`quota_per_leaf_family: 8` 表示每个 `策略/模板族/深度/字段数` 叶子族最多进入平台回测 8 条，不限制前置候选生成量。

```yaml
research:
  construction:
    strategies:
      - id: database-base
        kind: database_template
        families: ["*"]
        order_depth: {min: 0, max: 3}
        field_count: {min: 1, max: 2}
        quota_per_leaf_family: 8
        source: raw_fields
      - id: depth-3
        kind: depth_construction
        families: ["*"]
        order_depth: {exact: 3}
        field_count: {min: 1, max: 2}
        quota_per_leaf_family: 8
        source: raw_and_qualified_candidates
      - id: fields-2
        kind: field_composition
        families: ["*"]
        order_depth: {min: 1, max: 3}
        field_count: {exact: 2}
        quota_per_leaf_family: 8
        source: raw_and_qualified_candidates
      - id: paper-alpha
        kind: literature_llm
        families: [paper_hypothesis]
        document: ../docs/academic_paper.pdf
        llm_profile: deepseek
        order_depth: {min: 1, max: 3}
        field_count: {min: 1, max: 2}
        quota_per_leaf_family: 8
        source: raw_fields
    parent_gate:
      # 初始表达式晋升到下一构造阶段的门；不等同于提交候选门。
      sharpe: {operator: gt, value: 0.6}
      fitness: {operator: gt, value: 0.4}
    promotion:
      quality:
        min_long_short_sum: 20
        max_consecutive_flat_days: 200
        max_tail_flat_ratio: 0.30
      correlation:
        enabled: true
        channels: [sharpe, fitness, margin]
        first_threshold: 0.85
        second_threshold: 0.80
        final_threshold: 0.75
        min_periods: 100
      validation:
        enabled: true
        minimum_sharpe_ratio: 0.50
      early_stop_signal_count: 8
    platform_batch_size: 8
```

同一表达式被多个策略生成时只回测一次，但数据库会保留全部来源。多阶/多元策略仅在 `source` 显式包含 `qualified_candidates` 且父 Alpha 通过晋升门时继续构建。`diversity`/`d_optimal` 是回测前结构多样性选择；回测后 PnL 多通道剪枝由 `promotion.correlation` 控制。

```bash
# D-Optimal 算法 Dry-run 试运行
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal

# Thompson 采样贝叶斯自适应探索 + 真实回测 + 遥测输出
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm thompson \
    --execute --telemetry-file runs/telemetry.jsonl

# D-Optimal + 授权自动提交审批达标因子
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal \
    --execute --authorize-submission \
    --submission-evidence-file runs/evidence.jsonl
```

---

### 2.3 auto-pilot（全自动无人值守）

```bash
python alpha_machine.py auto-pilot \
    --region <市场区域>          # 必需
    --universe <股票宇宙>        # 必需
    --delay <延迟天数>
    --config <配置文件路径>
    --datasets <数据集列表>      # 默认 analyst7
    --paper <论文PDF路径>        # 可选，加入文献提炼
    --sample-per-family <N>      # 默认 4
    --batch-size <批次大小>      # 默认 5
    --decay <衰减参数>           # 默认 12
    --neutralization <中性化>    # 默认 SUBINDUSTRY
    --truncation <截断比例>      # 默认 0.08
    --min-sharpe <最低夏普>      # 默认 1.25
    --min-fitness <最低适健度>   # 默认 1.0
    --execute                    # ⚠️ 授权真实回测
    --seed <随机种子>
    --no-clean                   # 跳过结束后的 VACUUM 清理
    --output <输出报告路径>      # Markdown 研报
```

**典型用法**：

```bash
# Python CLI 全自动生产运行
python alpha_machine.py auto-pilot \
    --region GBR --universe TOP700 \
    --datasets analyst7 \
    --sample-per-family 4 --batch-size 5 \
    --execute

# Windows PowerShell 后台无人值守（自动保存日志）
.\run_autopilot.ps1 -Region GBR -Universe TOP700 -Datasets "analyst7" -SamplePerFamily 4 -BatchSize 5

# Linux 后台无人值守
bash run_autopilot.sh GBR TOP700 analyst7 4 5
```

---

### 2.4 mine（分层地毯式 Alpha 挖掘）

```bash
python alpha_machine.py mine \
    --region <市场区域>          # 必需
    --universe <股票宇宙>        # 必需
    --delay <延迟天数>
    --datasets <数据集列表>      # 逗号分隔（必需）
    --sample-per-family <N>      # 默认 4
    --batch-size <批次大小>      # 默认 5
    --decay <衰减参数>           # 默认 12
    --neutralization <中性化>    # 默认 SUBINDUSTRY
    --truncation <截断比例>      # 默认 0.08
    --execute                    # ⚠️ 授权真实回测
    --seed <随机种子>
    --output <输出报告路径>
```

```bash
# 对多个另类数据集进行地毯式挖掘
python alpha_machine.py mine \
    --region GBR --universe TOP700 \
    --datasets "insider_agg_matrix,pattern_scores,fundamental31" \
    --sample-per-family 4 --batch-size 5 \
    --decay 12 --neutralization SUBINDUSTRY \
    --execute
```

---

### 2.5 research（文献认知提炼）

该命令仅提取假说并生成本地报告，不直接提交平台。论文驱动的真实回测必须作为 `research-cycle` 的显式 `literature_llm` 构建策略执行。

```bash
python alpha_machine.py research \
    --paper <论文PDF或MD路径>    # 必需
    --region <市场区域>
    --universe <股票宇宙>
    --delay <延迟天数>
    --neutralization <中性化>    # 默认 SUBINDUSTRY
    --decay <衰减参数>           # 默认 8
    --datasets <数据集>          # 可选限定字段范围
    --use-llm                    # 启用 LLM 假说提取
    --provider <LLM提供商>       # openai / deepseek / qwen
    --model <模型名称>           # deepseek-chat / gpt-4o ...
    --output <输出Markdown报告>
    --config <配置文件路径>
```

```bash
# Dry-run 预览（不消耗配额）
python alpha_machine.py research \
    --paper docs/academic_paper.pdf \
    --region GBR --universe TOP700

# 启用 DeepSeek LLM + 生成本地研报
python alpha_machine.py research \
    --paper docs/academic_paper.pdf \
    --region GBR --universe TOP700 \
    --use-llm --provider deepseek --model deepseek-chat \
    --output data/paper_research_report.md
```

---

### 2.6 simulate（平台仿真）

```bash
python alpha_machine.py simulate \
    --region <市场区域> --universe <股票宇宙> --delay <延迟天数> \
    --tasks <任务文件.json>      # 必需，含 expression/decay 的任务列表
    --output <输出结果.json>     # 必需
    --execute                    # ⚠️ 授权真实提交
    --batch-size <N>             # 默认 8
    --neutralization SUBINDUSTRY \
    --truncation 0.08

# 查询批次状态
python alpha_machine.py poll-simulation \
    --batch-id <批次ID> \
    --output runs/poll.json
```

---

### 2.7 simulate-super（超级因子）

```bash
# 第一步：筛选正交化候选
python alpha_machine.py prepare-super \
    --region GBR --universe TOP700 --delay 1 \
    --output runs/super_candidates.json \
    --max-candidates 6 \
    --decay 6 --neutralization SUBINDUSTRY --truncation 0.08

# 第二步：提交超级因子回测
python alpha_machine.py simulate-super \
    --region GBR --universe TOP700 --delay 1 \
    --candidates runs/super_candidates.json \
    --output runs/super_result.json \
    --execute

# 第三步：查询结果
python alpha_machine.py poll-super \
    --batch-id <批次ID> \
    --output runs/super_poll.json
```

---

### 2.8 字段探索流水线（discover / prepare / filter）

```bash
# 探索目标市场字段
python alpha_machine.py discover \
    --region GBR --universe TOP700 --delay 1 \
    --output runs/fields.json \
    [--dataset <数据集ID>] [--type MATRIX] \
    [--min-coverage 0.5] [--max-users 100] [--limit 200]

# 字段→任务池生成
python alpha_machine.py prepare \
    --fields runs/fields.json \
    --output runs/tasks.json \
    --windows 5 22 66 252 --decays "6,12" --batch-size 8

# 离线质量过滤
python alpha_machine.py filter \
    --results runs/sim_results.json \
    --output runs/winners.json \
    --sharpe 1.2 --fitness 0.7 \
    --margin 5 --min-turnover 0.01 --max-turnover 0.7
```

---

### 2.9 数据库运维命令

```bash
# 初始化
python alpha_machine.py init-db [--reset] [--verify]
python init_db.py [--reset] [--verify]

# 清理（--dry-run 预览，不实际删除）
python alpha_machine.py clean-db --mode stale [--dry-run] [--no-vacuum]
python clean_db.py --mode stale [--dry-run]
# 模式：failed / pruned / pending / stale / all_data

# 备份与恢复
python alpha_machine.py storage-backup --destination backups/alpha_20260825.db
python alpha_machine.py storage-restore --backup backups/alpha_20260825.db

# 崩溃恢复演练
python alpha_machine.py drill-recovery

# 断点续传
python alpha_machine.py research-worker \
    --round-id <轮次ID> [--watch] [--poll-seconds 30] [--authorize-submission]

# 派发审批通过的提交 Outbox
python alpha_machine.py submission-dispatch --limit 50 --max-attempts 3
```

---

## 3. 核心场景实战

### 3.1 首次全自动生产运行

```bash
# 1. 环境初始化
python init_db.py
python -m pytest -q                 # 验证 465 项测试通过

# 2. 崩溃恢复演练（推荐在正式生产前执行一次）
python alpha_machine.py drill-recovery

# 3. 正式全自动生产运行
python alpha_machine.py auto-pilot \
    --region GBR --universe TOP700 \
    --datasets "analyst7" \
    --sample-per-family 4 --batch-size 5 \
    --execute \
    --output runs/report_$(date +%Y%m%d).md
```

---

### 3.2 文献驱动的假说挖掘

```bash
# 1. 提炼假说（Dry-run 预览，零配额消耗）
python alpha_machine.py research \
    --paper docs/momentum_paper.pdf \
    --region USA --universe TOP2000

# 2. 在 YAML 中配置 literature_llm 后，通过统一研究周期执行真实回测
python alpha_machine.py research-cycle \
    --region USA --universe TOP2000 \
    --datasets "fundamental31" \
    --round-id paper-momentum-001 \
    --execute
```

---

### 3.3 多数据集地毯式系统挖掘

```bash
for dataset in "insider_agg_matrix" "pattern_scores" "fundamental31" "analyst7"; do
    python alpha_machine.py mine \
        --region GBR --universe TOP700 \
        --datasets "$dataset" \
        --sample-per-family 4 --batch-size 5 \
        --decay 12 --execute \
        --output "runs/mine_${dataset}.md"
done
```

---

### 3.4 已有 Alpha 池提炼超级因子

```bash
# 1. 筛选正交化候选（Sharpe ≥ 1.25，Fitness ≥ 1.0）
python alpha_machine.py prepare-super \
    --region GBR --universe TOP700 --delay 1 \
    --output runs/super_candidates.json \
    --max-candidates 6

# 2. 提交超级因子回测
python alpha_machine.py simulate-super \
    --region GBR --universe TOP700 --delay 1 \
    --candidates runs/super_candidates.json \
    --output runs/super_result.json \
    --execute
```

---

### 3.5 断点续传与批次监控

```bash
# 查看当前状态
python alpha_machine.py status

# 恢复未完成批次
python alpha_machine.py research-worker \
    --watch --poll-seconds 30 \
    --authorize-submission

# 查询指定批次状态
python alpha_machine.py poll-simulation \
    --batch-id 42 --output runs/poll_42.json
```

---

### 3.6 定期数据库维护

```bash
# 预览待清理数据
python clean_db.py --mode stale --dry-run

# 执行清理 + VACUUM 释放磁盘空间
python clean_db.py --mode stale

# 热备（WAL 模式安全，不影响运行中的研究）
python alpha_machine.py storage-backup \
    --destination backups/alpha_$(date +%Y%m%d_%H%M).db
```

---

## 4. Python API 调用参考

### 4.1 基础表达式生成

```python
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.generation import sample_scalar_expressions, SampleSpec
from alpha_operator_framework.generation.templates import unary_factory

# 定义字段规格（禁止使用 close/open/high/low）
fields = [
    FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", coverage=0.98),
    FieldSpec(id="vwap",    dataset_id="pv1", type="MATRIX", coverage=0.95),
    FieldSpec(id="volume",  dataset_id="pv1", type="MATRIX", coverage=0.99),
]

# 字段采样 + 生成一阶 Alpha 任务
scalars = sample_scalar_expressions(fields, SampleSpec(sample_n=10))
tasks = unary_factory(scalars)
print(f"✅ 生成 {len(tasks)} 个一阶 Alpha 任务")
for t in tasks[:3]:
    print(f"   • {t.expression}")
```

### 4.2 DDD 用例 API

```python
from alpha_operator_framework.application.research_cycle import (
    ResearchCycleRequest, ResearchCycleUseCase,
)
from alpha_operator_framework.infrastructure.sqlalchemy_repositories import (
    SqliteResearchRepository, SqliteExperimentRepository,
)
from alpha_operator_framework.infrastructure.runtime_factory import build_backtest_gateway
from alpha_operator_framework.research.round import ResearchPolicy
from alpha_operator_framework.knowledge.models import KnowledgeBase

# 构建仓储与网关（Dry-run 模式）
research_repo   = SqliteResearchRepository()
experiment_repo = SqliteExperimentRepository()
backtest_gw     = build_backtest_gateway(execute=False)  # False = Dry-run 安全模式

# 组装用例
use_case = ResearchCycleUseCase(
    research_repository=research_repo,
    backtest_gateway=backtest_gw,
    experiment_repository=experiment_repo,
)

# 执行投研周期
policy = ResearchPolicy(
    region="GBR", universe="TOP700", delay=1,
    algorithm="d_optimal", sample_per_family=4,
)
summary = use_case.execute(
    ResearchCycleRequest(
        round_id="round-001", seed=42,
        policy=policy,
        knowledge=KnowledgeBase().snapshot(),
        candidates=[],
        execute_platform=False,
    )
)
print(f"✅ 周期完成，状态: {summary.status}")
```

### 4.3 多轮研究闭环 API

```python
import asyncio
from alpha_operator_framework.loop import LoopConfig, run_research_loop
from alpha_operator_framework.database.repository import AlphaDatabase

db = AlphaDatabase()
config = LoopConfig(
    rounds=3,
    region="GBR", universe="TOP700",
    top_k_fields=80, backtest_sample_n=80,
    execute=True,
    distill=True,
    distill_templates=True,
    distill_prune_rules=True,
)

history = asyncio.run(run_research_loop(db, config))
for r in history:
    print(f"轮次 {r['round']}: "
          f"规划字段 {len(r['planned_next_fields'])} 个, "
          f"蒸馏模板 {r['distilled_templates']} 条, "
          f"生成淘汰规则 {len(r['distilled_rules'])} 条")
```

### 4.4 防过拟合指标 API

```python
from alpha_operator_framework.domain.overfitting import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    compute_expected_max_sharpe,
)

best_sharpe = 1.5
trial_count = 100
obs_count = 252  # 约 1 年日度观测数

dsr = deflated_sharpe_ratio(
    sharpe_is=best_sharpe, trial_count=trial_count,
    obs_count=obs_count, skewness=0.0, excess_kurtosis=0.0, sr_std=0.5,
)
psr = probabilistic_sharpe_ratio(
    sharpe_is=best_sharpe, sharpe_benchmark=1.0, obs_count=obs_count,
)
e_max = compute_expected_max_sharpe(trial_count=100, sharpe_std=0.5)

print(f"DSR = {dsr:.3f}")
print(f"PSR = {psr:.3f}")
print(f"E[max Sharpe|N=100] = {e_max:.3f}")
```

---

## 5. 数据库运维与 SQL 速查

> 详细数据库架构见 [DATABASE_DESIGN.md](DATABASE_DESIGN.md)

### 5.1 常用分析 SQL

```sql
-- 1. IS 夏普最高的前 10 个 Alpha
SELECT alpha_id, expression, sharpe, fitness, turnover, returns, wf_stage
FROM alpha_details
ORDER BY sharpe DESC LIMIT 10;

-- 2. 各生成族群胜率与平均夏普
SELECT e.expression_origin, COUNT(*) AS total,
       AVG(d.sharpe) AS avg_sharpe, MAX(d.sharpe) AS max_sharpe
FROM alpha_details d
JOIN alpha_expressions e ON d.expression_sha = e.expression_sha
GROUP BY e.expression_origin
ORDER BY avg_sharpe DESC;

-- 3. 指定 Alpha 的 18 项 Checks 详细状态
SELECT check_name, result, value, "limit"
FROM alpha_checks
WHERE alpha_id = 'ALPHA_12345'
ORDER BY result ASC;

-- 4. 待审批提交候选池
SELECT alpha_id, expression, sharpe, fitness, turnover, margin, is_submitted
FROM alpha_submission_candidates
WHERE is_submitted = 0
ORDER BY sharpe DESC;

-- 5. 字段信号命中率 Top 20
SELECT field_id, dataset_id, region, universe,
       SUM(trials) AS total_trials,
       AVG(hit_rate) AS avg_hit_rate,
       MAX(max_sharpe) AS peak_sharpe
FROM field_signal_stats
GROUP BY field_id, dataset_id, region, universe
ORDER BY avg_hit_rate DESC LIMIT 20;

-- 6. 近 7 天回测批次状态
SELECT id, platform_batch_id, status,
       requested_count, completed_count, failed_count, created_at
FROM simulation_batches
WHERE created_at >= datetime('now', '-7 days')
ORDER BY created_at DESC;

-- 7. 防过拟合试验账本摘要
SELECT family, region, universe, COUNT(*) AS trial_count,
       AVG(json_extract(metrics_json, '$.sharpe')) AS avg_sharpe
FROM trial_ledger
GROUP BY family, region, universe
ORDER BY trial_count DESC;

-- 8. 模板库活跃模板统计
SELECT family, COUNT(*) AS template_count
FROM template_library WHERE active = 1
GROUP BY family ORDER BY template_count DESC;

-- 9. 剪枝规则库（最新 20 条）
SELECT pattern, pattern_type, family, reason, source, created_at
FROM template_prune_rules WHERE active = 1
ORDER BY created_at DESC LIMIT 20;
```

---

## 6. 常见问题与故障排查

### 6.1 数据库相关

**Q: `sqlite3.OperationalError: database is locked`**

A: 系统已内置 `PRAGMA busy_timeout = 30000`（30 秒等待重试）。若持续出现，检查并发写入进程：

```bash
# Windows
tasklist | findstr python
# 重启 Worker（自动清理残留锁）
python alpha_machine.py research-worker --round-id <ID>
```

**Q: 数据库磁盘占用过大**

```bash
python clean_db.py --mode stale   # 清理失败/剪枝数据并 VACUUM 释放物理空间
```

**Q: 数据库版本校验失败**

```bash
python init_db.py           # 增量升级 Schema（不删除现有数据）
python init_db.py --verify  # 查看当前版本
```

---

### 6.2 平台回测相关

**Q: 平台返回 429 Too Many Requests**

```bash
# 降低并发批次大小（默认 8）
python alpha_machine.py simulate ... --batch-size 3
```

**Q: 提交后长时间 ACCEPTED 无结果**

```bash
# 查询批次最新状态
python alpha_machine.py poll-simulation --batch-id <ID> --output poll.json

# 触发断点续传 Worker
python alpha_machine.py research-worker --round-id <ID> --watch
```

**Q: 凭据失效（Session Expired）**

```bash
del .brain_session.json   # Windows
rm .brain_session.json    # Linux/macOS
# 下次请求时自动重新登录
```

---

### 6.3 LLM 相关

**Q: 文献提炼失败，无法连接 LLM**

检查 `configs/llm_config.json` 中的 API key 和模型名称配置是否正确。

**Q: LLM 生成的假说包含废弃字段（`close`、`open`）**

系统在 AST 编译阶段**自动拦截**，无需手动干预。Dry-run 模式下可在日志中查看拦截详情。

---

### 6.4 测试与环境

**Q: 测试失败**

```bash
python -m pytest -v --tb=short   # 查看详细失败信息
python alpha_machine.py init-db --reset  # 重新初始化测试数据库
```

**Q: 如何在无网络环境运行？**

不带 `--execute` 的所有命令均完全离线运行（使用内置 `PlatformSimulator`）：

```bash
# 完全离线的 Dry-run 测试
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal
```

---

## 附录：文档导航

| 文档 | 定位 |
|:---|:---|
| [README.md](README.md) | 项目概览与 10 阶段架构总览 |
| [QUICKSTART.md](QUICKSTART.md) | 5 分钟极速入门 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | DDD + 事件溯源 + 防过拟合架构设计 |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | 24 张核心数据表/视图 + 5 张运行时表设计规范 |
| [docs/INDEX.md](docs/INDEX.md) | 文档全景导航索引 |
| [docs/guides/autonomous_evolution_guide.md](docs/guides/autonomous_evolution_guide.md) | 全自主进化与符号杂交实战指南 |
| [docs/guides/production_deployment_guide.md](docs/guides/production_deployment_guide.md) | 生产环境部署与运维手册 |
