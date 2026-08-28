# Alpha Factory 快速入门指南 (Quickstart Guide)

欢迎使用 **Alpha Factory**。本指南帮助您在 5 分钟内完成环境就绪、数据库初始化、执行全套单测并启动首次因子挖掘。

---

## ⚡ 1. 环境准备与数据库初始化

### 环境要求
- Python 3.10+
- 依赖项安装：
  ```bash
  pip install -r requirements.txt
  ```

### 数据库初始化 (首次运行必做)
本框架执行**数据库零提交规范**（`.db` 文件不提交 Git），新环境需先在本地初始化：
```bash
# 全新初始化 SQLite 主库并注入 30+ 模板种子
python init_db.py

# 或使用框架统一 CLI
python alpha_machine.py init-db
```

### 校验与全套单测 (465 项测试)
```bash
# 验证数据库完整性与表结构版本
python init_db.py --verify

# 运行全套 465 项自动化测试 (100% 通过, 0 警告)
python -m pytest -q

# 运行小批崩溃恢复与治理闭环演练 (生产前推荐)
python alpha_machine.py drill-recovery
```

---

## 🚀 2. 核心 CLI 命令备忘清单

### 2.0 全新 DDD 投研生命周期 (`research-cycle`) 🌟
严格遵循领域驱动设计 4 大限界上下文与 10 阶段流水线。默认仅生成可审计的回测计划（Dry-run 试运行），不会创建或调用 BRAIN 客户端；`--execute` 才授权真实回测：
```bash
# 1. 使用 D-Optimal 最大特征空间覆盖算法进行探索 (默认 Dry-run 试运行)
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal --sample-per-family 4

# 2. 使用 Thompson / UCB 贝叶斯多臂老虎机自适应探索
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm thompson --sample-per-family 4

# 3. 授权真实并发回测与遥测输出
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal --sample-per-family 4 \
    --execute --telemetry-file runs/telemetry.jsonl
```

### 2.1 全自动无人值守投研流水线 (`auto-pilot`) 🚀
一键串联：环境自检 ➔ 真实并发回测 ➔ 6 维证据终审 ➔ 空间释放 (VACUUM) ➔ 汇总研报生成：
```bash
# Python 命令行一键全自动生产运行:
python alpha_machine.py auto-pilot \
    --region GBR --universe TOP700 \
    --datasets analyst7 \
    --sample-per-family 4 --batch-size 5 \
    --execute

# 或直接运行后台一键启动脚本 (自动保存日志):
# Linux / macOS / Git Bash:
bash run_autopilot.sh GBR TOP700 analyst7 4 5
# Windows PowerShell:
.\run_autopilot.ps1 -Region GBR -Universe TOP700 -Datasets "analyst7" -SamplePerFamily 4 -BatchSize 5
```

### 2.2 分层地毯式 Alpha 挖掘 (`mine`) 🌟
对指定市场与另类数据集进行多模板族分层均衡抽样，自动并行回测与流式落库：
```bash
# 对英国市场 TOP700 与 analyst7 数据集进行地毯式挖掘
python alpha_machine.py mine \
    --region GBR --universe TOP700 \
    --datasets "insider_agg_matrix,pattern_scores,fundamental31" \
    --sample-per-family 4 \
    --batch-size 5 \
    --decay 12 \
    --neutralization SUBINDUSTRY \
    --execute
```

### 2.3 文献认知提炼流水线 (`research`)
从学术研报或论文 PDF 中自动提取量化逻辑，对齐平台可用字段并执行真实回测与 AlphaJudge 终审：
```bash
# 试运行 (Dry-run, 不消耗平台回测额度)
python alpha_machine.py research \
    --paper docs/academic_paper.pdf \
    --region GBR --universe TOP700

# 启用大模型 (DeepSeek/OpenAI/Qwen) 正式执行并生成 Markdown 研报
python alpha_machine.py research \
    --paper docs/academic_paper.pdf \
    --region GBR --universe TOP700 \
    --use-llm --provider deepseek --model deepseek-chat \
    --execute --output data/paper_research_report.md
```

### 2.4 查看生产投研看板 (`status`)
```bash
python alpha_machine.py status
```

### 2.5 数据库维护与磁盘空间释放 (`clean-db`)
```bash
# 试运行预览待清理数据
python clean_db.py --mode stale --dry-run

# 正式清理失败/剪枝记录并释放空间 (VACUUM)
python clean_db.py --mode stale
```

### 2.6 投研任务恢复与断点续传 (`research-worker`)
```bash
python alpha_machine.py research-worker --round-id <ROUND_ID>
```

### 2.7 达标因子上线外箱派发 (`submission-dispatch`)
```bash
python alpha_machine.py submission-dispatch --limit 50
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
- [权威用户操作手册](file:///d:/quant/alpha_factory/USAGE_GUIDE.md)
- [全自主进化与高阶挖掘实战指南](file:///d:/quant/alpha_factory/docs/guides/autonomous_evolution_guide.md)
- [数据库 24+5 表/视图设计规范](file:///d:/quant/alpha_factory/DATABASE_DESIGN.md)
- [文档全景导航索引](file:///d:/quant/alpha_factory/docs/INDEX.md)
