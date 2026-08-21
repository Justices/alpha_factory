# Alpha Factor Operator Framework

整合 `machine_lib.py` 多阶因子生成能力与 `cold_templates` 结构正交模板方法论，构建系统化的alpha因子研究框架。

**专为AI集成优化**: 支持精确参数控制、结构化结果、单次API调用完整工作流。

## 快速开始

### Python API (AI推荐方式)

```python
from alpha_operator_framework import run_full_workflow, FieldSpec

# AI指定精确参数: 区域/宇宙/数据集/字段列表
result = await run_full_workflow(
    region="EUR",
    universe="TOP2500",
    dataset_id="pv1",
    field_ids=["close", "volume", "returns"],  # 精确字段列表
    execute=False  # Dry-run先查看任务
)

# AI解析结构化结果
if result["survey"].success:
    print(f"生成{result['survey'].tasks_generated}个任务")
    for t in result["survey"].top_templates:
        print(f"  [{t['family']}/{t['template_index']}] density={t['density']:.2f}")
```

### 运行示例

```bash
# 演示工作流
python3 examples/demo_workflow.py

# AI工作流示例
python3 examples/ai_workflow_examples.py
```

### 使用本地字段文件预筛选

字段文件支持平台导出的 CSV，以及字段对象组成的 JSON 数组。提供本地文件后，
Survey 不会请求平台字段接口；会按 `region`、`universe`、`delay`、`dataset`、
`type` 和 `search` 过滤，再按 coverage 和冷门度进入后续预筛选。

```bash
python3 -m alpha_operator_framework.orchestrator survey \
  --fields-file data/fields/GBR/1/TOP700/risk68.csv --fields-file-type csv \
  --region GBR --universe TOP700 --delay 1 \
  --min-coverage 0.1 --sample 80 --backtest-sample 100
```

Python API：

```python
results = await run_full_workflow(
    region="GBR",
    universe="TOP700",
    delay=1,
    fields_file="data/fields/GBR/1/TOP700/risk68.json",
    execute=False,
)
```

### 语义二元配对

Survey 会在实际入选字段中自动识别同数据集的定向字段对，并将表达式与一阶
表达式一起登记、随机抽样回测：

- `earnings_positive` + `earnings_negative` → `positive - negative`
- `abc_revenue` + `abc_cap` → `abc_revenue / abc_cap`

`*_cap` 只会匹配同数据集、同前缀的字段，避免无关字段相除。需要关闭时传入
`--no-semantic-pairs`。

### Explicit binary base signals

Survey automatically discovers strict same-dataset revision (`raisednum`,
`lowerednum`, `num`) and dispersion (`high`, `low`, `mean`) groups. Group
members are excluded from standalone unary and first-order generation. Instead,
the combined economic base signal is expanded with the complete first-order
operator set (for example `rank(base)` and `ts_rank(base, 22)`). Repeatable
`--pair` parameters may add an explicit group. Tasks retain `paired_base` or
`paired_first_order` provenance, plus pair kind, stage, source, and source
fields.

```bash
python -m alpha_operator_framework.orchestrator survey \
  --field-source local --region GBR --universe TOP700 --delay 1 --dataset analyst7 \
  --pair net_revision:est_12m_ebi_raisednum_4wks:est_12m_ebi_lowerednum_4wks:est_12m_ebi_num \
  --backtest-sample 0
```

Use `ratio:NUMERATOR:DENOMINATOR` or
`difference|spread|net_revision:LEFT:RIGHT[:NORMALIZER]`.

## 核心特性

### 1. AI友好的API设计
- **精确参数控制**: 指定区域、宇宙、数据集、字段列表
- **结构化结果**: Python对象而非文本，便于解析
- **单次调用**: `run_full_workflow()` 完成survey→deepen→submit
- **Dry-run优先**: 默认不消耗额度，AI可先查看再决策

