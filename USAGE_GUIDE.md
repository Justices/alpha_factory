# Alpha Operator Framework 使用指南

> 本指南帮助你手动执行 alpha 挖掘全流程: 数据集筛选 → 字段探索 → 回测 → 评价 → 提交预检

## 目录

1. [环境准备](#1-环境准备)
2. [一键运行](#2-一键运行)
3. [核心流程](#3-核心流程)
4. [模块详解](#4-模块详解)
5. [CLI 命令速查](#5-cli-命令速查)
6. [数据库表结构](#6-数据库表结构)
7. [典型工作流](#7-典型工作流)

---

## 1. 环境准备

### 1.1 Python 环境

```bash
# 回测和平台访问使用已安装 cnhkmcp、mcp、pydantic、pandas 的当前 Python 环境
export PY=python

# 离线计算 (剪枝/评价) 可用系统 python3
export PY3=python3
```

### 1.2 认证配置

项目根目录有 `.brain.json` (账号凭据) 和 `.brain_session.json` (会话缓存)。

首次运行会自动登录，会话缓存到本地，后续免登录。

### 1.3 数据包

```
runs/WebData_20260219_V0.10.9.zip  (35MB, 90万+ 已提交 alpha 统计)
data/alpha_research.db              (SQLite 回测状态数据库)
```

### 1.4 项目数据目录

```text
data/fields/<region>/<delay>/<universe>/  # 平台导出的字段 CSV / JSON；默认优先读取
data/imports/    # 外部 Alpha / 回测结果 CSV
runs/            # 自动生成的任务、结果、密度报告和数据库
```

默认 `--field-source auto` 按 `region`、`delay`、`universe`、`dataset` 直接定位
`data/fields/<region>/<delay>/<universe>/<dataset>.json`，找不到时尝试 CSV；未传
`dataset` 时才合并范围内的所有本地字段文件。不存在或无匹配字段时才请求平台。可传
`--field-source local` 强制本地或 `--field-source platform` 强制平台。显式文件必须标明格式：

```bash
$PY -m alpha_operator_framework.orchestrator survey \
  --field-source local --region GBR --universe TOP700 --delay 1 --dataset risk68
```

---

## 2. 一键运行

### 2.1 完整流程 (消耗额度)

```bash
$PY -m alpha_operator_framework.orchestrator run-all \
    --region USA \
    --universe TOP3000 \
    --survey-sample 80 \
    --deepen-sample 400 \
    --sharpe 1.58 \
    --fitness 1.0 \
    --margin 0.0005 \
    --prune-fields 3 \
    --prune-per-field 2 \
    --local-sc \
    --prune-corr \
    --execute
```

### 2.2 仅本地预检 (不消耗额度)

```bash
# 本地流程: Survey + Deepen (dry-run) + Submit (本地预检)
python3 -m alpha_operator_framework.orchestrator run-all \
    --region USA \
    --universe TOP3000 \
    --prune-fields 3 \
    --local-sc \
    --prune-corr
```

### 2.3 参数说明

| 参数 | 默认值 | 作用 |
|---|---|---|
| `--region` | EUR | 区域 |
| `--universe` | TOP2500 | 股票池 |
| `--survey-sample` | 80 | Survey 阶段字段池样本数 |
| `--deepen-sample` | 400 | Deepen 阶段字段池上限 |
| `--sharpe` | 1.58 | Sharpe 阈值 |
| `--fitness` | 1.0 | Fitness 阈值 |
| `--margin` | 0.0005 | Margin 阈值 (5bp) |
| `--prune-fields` | 0 | 语义剪枝: 每类保留 N 个字段 |
| `--prune-per-field` | 0 | 同字段 top-k: 每字段保留 N 个 alpha |
| `--local-sc` | 关 | 本地 SC 预检 |
| `--prune-corr` | 关 | 相关性剪枝 |
| `--page-delay` | 0.5 | 翻页请求间隔 (秒) |
| `--execute` | 关 | 实际消耗额度 |

### 2.4 使用数据包预筛 (推荐)

在拉取平台字段前，先用本地数据包做零成本预筛，只选择高质量数据集：

```bash
# 使用数据包预筛，只保留甜点区数据集
$PY -m alpha_operator_framework.orchestrator run-all \
    --region USA \
    --universe TOP3000 \
    --use-datapack runs/WebData_20260219_V0.10.9.zip \
    --datapack-dataset-mode sweet_spot \
    --datapack-dataset-top 10 \
    --local-sc \
    --execute
```

**参数说明:**

| 参数 | 默认值 | 作用 |
|---|---|---|
| `--use-datapack` | 关 | 数据包路径，启用本地预筛 |
| `--datapack-dataset-mode` | sweet_spot | 筛选模式 |
| `--datapack-dataset-top` | 10 | 数据集数量上限 |

**筛选模式:**

| 模式 | 含义 |
|---|---|
| `sweet_spot` | 甜点区: 100-3000提交且sharpe≥1.1×均值 (推荐) |
| `top_n` | 提交数最多的N个 |
| `all` | 全部数据集 |

**优势:**
- 减少平台 API 调用 (避免 429)
- 提高命中率 (选择已验证可提交的数据集)
- 降低 ProdCorr 死区风险

### 2.5 避免 429 限流

平台对 `data-fields` 接口有速率限制，连续翻页过快会触发 429 错误。

**解决方案:**

```bash
# 增加翻页间隔 (默认 0.5s，可调到 1-2s)
$PY -m alpha_operator_framework.orchestrator run-all \
    --page-delay 1.0 \
    ...

# 或使用 --dataset 缩小字段范围，减少翻页次数
$PY -m alpha_operator_framework.orchestrator run-all \
    --dataset model38 \
    ...
```

**建议:**
- 首次运行用较小 `--survey-sample` (如 50) 测试
- 用 `--dataset` 指定单个数据集，减少字段总数
- 遇到 429 后等待 1-2 分钟再重试

---

## 3. 核心流程

```
┌─────────────────────────────────────────────────────────────────┐
│  Phase 0: 数据集/字段预筛 (本地, 零成本)                          │
│  ├─ webdata_quality.py → 数据集甜点区排名                        │
│  └─ evaluation.py → DatasetQuality 评级                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Phase 1: Survey (调研)                                          │
│  ├─ 发现字段 (fetch_datafields)                                   │
│  ├─ 语义剪枝 (--prune-fields, 压缩字段池)                         │
│  ├─ 构造任务 (模板族 × 字段)                                       │
│  ├─ 模拟回测 (--execute 消耗额度)                                 │
│  └─ 计算密度 → top-N 模板                                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Phase 2: Deepen (深挖)                                          │
│  ├─ 读取 density 报告                                             │
│  ├─ top-N 模板 × 全字段                                           │
│  ├─ 质量门筛选 (sharpe/fitness/margin/turnover)                   │
│  ├─ 同字段 top-k 剪枝 (--prune-per-field, 防垄断)                 │
│  └─ 输出 kept.json                                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Phase 3: Submit (提交预检)                                       │
│  ├─ 本地 SC 预检 (--local-sc, 减少平台调用)                       │
│  │   ├─ sc >= 0.7 → 绿色 (不可提交, 跳过 check)                   │
│  │   ├─ sc >= 0.65 → 黄色 (边缘)                                  │
│  │   └─ sc < 0.65 → 蓝色 (可提交)                                 │
│  ├─ 相关性剪枝 (--prune-corr, PnL 去重)                          │
│  ├─ Failed Gate 计数 (RA/PPA)                                     │
│  └─ 平台 Check (--execute 触发)                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 模块详解

### 3.1 pruning.py — 三阶段剪枝

| 函数 | 阶段 | 作用 | 网络访问 |
|---|---|---|---|
| `semantic_prune_fields` | Survey 前 | 字段池按语义类别压缩 (每类留 N 个代表) | 否 |
| `field_topk_prune` | Deepen 后 | 同字段只留 sharpe 最高的 N 个 | 否 |
| `correlation_prune` | Submit 前 | 按 PnL 日差分贪心去重 | 是 (只读) |
| `local_sc_precheck` | Submit 前 | 本地计算 SC, 分级筛选 | 是 (只读) |

**配置参数:**

```python
SemanticPruneConfig(
    keep_per_category=3,    # 每类保留数
    prefer_cold=True,       # 冷门优先 (userCount 小的先留)
)

FieldTopKConfig(
    keep_per_field=3,       # 每字段保留数
    split_by_sign=True,     # 正负 sharpe 分开计数
)

CorrelationPruneConfig(
    threshold=0.7,          # 相关性阈值
    min_periods=100,        # 最小重叠期
)

LocalCheckConfig(
    sc_threshold=0.7,       # SC 阈值
    sc_marginal=0.05,       # 边缘带宽度
)
```

### 3.2 evaluation.py — Alpha 评价

#### Failed Gate 计数

```python
from alpha_operator_framework import count_failed_gates

# 从 is.checks 计算失败数
result = count_failed_gates(checks)

result.failed_ra       # Failed RA 计数 (REGULAR alpha 需要 = 0)
result.failed_ppa      # Failed PPA 计数 (PPA alpha 需要 = 0)
result.qualifies_regular  # True = REGULAR 合格
result.failed_ra_items    # 失败项详情
```

**RA 清单 (17项):**
```
HIGH_TURNOVER, LOW_TURNOVER, LOW_FITNESS, LOW_RETURNS, LOW_SHARPE,
LOW_GLB_AMER_SHARPE, LOW_GLB_APAC_SHARPE, LOW_GLB_EMEA_SHARPE,
LOW_ASI_JPN_SHARPE, IS_LADDER_SHARPE, LOW_2Y_SHARPE,
LOW_SUB_UNIVERSE_SHARPE, LOW_ROBUST_UNIVERSE_SHARPE,
LOW_AFTER_COST_ILLIQUID_UNIVERSE_SHARPE, LOW_INVESTABILITY_CONSTRAINED_SHARPE,
LOW_ROBUST_UNIVERSE_RETURNS, CONCENTRATED_WEIGHT
```

#### Alpha 综合评价

```python
from alpha_operator_framework import evaluate_alpha

eval_result = evaluate_alpha(
    alpha_id="abc123",
    is_result={"sharpe": 1.8, "fitness": 1.2, "checks": [...]},
    expression="rank(close)",
)

eval_result.grade              # "submission_ready" / "needs_optimization" / "failed"
eval_result.grade_reason       # 评级原因
eval_result.optimization_hints # 优化建议列表
eval_result.can_submit         # True = 可提交
```

#### 数据集质量预筛

```python
from alpha_operator_framework import evaluate_dataset_quality

ds_quality = evaluate_dataset_quality(
    dataset_id="other566",
    alpha_count=791,
    avg_sharpe=0.799,
    region_mean_sharpe=0.358,
)

ds_quality.grade          # "sweet_spot" / "saturated" / "unverified" / "low_quality"
ds_quality.recommendation # 推荐动作
```

**数据集评级规则:**

| 评级 | 条件 | 推荐 |
|---|---|---|
| sweet_spot | 100≤count≤3000 且 sharpe≥1.1×均值 | 优先入围 |
| saturated | count > 30000 | 需非对称结构, 冷启动避开 |
| unverified | count < 50 | 默认跳过 |
| low_quality | sharpe 明显低于均值 | 跳过 (社区踩坑) |

### 3.3 database.py — 数据持久化

**表结构:**

| 表名 | 作用 |
|---|---|
| alpha_expressions | 表达式去重存储 |
| backtest_results | 回测结果 + 状态跟踪 |
| alpha_details | Alpha 详情 (指标 + PC/SC) |
| alpha_checks | 检查子表 (平台全部 check 项) |
| alpha_optimization_queue | 待优化 alpha (失败因子 + 阈值) |
| alpha_submission_candidates | 可提交 alpha (性能详情 + 状态) |

**常用操作:**

```python
from alpha_operator_framework import AlphaDatabase

db = AlphaDatabase("data/alpha_research.db")

# 保存回测结果
db.save_result_with_checks(alpha_id, is_result, settings)

# 查询
alphas = db.query_alphas(min_sharpe=1.5, min_fitness=1.0)

# 获取 checks
checks = db.get_checks(alpha_id)

db.close()
```

---

## 4. CLI 命令速查

### 4.1 Survey (调研)

```bash
# Dry-run (不消耗额度)
python3 -m alpha_operator_framework.orchestrator survey \
    --region USA --universe TOP3000 \
    --sample 80 \
    --prune-fields 3

# 实际回测 (消耗额度)
$PY -m alpha_operator_framework.orchestrator survey \
    --region USA --universe TOP3000 \
    --sample 80 \
    --prune-fields 3 \
    --batch-size 8 \
    --execute
```

**参数说明:**

| 参数 | 默认值 | 作用 |
|---|---|---|
| `--prune-fields` | 0 (关) | 语义剪枝: 每类保留 N 个字段代表 |
| `--sample` | 80 | 字段池样本数 |
| `--batch-size` | 8 | 多模拟并发数 |
| `--top-n` | 3 | 输出 top-N 模板 |

### 4.2 Deepen (深挖)

```bash
# Dry-run
python3 -m alpha_operator_framework.orchestrator deepen \
    --density-out runs/survey_density.json \
    --sample 400 \
    --sharpe 1.58 --fitness 1.0 --margin 0.0005 \
    --prune-fields 3 \
    --prune-per-field 2

# 实际回测
$PY -m alpha_operator_framework.orchestrator deepen \
    --density-out runs/survey_density.json \
    --sample 400 \
    --sharpe 1.58 --fitness 1.0 --margin 0.0005 \
    --prune-fields 3 \
    --prune-per-field 2 \
    --execute
```

**质量门参数:**

| 参数 | 默认值 | 作用 |
|---|---|---|
| `--sharpe` | 1.2 | Sharpe 下限 |
| `--fitness` | 0.7 | Fitness 下限 |
| `--margin` | 5.0 | Margin 下限 (bp) |
| `--prune-per-field` | 0 | 同字段 top-k 剪枝 |

### 4.3 Submit (提交预检)

```bash
# 仅本地预检 (不触发平台 check)
python3 -m alpha_operator_framework.orchestrator submit \
    --kept-out runs/deepen_kept.json \
    --local-sc \
    --sc-threshold 0.7 \
    --sc-marginal 0.05 \
    --prune-corr

# 触发平台 check (消耗额度)
$PY -m alpha_operator_framework.orchestrator submit \
    --kept-out runs/deepen_kept.json \
    --local-sc \
    --prune-corr \
    --execute
```

**提交预检参数:**

| 参数 | 默认值 | 作用 |
|---|---|---|
| `--local-sc` | 关 | 本地 SC 预检, 分级减少平台调用 |
| `--sc-threshold` | 0.7 | SC 阈值 (≥ 此值标记绿色跳过) |
| `--sc-marginal` | 0.05 | SC 边缘带 (阈值±边缘带 = 黄色) |
| `--prune-corr` | 关 | 相关性剪枝 (PnL 去重) |

### 4.4 数据包分析

```bash
# 查看数据集质量排名
$PY tools/webdata_quality.py --top 30

# 导出 JSON
$PY tools/webdata_quality.py --json-out runs/dataset_quality.json
```

---

## 5. 数据库表结构

### 5.1 alpha_optimization_queue (待优化)

```sql
CREATE TABLE alpha_optimization_queue (
    alpha_id TEXT NOT NULL,
    expression TEXT,
    sharpe, fitness, turnover, margin,    -- 性能快照
    failed_checks TEXT,                     -- JSON: 失败检查项详情
    failed_ra_count INTEGER,                -- Failed RA 计数
    failed_ppa_count INTEGER,               -- Failed PPA 计数
    optimization_hints TEXT,                -- JSON: 优化建议
    status TEXT DEFAULT 'pending',          -- pending/optimizing/resolved/abandoned
    priority INTEGER DEFAULT 0
);
```

### 5.2 alpha_submission_candidates (可提交)

```sql
CREATE TABLE alpha_submission_candidates (
    alpha_id TEXT NOT NULL UNIQUE,
    expression TEXT,
    sharpe, fitness, turnover, margin,
    sc_value, pc_value,
    local_sc, local_sc_grade,               -- 本地预检结果
    robustness_status TEXT,                  -- pending/pass/fail
    needs_optimization INTEGER DEFAULT 0,
    is_submitted INTEGER DEFAULT 0,
    submitted_at TEXT,
    pyramid_category TEXT,
    pyramid_multiplier REAL
);
```

---

## 6. 典型工作流

### 6.1 新区域探索

```bash
# 1. 查看数据集甜点区
$PY tools/webdata_quality.py --region EUR --delay 1 --top 20

# 2. Survey
$PY -m alpha_operator_framework.orchestrator survey \
    --region EUR --universe TOP1200 \
    --sample 100 --prune-fields 3 \
    --execute

# 3. Deepen
$PY -m alpha_operator_framework.orchestrator deepen \
    --density-out runs/survey_density.json \
    --sample 500 --prune-per-field 2 \
    --sharpe 1.58 --execute

# 4. Submit 预检
$PY -m alpha_operator_framework.orchestrator submit \
    --kept-out runs/deepen_kept.json \
    --local-sc --prune-corr
```

### 6.2 增量优化

```bash
# 1. 查看待优化 alpha
sqlite3 data/alpha_research.db "
SELECT alpha_id, expression, failed_ra_count, optimization_hints 
FROM alpha_optimization_queue 
WHERE status='pending' 
ORDER BY priority DESC LIMIT 10"

# 2. 根据优化建议修复表达式
# 3. 重新提交预检
```

### 6.3 本地 SC 预检查看

```bash
# 查看分级结果
cat runs/submit_sc_green.json   # 不可提交 (SC >= 0.7)
cat runs/submit_sc_yellow.json  # 边缘 (0.65 <= SC < 0.7)
cat runs/submit_sc_blue.json    # 可提交 (SC < 0.65) -- 实际没有单独文件
```

---

## 附录: 阈值速查表

| 指标 | 阈值 | 说明 |
|---|---|---|
| Sharpe | ≥ 1.58 | 全期夏普 |
| Fitness | ≥ 1.0 | 适应度 |
| Turnover | 5% - 30% | 换手率范围 |
| Margin | ≥ 5bp | 边际收益 |
| SC (Self-Corr) | < 0.7 | 自相关阈值 |
| PC (Prod-Corr) | < 0.7 | 生产相关阈值 |
| Failed RA | = 0 | REGULAR alpha 硬门槛 |
| Failed PPA | = 0 | PPA alpha 硬门槛 |

---

## 附录: 文件输出

| 文件 | 阶段 | 内容 |
|---|---|---|
| `survey_tasks.json` | Survey | 任务列表 |
| `survey_results.json` | Survey | 回测结果 |
| `survey_density.json` | Survey | 密度报告 |
| `deepen_tasks.json` | Deepen | 任务列表 |
| `deepen_kept.json` | Deepen | 质量门通过 |
| `deepen_pruned_topk.json` | Deepen | top-k 剪掉 |
| `submit_sc_green.json` | Submit | 本地 SC 不可提交 |
| `submit_sc_yellow.json` | Submit | 本地 SC 边缘 |
| `submit_pruned_corr.json` | Submit | 相关性剪掉 |
