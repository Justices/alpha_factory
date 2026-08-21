# 改进总结：AI友好的工作流API

## 改进背景

**原问题**: orchestrator.py是CLI设计，不适合AI直接调用：
- 参数通过命令行传递，AI调用不便
- 只支持随机采样，无法指定精确字段
- 结果是文本输出，AI难以解析

**新需求**: 配合AI工作，需要：
- 精确参数控制（区域/宇宙/数据集/字段列表）
- Python API接口
- 结构化结果
- Dry-run优先

## 核心改进

### 1. 新增ai_workflow.py模块

**设计理念**:
```python
# 旧方式(CLI)
$ python orchestrator.py survey --region EUR --sample 80

# 新方式(Python API)
result = await run_full_workflow(
    region="EUR",
    universe="TOP2500",
    dataset_id="pv1",
    field_ids=["close", "volume"],  # 精确字段
    execute=False
)
```

**关键特性**:
- ✅ Python API而非CLI
- ✅ 支持指定精确字段列表
- ✅ 返回结构化对象(WorkflowResult)
- ✅ 单次调用完成完整工作流

### 2. 精确参数控制

**新增参数**:
```python
# SurveyConfig
region: str = "EUR"                     # 地区代码
universe: str = "TOP2500"              # 股票池
delay: int = 1                         # 数据延迟
dataset_id: str = ""                   # 数据集ID
field_ids: Optional[List[str]] = None  # 指定字段列表(新增!)
```

**使用方式**:

**场景A**: 指定精确字段
```python
# 用户: "用close, volume, returns这3个字段"
result = await run_full_workflow(
    region="EUR",
    field_ids=["close", "volume", "returns"],
    execute=False
)
```

**场景B**: 指定数据集+采样
```python
# 用户: "对pv1数据集采样80个字段"
result = await run_full_workflow(
    region="EUR",
    dataset_id="pv1",
    sample_n=80,
    execute=False
)
```

**场景C**: 全字段
```python
# 用户: "EUR市场全字段调研"
result = await run_full_workflow(
    region="EUR",
    dataset_id="",  # 空=全字段
    sample_n=80,
    execute=False
)
```

### 3. 结构化结果

**WorkflowResult对象**:
```python
@dataclass
class WorkflowResult:
    success: bool                  # 是否成功
    stage: str                     # 阶段名
    message: str                   # 消息
    
    tasks_generated: int           # 生成的任务数
    tasks_file: Optional[Path]     # 任务文件路径
    
    simulations_run: int           # 运行的模拟数
    results_file: Optional[Path]   # 结果文件路径
    
    density_report: Optional[Dict] # 密度报告
    top_templates: List[Dict]      # Top模板列表
    
    candidates: List[Dict]         # 候选alpha列表
```

**AI解析示例**:
```python
result = await run_full_workflow(...)

# AI直接访问结构化字段
if result["survey"].success:
    tasks = result["survey"].tasks_generated
    top = result["survey"].top_templates[0]
    
    print(f"生成{tasks}个任务")
    print(f"Top模板密度={top['density']:.2f}")
```

### 4. AI决策循环

**示例: 根据密度调整字段**
```python
async def ai_decision_loop():
    # 第一步: 快速调研
    result_1 = await run_full_workflow(
        region="EUR",
        field_ids=["close", "volume"],
        execute=False
    )
    
    # AI检查密度
    density = result_1["survey"].top_templates[0]["density"]
    
    # AI决策
    if density < 0.1:
        # 密度太低,扩展字段
        print("AI: 密度较低,扩展字段列表")
        result_2 = await run_full_workflow(
            region="EUR",
            field_ids=["close", "volume", "returns", "cap"],
            execute=False
        )
    else:
        # 密度可接受,继续深挖
        print("AI: 密度可接受,可以深挖")
```

## 对比：旧 vs 新

| 特性 | 旧(orchestrator.py) | 新(ai_workflow.py) |
|------|---------------------|--------------------|
| **调用方式** | CLI命令行 | Python API |
| **字段选择** | 随机采样 | 精确指定或采样 |
| **参数传递** | 命令行参数 | 函数参数+配置对象 |
| **结果格式** | 文本输出 | 结构化对象 |
| **AI友好度** | 低(需解析文本) | 高(直接访问字段) |
| **单次调用** | 否(需多次命令) | 是(run_full_workflow) |
| **决策支持** | 无 | 有(density字段) |

## 使用示例

### 示例1: 用户指定字段

```python
# 用户: "用close, volume, returns做EUR调研"

result = await run_full_workflow(
    region="EUR",
    universe="TOP2500",
    field_ids=["close", "volume", "returns"],
    execute=False
)

# AI回复用户
print(f"生成{result['survey'].tasks_generated}个任务")
print(f"是否执行?")
```

### 示例2: 批量处理