### 2. 整合创新
- **模板层扩展**: 新增四元模板，支持多阶group操作
- **算子层统一**: 统一管理basic_ops/ts_ops/group_ops
- **字段层增强**: 多阶预处理+精确指定
- **工作流标准化**: 三段方法论(survey→deepen→submit)

### 3. 灵活的字段选择

**方式1: 指定精确字段**
```python
result = await run_full_workflow(
    field_ids=["close", "volume", "returns"]
)
```

**方式2: 数据集+采样**
```python
result = await run_full_workflow(
    dataset_id="pv1",
    sample_n=80
)
```

**方式3: 全字段**
```python
result = await run_full_workflow(
    dataset_id="",  # 空=全字段
    sample_n=80
)
```

### 4. Alpha筛选与优化

支持两种筛选方式:

**方式A: 指定alpha_id**
```python
# 精确筛选
filtered = filter_alphas_for_optimization(
    alphas,
    alpha_ids=["alpha_001", "alpha_002", "alpha_003"]
)
```

**方式B: 按回测指标**
```python
# 高质量alpha: sharpe>1.58, fitness>1.0
high_quality = filter_high_quality_alphas(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    min_turnover=0.03
)

# 边缘alpha(有优化潜力): sharpe在1.2-1.8之间
marginal = filter_marginal_alphas(
    alphas,
    sharpe_range=(1.2, 1.8),
    limit=20
)

# 可提交的alpha
ready = filter_ready_for_submission(alphas)
```

### 5. Alpha AST 语法树引擎 (新增)

支持表达式语法解析、可交换算子重排、冗余嵌套消除与等价去重：

```python
from alpha_operator_framework import (
    parse_expression,
    to_canonical_string,
    get_canonical_sha,
    validate_expression,
)

# 1. 自动消除冗余嵌套与交换律规范化
expr1 = "volume + rank(rank(close))"
expr2 = "rank(close) + volume"

print(to_canonical_string(expr1))  # 输出: 'close + volume'
print(get_canonical_sha(expr1) == get_canonical_sha(expr2))  # True! 唯一哈希，杜绝重复回测

# 2. 静态语义与类型检查
res = validate_expression("group_neutralize(ts_rank(close, 22), industry)")
print(res.is_valid, res.fields_used)  # True, {'close', 'industry'}
```

### 6. 本地轻量向量化沙盒 (新增)

无需联网，在本地截面数据上毫秒级计算 Rank IC、Sharpe 与换手率，云端回测前预筛淘汰死因子，**节省 70%+ 云端配额**：

```python
from alpha_operator_framework import (
    SandboxEngine,
    evaluate_expression_local,
    sandbox_prefilter,
)

# 1. 单表达式快速本地回测评估
metrics = evaluate_expression_local("rank(close) / rank(volume)")
print(f"Local Rank IC: {metrics.rank_ic:.4f}, Sharpe: {metrics.sharpe:.2f}, Turnover: {metrics.turnover:.2f}")

# 2. 任务列表本地预筛剪枝
passed_tasks, rejected_tasks = sandbox_prefilter(tasks, min_abs_ic=0.01, min_sharpe=0.1)
print(f"保留 {len(passed_tasks)} 个有信号任务，淘汰 {len(rejected_tasks)} 个无效任务")
```

### 7. 统计防过拟合防御套件 (新增)

结合多重检验尝试总次数 (Trial Count)、收益偏度/峰度，校正数据挖掘偏差 (Data Snooping Bias)：

```python
from alpha_operator_framework import (
    compute_psr,
    compute_dsr,
    compute_haircut_sharpe,
    compute_pbo_cscv,
)

# 1. 折损夏普比率 (DSR): 在 2000 次试错背景下检验名义 Sharpe=1.40 是否显著
dsr = compute_dsr(sharpe=1.40, trial_count=2000, t_days=252)
print(f"DSR Confidence: {dsr:.4f}")  # < 0.95 说明属于多重检验过拟合假阳性

# 2. 组合对称交叉验证 (PBO/CSCV)
pbo = compute_pbo_cscv(returns_matrix, n_partitions=8)
print(f"PBO (Overfitting Probability): {pbo:.2%}")
```

