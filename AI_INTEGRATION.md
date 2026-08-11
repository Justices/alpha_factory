# AI工作流集成指南

## 设计理念

本框架专门优化以配合AI工作，提供：

1. **精确参数控制**: 支持AI指定区域、宇宙、数据集、字段列表
2. **结构化结果**: 返回Python对象而非文本，便于AI解析
3. **Dry-run优先**: 默认不消耗额度，AI可先查看任务再决策
4. **单次调用**: 一次API调用完成完整工作流

## 核心API

### 1. run_full_workflow - 完整三段工作流

**用途**: AI单次调用完成survey→deepen→submit

**参数**:
```python
async def run_full_workflow(
    region: str,                          # 地区代码 (EUR/USA/CHN等)
    universe: str,                        # 股票池 (TOP2500/TOP3000等)
    delay: int = 1,                       # 数据延迟 (0/1)
    dataset_id: str = "",                 # 数据集ID (空=全字段)
    field_ids: Optional[List[str]] = None,# 指定字段列表 (None=采样)
    field_specs: Optional[Sequence[...]] = None,  # 字段规格 (避免平台查询)
    sample_n: int = 80,                   # 采样数量
    top_n: int = 3,                       # Top-N模板
    min_sharpe: float = 1.2,              # Deepen阶段Sharpe阈值
    execute: bool = False                 # 是否执行模拟
) -> Dict[str, WorkflowResult]
```

**返回**: 
```python
{
    "survey": WorkflowResult(...),   # Survey阶段结果
    "deepen": WorkflowResult(...),   # Deepen阶段结果(可选)
    "submit": WorkflowResult(...)    # Submit阶段结果(可选)
}
```

**示例**:
```python
# AI指定精确参数
result = await run_full_workflow(
    region="EUR",
    universe="TOP2500",
    dataset_id="pv1",
    field_ids=["close", "volume", "returns"],  # 精确字段
    execute=False  # 先dry-run
)

# AI解析结果
survey = result["survey"]
if survey.success:
    print(f"生成{survey.tasks_generated}个任务")
    for t in survey.top_templates:
        print(f"  [{t['family']}/{t['template_index']}] density={t['density']}")
```

### 2. run_survey_with_fields - 使用指定字段列表

**用途**: 精确控制字段列表，不随机采样

**参数**:
```python
async def run_survey_with_fields(
    field_specs: Sequence[FieldSpec],    # 字段规格列表
    config: SurveyConfig,                # Survey配置
    output_dir: Path = Path("runs"),     # 输出目录
    execute: bool = False                # 是否执行模拟
) -> WorkflowResult
```

**示例**:
```python
# AI提供精确字段列表
field_specs = [
    FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.95),
    FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.92),
]

# AI精确配置
config = SurveyConfig(
    region="EUR",
    universe="TOP2500",
    delay=1,
    field_ids=["close", "volume"],  # 只用这2个字段
    include_unary=True,
    include_binary=True,
    include_ternary=False
)

result = await run_survey_with_fields(field_specs, config)
```

## AI工作流程

### 典型流程

```python
# 1. AI指定参数(可能来自用户请求)
region = "EUR"
universe = "TOP2500"
dataset_id = "pv1"
fields = ["close", "volume", "returns"]

# 2. AI调用API (dry-run)
result = await run_full_workflow(
    region=region,
    universe=universe,
    dataset_id=dataset_id,
    field_ids=fields,
    execute=False
)

# 3. AI解析结果并决策
if result["survey"].success:
    tasks_n = result["survey"].tasks_generated
    
    # AI根据任务数量决策
    if tasks_n < 100:
        # 任务较少,可以直接执行
        print(f"生成{tasks_n}个任务,建议执行")
        # result = await run_full_workflow(..., execute=True)
    else:
        # 任务较多,建议分批
        print(f"生成{tasks_n}个任务,建议分批执行")

# 4. AI继续处理后续阶段
if result.get("deepen"):
    candidates = result["deepen"].candidates
    print(f"找到{len(candidates)}个候选alpha")
```

### AI决策循环示例

```python
async def ai_decision_loop():
    """AI根据密度动态调整字段."""
    
    # 第一步: 快速调研(少量字段)
    result_1 = await run_full_workflow(
        region="EUR",
        universe="TOP2500",
        field_ids=["close", "volume"],
        execute=False
    )
    
    # AI检查密度
    density = result_1["survey"].top_templates[0]["density"]
    
    # AI决策
    if density < 0.1:
        # 密度太低,尝试其他字段
        print("AI决策: 密度较低,扩展字段列表")
        result_2 = await run_full_workflow(
            region="EUR",
            universe="TOP2500",
            field_ids=["close", "volume", "returns", "cap"],
            execute=False
        )
        # 继续决策...
    else:
        # 密度可接受,继续深挖
        print("AI决策: 密度可接受,可以深挖")
        # result = await run_full_workflow(..., execute=True)
```

## 参数说明

### SurveyConfig - Survey阶段配置

