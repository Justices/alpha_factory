# 快速入门指南

## 安装与配置

### 1. 环境要求
- Python 3.8+
- 依赖项见 `requirements.txt`

### 2. 安装依赖
```bash
pip install -r requirements.txt  # (如有)
```

### 3. 配置平台访问
本框架依赖 `alpha_machine` 和 `brain_client` 进行平台交互。使用前需配置:

```python
# 在 ~/.brain_credentials 或环境变量中配置
BRAIN_EMAIL=your_email@example.com
BRAIN_PASSWORD=your_password
```

## 5分钟快速开始

### 方式1: 运行演示(推荐)
```bash
# 无需配置,直接运行
python3 examples/demo_workflow.py
```

**演示内容**:
- 模板族概览(一元/二元/三元)
- 算子库展示
- 字段处理流程
- 因子密度计算
- Top-N模板筛选

### 方式2: 运行测试
```bash
# 验证框架功能
python3 tests/test_framework.py
```

### 方式3: Python API
```python
from alpha_operator_framework import (
    unary_factory,
    FieldSpec,
    sample_scalar_expressions,
    compute_density,
)

# 1. 构造字段
fields = [
    FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.95)
]

# 2. 采样
scalars = sample_scalar_expressions(fields, SampleSpec(sample_n=10))

# 3. 生成任务
tasks = unary_factory(scalars)

# 4. 查看
print(f"生成{len(tasks)}个任务")
for t in tasks[:3]:
    print(f"  {t.expression}")
```

## 完整工作流示例

### Survey阶段: 调研市场
```bash
# Dry-run (不消耗额度)
python3 -m alpha_operator_framework.orchestrator survey \
  --region EUR --universe TOP2500

# 实际执行 (消耗回测额度)
python3 -m alpha_operator_framework.orchestrator survey \
  --region EUR --universe TOP2500 \
  --sample 80 --execute
```

**输出**:
- `runs/survey_tasks.json`: 任务列表
- `runs/survey_results.json`: 模拟结果
- `runs/survey_density.json`: 密度报告(含top-N)

### Deepen阶段: 深挖模板
```bash
# 基于survey的density报告
python3 -m alpha_operator_framework.orchestrator deepen \
  --density-out runs/survey_density.json \
  --sample 400 --execute
```

**输出**:
- `runs/deepen_tasks.json`: 深挖任务
- `runs/deepen_results.json`: 深挖结果
- `runs/deepen_kept.json`: 质量门筛选后的候选

### Submit阶段: 列出候选
```bash
# Dry-run (仅列出)
python3 -m alpha_operator_framework.orchestrator submit \
  --kept-out runs/deepen_kept.json

# 实际执行 (触发check)
python3 -m alpha_operator_framework.orchestrator submit \
  --kept-out runs/deepen_kept.json --execute
```

## 参数说明

### 通用参数
```bash
--region REGION          # 地区代码 (EUR/USA/CHN等)
--universe UNIVERSE      # 股票池 (TOP2500/TOP3000等)
--delay DELAY            # 延迟 (0/1)
--dataset DATASET        # 数据集ID (可选,空=全字段)
--sample N               # 采样数量
--execute                # 实际执行 (默认dry-run)
```

### Survey专用
```bash
--unary                  # 包含一元模板 (默认True)
--binary                 # 包含二元模板 (默认True)
--ternary                # 包含三元模板 (默认False)
--top-n N                # 取top-N模板用于deepen (默认3)
```

### Deepen专用
```bash
--density-out PATH       # survey的密度报告路径
--sharpe MIN             # Sharpe阈值 (默认1.2)
--fitness MIN            # Fitness阈值 (默认0.7)
--margin MIN             # Margin阈值 (默认5.0)
```

## 常见问题

### Q1: 如何查看可用的模板?
```python
from alpha_operator_framework import UNARY_TEMPLATES, BINARY_TEMPLATES

for idx, template, rationale, _ in UNARY_TEMPLATES:
    print(f"[{idx}] {rationale}")
```

### Q2: 如何自定义采样?
```python
from alpha_operator_framework import FieldSpec, SampleSpec, sample_scalar_expressions

spec = SampleSpec(
    sample_n=100,           # 采样100个
    min_coverage=0.8,       # coverage ≥ 0.8
    prefer_cold=True,       # 冷门优先
    seed=42                 # 固定随机种子
)
scalars = sample_scalar_expressions(fields, spec)
```

### Q3: 如何调整质量门?
```python
from alpha_operator_framework import SignalGate

gate = SignalGate(
    abs_sharpe_min=1.0,     # 调低Sharpe要求
    abs_fitness_min=0.5,    # 调低Fitness要求
    abs_pnl_min=2_000_000,  # 调低PnL要求
)
```

### Q4: 如何使用四元模板?
```bash
python3 -m alpha_operator_framework.orchestrator survey \
  --quaternary --groups sector industry \
  --execute
```

## 下一步

1. **阅读项目文档**: `PROJECT_SUMMARY.md`
2. **理解设计理念**: `README.md`
3. **查看测试代码**: `tests/test_framework.py`
4. **运行完整工作流**: 配置alpha_machine后执行survey→deepen→submit

## 获取帮助

```bash
# 查看CLI帮助
python3 -m alpha_operator_framework.orchestrator --help

# 查看子命令帮助
python3 -m alpha_operator_framework.orchestrator survey --help
```