### 8. 假说驱动因子推理引擎 (新增)

摒弃排列组合盲目穷举，从 5 大金融经济学假说出发生成具备强因果逻辑的 AST 因子：

```python
from alpha_operator_framework import HypothesisEngine, BUILTIN_HYPOTHESES

engine = HypothesisEngine()

# 1. 自动根据可用字段池匹配金融假说并生成高胜率 AST 任务
tasks = engine.generate_tasks_for_all_hypotheses(available_fields, max_tasks_per_hypothesis=5)

# 2. 生成供外部 LLM / AI Agent 推理的结构化 Prompt
prompt = engine.build_llm_prompt("USA", "TOP3000", available_fields)
```

### 9. 智能故障诊断与自动突变修复 (新增)

对回测未达标的 Alpha 进行精准病因归类并自动实施 AST 基因修复突变：

```python
from alpha_operator_framework import diagnose_alpha_failure, AlphaMutator, auto_repair_failed_alphas

# 1. 自动病因诊断 (如高换手 / 子宇宙崩溃 / 边缘夏普)
diagnosis = diagnose_alpha_failure({"alpha_id": "a001", "expression": "ts_delta(close, 2)", "turnover": 0.85})
print(diagnosis.primary_cause)  # FailureMode.HIGH_TURNOVER

# 2. 针对性基因修复 (自动注入 ts_decay_linear / 细分行业中性化 / 保号非线性压缩)
mutator = AlphaMutator()
repaired_exprs = mutator.mutate_expression("ts_delta(close, 2)", diagnosis.primary_cause)
print(repaired_exprs)  # ['ts_decay_linear(ts_delta(close, 2), 10)', ...]
```

### 10. 因子衰减半衰期探测器 (新增)

自适应拟合前向 IC 指数衰减曲线，精确推荐最佳 `decay` 平滑参数：

```python
from alpha_operator_framework import profile_alpha_decay

profile = profile_alpha_decay(signal_matrix, returns_matrix, max_lag=20)
print(f"半衰期: {profile.half_life} 天, 推荐 decay: {profile.recommended_decay}, 评级: {profile.decay_speed.value}")
```

### 11. 正交残差化与 Super-Alpha 2.0 风险平价组合 (新增)

向存量因子基底投影剥离共线性残差，并基于分层风险平价 (HRP) 算法合成多因子组合：

```python
from alpha_operator_framework import (
    gram_schmidt_residualize,
    build_super_alpha_2,
    PortfolioMethod,
)

# 1. 施密特正交残差化 (与存量基底相关性清零)
residual_matrix = gram_schmidt_residualize(candidate_matrix, [existing_alpha_1, existing_alpha_2])

# 2. 分层风险平价 (HRP) 组合公式合成
super_alpha = build_super_alpha_2(alpha_list, returns_matrix, method=PortfolioMethod.HRP)
print(f"Super-Alpha 2.0 表达式: {super_alpha.composite_expression}")
print(f"预期组合 Sharpe: {super_alpha.expected_sharpe}")
```

### 12. 跨市场/跨区域鲁棒性迁移套件 (新增)

跨 USA / EUR / CHN / JPN 多区域评估同一个 Alpha 的稳健性与一致性指数 (CMCI)：

```python
from alpha_operator_framework import evaluate_cross_market_robustness

report = evaluate_cross_market_robustness(
    "rank(close) / (rank(volume) + 0.01)",
    market_data_by_region={"USA": md_usa, "EUR": md_eur, "CHN": md_chn},
)
print(f"跨市场一致性指数 CMCI: {report.consistency_score:.2f}")
print(f"是否为全天候通用 Alpha: {report.is_universal}")
```

