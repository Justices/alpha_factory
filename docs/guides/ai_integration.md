# AI 工作流与自动化集成指南 (AI Integration Guide)

> **定位**: 面向 AI Agent、大语言模型与 Python 自动化脚本的结构化接口与调用规范。

---

## 一、 设计理念

本框架专门针对 AI Agent 与自动化脚本调用进行了深度优化：
1. **精确参数控制**: 支持 AI 精确指定区域、宇宙、数据集与字段列表；
2. **结构化结果返回**: 返回 Python 强类型数据类与字典对象，绝非易错的松散纯文本；
3. **Dry-Run 优先保障**: 默认不消耗任何平台回测配额，AI 可先生成并检查任务，确认安全后再授权 `--execute`；
4. **全闭环单用例调用**: 支持通过单一用例或 CLI 单行命令触发端到端投研流程。

---

## 二、 核心 API 与调用模式

### 1. DDD 投研生命周期 (`ResearchCycleUseCase`)

**适用场景**: AI Agent 自动化触发 10 阶段标准化投研周期：

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

# 1. 组装用例
use_case = ResearchCycleUseCase(
    research_repo=SqliteResearchRepository(),
    experiment_repo=SqliteExperimentRepository(),
    knowledge_repo=SqliteKnowledgeRepository(),
    backtest_gateway=BrainBacktestGateway(execute=False),  # 默认 Dry-run 试运行
    submission_gateway=BrainSubmissionGateway(),
)

# 2. 发起请求
request = ResearchCycleRequest(
    region="GBR",
    universe="TOP700",
    algorithm="d_optimal",     # 可选: d_optimal, thompson, ucb, stratified, diversity
    sample_per_family=4,
    execute=False,             # 安全试运行
)

result = use_case.execute(request)
print(f"生成的候选数: {len(result.round.candidates)}")
```

### 2. 字段合规与安全包装

> [!IMPORTANT]
> **严禁使用 `close`, `open`, `high`, `low` 等已停用字段**。AI 构造特征规格时必须统一采用 `returns`, `vwap`, `volume`, `market_cap` 等标准字段。

```python
from alpha_operator_framework.domain.fields import FieldSpec

# 构造合规字段规格
field_specs = [
    FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", coverage=0.98),
    FieldSpec(id="vwap", dataset_id="pv1", type="MATRIX", coverage=0.95),
    FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.99),
]
```

### 3. 一键分层地毯式挖掘 API (`run_stratified_carpet_mining`)

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
    execute=False,  # 先进行 Dry-run 预览
)

# 打印生成的任务摘要
print(result.summary_markdown())
```

---

## 三、 CLI 命令行集成规范

AI Agent 在通过终端执行外部工具调用时，推荐使用如下标准命令：

```bash
# 1. 探索预览 (Dry-run, 零配额消耗)
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal --sample-per-family 4

# 2. 生产回测与遥测输出
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal --sample-per-family 4 \
    --execute --telemetry-file runs/telemetry.jsonl

# 3. 生产无人值守流水线
python alpha_machine.py auto-pilot \
    --region GBR --universe TOP700 \
    --datasets analyst7 --sample-per-family 4 --batch-size 5 \
    --execute
```