```python
# 用户: "对比EUR, USA, CHN市场"

results = {}
for region in ["EUR", "USA", "CHN"]:
    results[region] = await run_full_workflow(
        region=region,
        field_ids=["close", "volume"],
        execute=False
    )

# AI回复用户
for region, result in results.items():
    tasks = result["survey"].tasks_generated
    print(f"{region}: {tasks}个任务")
```

### 示例3: AI主动探索

```python
# AI主动探索不同数据集

best_density = 0
best_dataset = ""

for dataset in ["pv1", "pv13", "nws82"]:
    result = await run_full_workflow(
        region="EUR",
        dataset_id=dataset,
        sample_n=80,
        execute=False
    )
    
    density = result["survey"].top_templates[0]["density"]
    if density > best_density:
        best_density = density
        best_dataset = dataset

# AI报告最佳配置
print(f"最佳数据集: {best_dataset}, 密度={best_density:.2f}")
```

## 实现细节

### 1. SurveyConfig配置类

```python
@dataclass
class SurveyConfig:
    # 基础参数
    region: str = "EUR"
    universe: str = "TOP2500"
    delay: int = 1
    dataset_id: str = ""
    
    # 字段选择(关键!)
    field_ids: Optional[List[str]] = None  # None=采样,否则精确指定
    
    # 采样参数(仅当field_ids=None时生效)
    sample_n: int = 80
    min_coverage: float = 0.0
    prefer_cold: bool = True
    seed: int = 42
    
    # 模板选择
    include_unary: bool = True
    include_binary: bool = True
    include_ternary: bool = False
    ...
```

### 2. run_survey_with_fields核心逻辑

```python
async def run_survey_with_fields(
    field_specs: Sequence[FieldSpec],
    config: SurveyConfig,
    execute: bool = False
) -> WorkflowResult:
    # 1. 字段选择
    if config.field_ids:
        # 精确指定
        selected = [f for f in field_specs if f.id in config.field_ids]
    else:
        # 采样
        selected = candidate_scalars(field_specs, SampleSpec(...))
    
    # 2. 构造任务
    tasks = []
    if config.include_unary:
        tasks.extend(unary_factory(scalars))
    ...
    
    # 3. (可选)模拟
    if execute:
        results = await alpha_machine.simulate(...)
        density_rows = compute_density(results)
        ...
    
    # 4. 返回结构化结果
    return WorkflowResult(
        success=True,
        tasks_generated=len(tasks),
        top_templates=[...],
        ...
    )
```

### 3. run_full_workflow完整流程

```python
async def run_full_workflow(...) -> Dict[str, WorkflowResult]:
    results = {}
    
    # Survey阶段
    results["survey"] = await run_survey_with_fields(...)
    
    # Deepen阶段(可选)
    if results["survey"].top_templates:
        results["deepen"] = await _run_deepen_from_survey(...)
    
    # Submit阶段(可选)
    if results.get("deepen") and results["deepen"].candidates:
        results["submit"] = WorkflowResult(
            candidates=results["deepen"].candidates
        )
    
    return results
```

## 测试与验证

### 运行示例

```bash
$ python3 examples/ai_workflow_examples.py

示例1: 使用精确字段列表
  成功: True
  消息: [DRY-RUN] 生成38个任务
  任务数: 38

示例2: 完整三段工作流
  SURVEY阶段:
    成功: True
    消息: [DRY-RUN] 生成28个任务

示例3: AI决策循环
  AI决策: 密度可接受

示例4: 批量处理多个地区
  EUR: 28个任务
  USA: 28个任务
  CHN: 28个任务

✓ 所有示例完成!
```

### API测试

```python
# 测试精确字段
result = await run_full_workflow(
    region="EUR",
    field_ids=["close", "volume"],
    execute=False
)
assert result["survey"].success
assert result["survey"].tasks_generated == 28

# 测试批量
results = {}
for region in ["EUR", "USA"]:
    results[region] = await run_full_workflow(region=region, ...)
assert len(results) == 2
```

## 文档

新增文档:
- `AI_INTEGRATION.md`: AI集成指南
- `examples/ai_workflow_examples.py`: 5个完整示例

更新文档:
- `__init__.py`: 导出新的API
- `README.md`: 更新快速开始章节

## 后续优化方向

1. **性能优化**:
   - 支持异步批量调用
   - 缓存field_specs避免重复查询

2. **功能扩展**:
   - 支持自定义模板注册
   - 支持更多质量门参数

3. **AI辅助**:
   - 自动推荐字段组合
   - 密度预测模型

4. **可视化**:
   - 结果dashboard
   - 参数对比图表

## 总结

本次改进核心:
- ✅ 新增ai_workflow.py模块
- ✅ 支持精确字段列表(field_ids参数)
- ✅ 结构化结果(WorkflowResult对象)
- ✅ 单次调用完整工作流(run_full_workflow)
- ✅ AI决策循环支持
- ✅ Dry-run优先设计

框架现已完全适配AI工作方式!