### 13. 文献研究与研报认知提炼引擎 (新增)

一键从学术论文 (SSRN/arXiv)、券商金工研报或量化社区帖子中抽取金融假说与数学公式，自动对齐真实字段并编译为 AST 因子：

```python
from alpha_operator_framework import (
    ingest_literature_to_alphas,
    parse_document,
    IdeaExtractor,
    DocumentType,
)

paper_text = """
# 海通证券：特质波动率与动量修正因子
核心观点：剥离特质波动率后，动量因子的反转预测力显著增强。
公式：rank(close) / (rank(volume) + 0.01)
"""

# 方式 1: 默认极速离线规则引擎 (无需 API Key，零成本毫秒级)
tasks_offline = ingest_literature_to_alphas(
    literature_text=paper_text,
    available_fields=available_fields,
    doc_type=DocumentType.RESEARCH_REPORT,
    run_sandbox_prefilter=True, # 自动过滤无信号公式
)

# 方式 2: 统一配置文件与多模型热切换 (读取 configs/llm_config.json 或环境变量)
tasks_llm = ingest_literature_to_alphas(
    literature_text=paper_text,
    available_fields=available_fields,
    use_llm=True,
    provider="deepseek",        # 自由指定 deepseek / openai / qwen / ollama
    model="deepseek-reasoner",  # 从该 Provider 绑定的 models 列表中选择模型
    run_sandbox_prefilter=True,
)

for t in tasks_llm:
    print(f"提取出 AST 公式: {t.expression}")
    print(f"文献来源: {t.meta['paper_title']}, 机理: {t.meta['rationale']}")
```

### 14. 终审评估与价值因子优先级决策引擎 (新增)

融合 20 篇高水平量化顾问实战语料与平台红线，在提交前执行实战红线审查（Extra Rubrics）、价值因子多样性推演（$\Delta \text{diversity}$）与提交优先级排序：

```python
from alpha_operator_framework import (
    AlphaJudge,
    JudgeVerdict,
    compute_value_factor_diversity,
)

# 1. 初始化裁判员 (传入存量提交历史)
judge = AlphaJudge(submitted_alphas=submitted_list)

# 2. 单个因子终审评估
report = judge.judge_candidate(candidate_alpha_detail)
print(f"终审结论: {report.verdict.value}")            # READY / REVIEW / BLOCK
print(f"提交优先级得分: {report.priority_score}")      # 综合打分 (越高越优先)
print(f"价值因子多样性增量: {report.projected_diversity_delta:.4f}")
print(f"落地改进建议: {report.actionable_recommendations}")

# 3. 候选池批量综合打分与排序
ranked_reports = judge.rank_candidates(candidate_pool)
for r in ranked_reports:
    print(f"[{r.verdict.value}] {r.alpha_id}: 优先级得分={r.priority_score:.1f}, 建议={r.actionable_recommendations[0]}")
```

### 15. 全自动端到端文献研发、真实平台回测与自动落库 (Autonomous Quant Pipeline)

一条函数或一条命令串联全流程：**PDF文献/Markdown解析 ➔ 动态真实字段池载入 ➔ 大模型假说提炼 ➔ AST公式规范编译 ➔ 双模回测(真实BRAIN平台在线回测/本地沙盒) ➔ DSR/PSR统计防过拟合检验 ➔ IC衰减半衰期探测 ➔ AlphaJudge终审评级 ➔ SQLite数据库自动持久化(落库) ➔ 导出研究报告**：