```python
@dataclass
class SurveyConfig:
    # 基础参数
    region: str = "EUR"                  # 地区代码
    universe: str = "TOP2500"            # 股票池
    delay: int = 1                       # 数据延迟
    dataset_id: str = ""                 # 数据集ID
    
    # 字段选择
    field_ids: Optional[List[str]] = None  # None=采样,否则使用指定字段
    sample_n: int = 80                   # 采样数量
    min_coverage: float = 0.0            # 最小覆盖率
    prefer_cold: bool = True             # 冷门字段优先
    seed: int = 42                       # 随机种子
    
    # 模板选择
    include_unary: bool = True           # 包含一元模板
    include_binary: bool = True          # 包含二元模板
    include_ternary: bool = False        # 包含三元模板
    include_quaternary: bool = False     # 包含四元模板
    group_fields: Optional[List[str]] = None  # GROUP字段列表
    
    # 模拟参数
    batch_size: int = 8                  # 批量大小
    neutralization: str = "SUBINDUSTRY"  # 中性化方法
    truncation: float = 0.08             # 截断值
    decay: float = 6.0                   # 衰减值
```

### WorkflowResult - 结构化结果

```python
@dataclass
class WorkflowResult:
    success: bool                        # 是否成功
    stage: str                           # 阶段名
    message: str                         # 消息
    
    # 任务信息
    tasks_generated: int = 0             # 生成的任务数
    tasks_file: Optional[Path] = None    # 任务文件路径
    
    # 模拟信息
    simulations_run: int = 0             # 运行的模拟数
    results_file: Optional[Path] = None  # 结果文件路径
    
    # 密度信息
    density_report: Optional[Dict] = None  # 密度报告
    top_templates: List[Dict] = field(...)  # Top模板列表
    
    # 候选信息
    candidates: List[Dict] = field(...)  # 候选alpha列表
    kept_file: Optional[Path] = None     # 候选文件路径
    
    # 元数据
    timestamp: str = ...                 # 时间戳
    config: Dict = ...                   # 配置快照
```

## 使用场景

### 场景1: 用户指定具体字段

```python
# 用户: "用close, volume, returns这3个字段做EUR市场的调研"

result = await run_full_workflow(
    region="EUR",
    universe="TOP2500",
    field_ids=["close", "volume", "returns"],
    execute=False
)

# AI回复用户
print(f"生成{result['survey'].tasks_generated}个任务")
print(f"预计需要消耗回测额度")
print(f"是否执行?")
```

### 场景2: 用户指定数据集

```python
# 用户: "对pv1数据集在EUR市场做调研"

# AI可以选择采样或获取全部字段
result = await run_full_workflow(
    region="EUR",
    universe="TOP2500",
    dataset_id="pv1",
    sample_n=80,  # 采样80个字段
    execute=False
)

# AI回复用户
print(f"从pv1数据集采样{result['survey'].config['sample_n']}个字段")
print(f"生成{result['survey'].tasks_generated}个任务")
```

### 场景3: 批量处理

```python
# 用户: "对比EUR和USA市场"

results = {}
for region in ["EUR", "USA"]:
    results[region] = await run_full_workflow(
        region=region,
        universe="TOP2500",
        field_ids=["close", "volume"],
        execute=False
    )

# AI回复用户
for region, result in results.items():
    tasks = result["survey"].tasks_generated
    print(f"{region}: {tasks}个任务")
```

### 场景4: AI主动探索

```python
# AI主动探索不同参数组合

best_density = 0
best_config = None

for dataset in ["pv1", "pv13", "nws82"]:
    result = await run_full_workflow(
        region="EUR",
        dataset_id=dataset,
        sample_n=80,
        execute=False
    )
    
    if result["survey"].top_templates:
        density = result["survey"].top_templates[0]["density"]
        if density > best_density:
            best_density = density
            best_config = result["survey"].config

# AI报告最佳配置
print(f"最佳数据集: {best_config['dataset_id']}, 密度={best_density:.2f}")
```

## CLI兼容

保留CLI接口以支持命令行调用:

```bash
# CLI方式(向后兼容)
python3 -m alpha_operator_framework.ai_workflow \
    --region EUR \
    --universe TOP2500 \
    --dataset pv1 \
    --fields close volume returns \
    --execute
```

## 最佳实践

### 1. Dry-run优先

```python
# 先dry-run查看任务
result = await run_full_workflow(..., execute=False)

# AI检查任务数量
if result["survey"].tasks_generated < 100:
    # 任务合理,再执行
    result = await run_full_workflow(..., execute=True)
```

### 2. 提供field_specs

```python
# 避免平台查询(更快)
field_specs = [
    FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.95),
    ...
]

result = await run_full_workflow(
    ...,
    field_specs=field_specs  # 提供字段规格
)
```

### 3. 解析结构化结果

```python
# AI直接访问Python对象
result = await run_full_workflow(...)

if result["survey"].success:
    # 访问top模板
    for t in result["survey"].top_templates:
        family = t["family"]
        index = t["template_index"]
        density = t["density"]
        
        # AI做决策...
```

## 故障排除

### Q: 如何知道需要哪些字段?

A: AI可以:
1. 从用户输入提取字段名
2. 从平台查询数据集字段列表
3. 从历史数据学习常用字段

### Q: 如何处理大量任务?

A: AI可以:
1. 先dry-run查看任务数
2. 如果>100,建议分批或降低模板数量
3. 使用include_unary=False等参数控制

### Q: 如何解释密度给用户?

A: AI可以这样解释:
- "密度0.15表示15%的表达式通过了质量门"
- "密度越高,该模板对当前数据集越有效"
- "通常密度>0.1就可以继续深挖"

## 总结

本框架专为AI集成设计:
- ✅ 精确参数控制(区域/宇宙/数据集/字段)
- ✅ 结构化结果(便于解析)
- ✅ Dry-run优先(不消耗额度)
- ✅ 单次调用完整工作流
- ✅ 支持AI决策循环
- ✅ 批量处理能力