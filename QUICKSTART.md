# Alpha Factory 快速入门指南 (Quickstart Guide)

欢迎使用 **Alpha Factory**。本指南帮助您在 5 分钟内完成环境就绪、数据库初始化、执行单测并启动首次因子挖掘。

---

## ⚡ 1. 环境准备与数据库初始化

### 环境要求
- Python 3.10+
- 依赖项安装：
  ```bash
  pip install -r requirements.txt
  ```

### 数据库初始化 (首次运行必做)
本框架执行**数据库零提交规范**（`.db` 文件不提交 Git），新环境需先初始化：
```bash
# 全新初始化 SQLite 主库并注入 30+ 模板种子
python init_db.py

# 或使用框架统一 CLI
python alpha_machine.py init-db
```

### 校验与全套单测
```bash
# 验证数据库完整性
python init_db.py --verify

# 运行全套 180 项测试
python -m pytest

# 运行小批崩溃恢复与治理闭环演练 (生产前推荐)
python alpha_machine.py drill-recovery
```

---

## 🚀 2. 核心 CLI 命令备忘清单

### 2.0 全自动无人值守投研流水线 (`auto-pilot`) 🌟
一键串联：环境自检 ➔ 真实并发回测 ➔ 6 维证据终审 ➔ 空间释放 (VACUUM) ➔ 汇总研报生成：
```bash
# 云端/后台一键全自动生产运行 (推荐)
python alpha_machine.py auto-pilot \
    --region GBR --universe TOP700 \
    --datasets analyst7 \
    --sample-per-family 4 --batch-size 5 \
    --execute

# 或直接运行后台一键启动脚本 (自动保存日志):
bash run_autopilot.sh GBR TOP700 analyst7 4 5
```
从学术研报或论文 PDF 中自动提取量化逻辑，对齐平台字段并执行真实回测与终审：
```bash
# 试运行 (Dry-run, 不消耗平台回测额度)
python alpha_machine.py run-research \
    --paper-path docs/academic_paper.pdf \
    --region GBR --universe TOP700

# 正式执行并生成研报
python alpha_machine.py run-research \
    --paper-path docs/academic_paper.pdf \
    --region GBR --universe TOP700 \
    --execute --output data/paper_research_report.md
```

### 2.2 分层地毯式 Alpha 挖掘 (`carpet-mine`)
对指定市场与另类数据集进行多模板族分层均衡抽样，自动并行回测：
```bash
# 对英国市场 TOP700 与 analyst7 数据集进行地毯式挖掘
python alpha_machine.py carpet-mine \
    --region GBR --universe TOP700 \
    --dataset analyst7 \
    --sample-per-family 5 \
    --batch-size 10 \
    --execute
```

### 2.3 事件溯源 A/B 分支科学对照 (`compare-branches`)
严格在相同锁死时间分区与计算预算下，比较两套生成策略的 Locked-OOS 产出率：
```bash
python alpha_machine.py compare-branches \
    --branch-a exp_momentum_prior \
    --branch-b exp_reversion_prior
```

### 2.4 候选因子 6 维证据终审与提交审计 (`evaluate-candidates`)
```bash
python alpha_machine.py evaluate-candidates \
    --min-sharpe 1.25 --min-fitness 1.0 \
    --auto-promote
```

### 2.5 数据库维护与磁盘空间释放 (`clean-db`)
```bash
# 试运行预览待清理数据
python clean_db.py --failed --pruned --dry-run

# 正式清理失败/剪枝记录并释放空间 (VACUUM)
python clean_db.py --failed --pruned --vacuum
```

---

## 💻 3. Python API 极简调用示例

```python
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.generation import sample_scalar_expressions, SampleSpec
from alpha_operator_framework.generation.templates import unary_factory

# 1. 构造合规字段规格 (杜绝使用废弃的 close/open)
fields = [
    FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", coverage=0.98),
    FieldSpec(id="vwap", dataset_id="pv1", type="MATRIX", coverage=0.95),
    FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.99),
]

# 2. 字段采样
scalars = sample_scalar_expressions(fields, SampleSpec(sample_n=10))

# 3. 生成 AST 任务
tasks = unary_factory(scalars)
print(f"✅ 成功生成 {len(tasks)} 个一阶 Alpha 任务:")
for t in tasks[:3]:
    print(f"   • {t.expression}")
```

---

## 📖 更多详细文档

- [系统架构设计全景](file:///d:/quant/alpha_factory/ARCHITECTURE.md)
- [完整用户操作手册](file:///d:/quant/alpha_factory/USAGE_GUIDE.md)
- [数据库 17 表/视图设计规范](file:///d:/quant/alpha_factory/DATABASE_DESIGN.md)
- [文档全景导航索引](file:///d:/quant/alpha_factory/docs/INDEX.md)