#### Python API 调用
```python
from alpha_operator_framework import run_literature_research_pipeline

result = run_literature_research_pipeline(
    literature_source=r"D:\quant\brain\reports\papers\pdfs\2605.09712v1_Quantifying_the_Risk-Return_Tradeoff_in_Forecasting.pdf",
    region="GBR",               # 目标市场 (自动适配 GBR 对应 TOP700)
    datasets=["analyst7", "risk68"], # ★ 动态加载指定真实数据集，绝不写死固定字段！
    neutralization="SUBINDUSTRY",
    delay=1,
    decay=8,
    execute_on_platform=True,   # ★ 直连 WorldQuant BRAIN 官方模拟集群真实回测！
    use_llm=True,               # 启用大模型 (自动读取 configs/llm_config.json)
    provider="deepseek",        # 支持自由切换 deepseek / openai / qwen / ollama
    save_to_db=True,            # ★ 自动落库：写入 alpha_expressions, alpha_details, alpha_checks
    database_path="data/alpha_research.db",
    output_report_path="gbr_research_report.md", # 自动导出精美 Markdown 总结报告
)

# 打印生成的终审研发报告
print(result.summary_markdown())

# 获取第一顺位推荐提交的 Alpha
top_alpha = result.top_submission_alpha
print(f"Top 1 提交因子: {top_alpha['alpha_id']}, 终审评级: {top_alpha['verdict']}, 优先级得分: {top_alpha['priority_score']}")
print(f"规范 AST 表达式: {top_alpha['expression']}")
```

#### CLI 命令行一键调用 (无需临时编写脚本)
```powershell
python alpha_machine.py research `
  --paper "D:\quant\brain\reports\papers\pdfs\2605.09712v1_Quantifying_the_Risk-Return_Tradeoff_in_Forecasting.pdf" `
  --region GBR `
  --datasets analyst7,risk68 `
  --execute `
  --database data/alpha_research.db `
  --output gbr_report.md
```

### 16. 一键分层地毯式 Alpha 挖掘与正向自优化 (Stratified Carpet Mining)

一条命令实现全市场、多数据集的大规模自动化挖掘与自进化：**数据集字段动态提取 ➔ 5,000+ 多阶候选 AST 表达式生成 ➔ 6 大语义模板族分类 ➔ 分层均衡随机抽样 ➔ 分批真实回测 ➔ 实时流式落库 (`alpha_expressions`, `alpha_details`, `alpha_checks`) ➔ 零信号模板智能剪枝 ➔ 正向信号针对性 AST 基因突变自优化 (降换手/调衰减/反转) ➔ 输出终审研报**：

#### CLI 命令行一键调用
```powershell
python alpha_machine.py mine `
  --region GBR `
  --universe TOP700 `
  --datasets "insider_agg_matrix,pattern_scores,fundamental31" `
  --sample-per-family 4 `
  --batch-size 5 `
  --execute `
  --output data/gbr_carpet_mining_report.md
```

#### Python API 调用
```python
from alpha_operator_framework.carpet_mining import run_stratified_carpet_mining

result = run_stratified_carpet_mining(
    region="GBR",
    universe="TOP700",
    datasets=["insider_agg_matrix", "pattern_scores", "fundamental31"],
    sample_per_family=4,      # 每一类表达式随机抽选 4 条代表
    batch_size=5,             # 平台每批任务数 (每批跑完即时落库)
    decay=12,
    neutralization="SUBINDUSTRY",
    execute=True,             # 提交真实在线回测 (False 为 0.1 秒 Dry-run)
    output_report_path="data/gbr_carpet_mining_report.md",
)

print(result.summary_markdown())
```

## 与原项目的关系

- 继承 `machine_lib.py` 的核心算子和多阶组合逻辑
- 继承 `cold_templates` 的模板族定义和密度评估方法论
- 新增：算子元数据、AST 语法编译器、文献研发直通车、分层地毯挖掘、AlphaJudge 终审裁决、真实平台回测直连与主数据库自动落库

## 设计红线

1. **纯函数优先**: families/operators/density模块无网络访问
2. **会话单管理**: 模拟统一经`alpha_machine.simulate`（brain_client）
3. **零授权submit**: 默认dry-run，需显式`--execute`才触发check
4. **区域自适应**: group操作符按region自动匹配可用GROUP字段


