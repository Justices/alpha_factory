# 因子生成策略与多族架构设计 (Strategy Architecture)

> **定位**: 阐述 Alpha Factory 统一因子构造策略体系（Unified Construction Strategies）、10 大母版族群、AST 结构测量与约束、符号语法树自由杂交与 DDD 纯抽样探索架构。

---

## 一、 统一构造策略架构全景

框架的因子生成已全面演进为 **统一显式声明构造策略 + AST 独立结构约束 (`order_depth`, `field_count`) + 统一确定性准入管线 + 10 大母版族群 + 符号语法树自由杂交 + 模板库闭环晋升**：

```mermaid
flowchart TD
    subgraph CONFIG["一、 显式策略配置层 (YAML Strategy Config)"]
        CF1["configs/alpha-factory.yaml"]
        CF2["ConstructionPlan (typed & validated)"]
        CF3["StructuralConstraint: order_depth & field_count"]
    end

    subgraph REGISTRY["二、 统一策略注册中心 (ConstructionStrategyRegistry)"]
        S1["1. DatabaseTemplateStrategy (kind: database_template)\n• 加载 template_library 种子与自进化模板\n• 参数化槽位实例化与自适应变异"]
        S2["2. DepthConstructionStrategy (kind: depth_construction)\n• 算子嵌套深度约束 (order_depth)\n• 多阶时序算子递归嵌套与衍生"]
        S3["3. FieldCompositionStrategy (kind: field_composition)\n• 原始字段数量约束 (field_count)\n• 多元字段跨源协同、截面正交与非线性交互"]
        S4["4. LiteratureLlmStrategy (kind: literature_llm)\n• 学术研报/PDF 假说提取\n• LLM 结构化表达式转译 (untrusted draft)"]
    end

    subgraph PIPELINE["三、 统一确定性准入管线 (Shared Acceptance Pipeline)"]
        P1["ASTValidator 语义与类型校验 (拦截 close/open 等)"]
        P2["StructureMeasurement (精确测量 order_depth & field_count)"]
        P3["StructuralConstraint 独立维度范围过滤"]
        P4["FASTEXPR 规范化转译 & SHA256 等价去重"]
        P5["确定性叶子族群映射 (leaf_family) & 多源谱系写入"]
    end

    subgraph SAMPLING["四、 DDD 纯抽样与调度 (Sampling & Execution)"]
        SP1["4 大纯抽样算法 (D-Optimal / Thompson / UCB / Stratified)"]
        SP2["单叶子族配额约束 (Quota per leaf family <= 8)"]
        SP3["平台标准 8 条切片并发回测 (Batch Size = 8)"]
    end

    subgraph PROMOTION["五、 模板晋升与终生复用闭环 (Promotion Chain)"]
        PR1["胜出因子 (Sharpe>=1.0 / READY)"]
        PR2["TemplateAbstractor 去标识化提取 ({a}, {b} 骨架)"]
        PR3["template_library 单一可信源持久化 (合并 source_task_ids 证据)"]
    end

    CONFIG --> REGISTRY
    REGISTRY --> PIPELINE
    PIPELINE --> SAMPLING
    SAMPLING --> PROMOTION
    PROMOTION -.->|自动回填| S1
```

---

## 二、 独立结构约束维度与测量 (`research/structure.py`)

系统引入两个正交且解耦的 AST 结构测量维度：
- **`order_depth`（算子嵌套深度）**：
  - 从 AST 根节点到叶子节点所经过的算子层级深度；
  - 一阶算子（如 `rank(A)`、`ts_delta(A, 20)`）对应 `order_depth = 1`；
  - 二阶复合算子（如 `group_rank(ts_delta(A, 20), subindustry)`）对应 `order_depth = 2`；
  - 高阶嵌套（如 `ts_scale(group_rank(ts_delta(A, 20), subindustry), 30)`）对应 `order_depth = 3`。
- **`field_count`（原始字段数量）**：
  - AST 树中引用的去重底层特征字段总数；
  - 单字段公式（`field_count = 1`）、双字段比率/残差（`field_count = 2`）、三字段条件切换（`field_count = 3`）。
- **独立过滤与声明**：
  ```yaml
  research:
    construction:
      strategies:
        - strategy_id: "deep_momentum"
          kind: "depth_construction"
          families: ["ts_momentum", "macd_velocity"]
          order_depth: { exact: 3 }
          field_count: { exact: 1 }
          quota_per_leaf_family: 8
  ```

---

## 三、 10 大生成族群核心机理

| 族群名称 | 标识符 (Family) | 核心数学形态示例 | 捕获的金融异象 / 机制 |
| :--- | :--- | :--- | :--- |
| **1. 时序动量族** | `ts_momentum` | `group_neutralize(rank(ts_delta(A, 20)), subindustry)` | 价格与预期基本面的中期趋势持续性 |
| **2. 均值反转族** | `mean_reversion` | `-1.0 * group_neutralize(rank(A), subindustry)` | 短期过度反应与流动性冲击后的均值回归 |
| **3. MACD加速度族**| `macd_velocity` | `group_neutralize(rank(ts_decay(A, 5) - ts_decay(A, 20)), subindustry)` | 短期预期均线相对于长期均线的加速度突破 |
| **4. 相对比率溢价族**| `relative_ratio` | `group_neutralize(rank(A) / (0.01 + rank(B)), subindustry)` | 跨特征估值溢价与相对质量比率 |
| **5. 不对称波动族** | `asymmetric_risk`| `group_neutralize(rank(ts_std_dev(A, 20) / (0.01 + ts_mean(A, 20))), subindustry)` | 波动率异象与下行风险补偿 |
| **6. 行业-特质正交分解**| `sector_decomposition` | `ts_zscore(A, 20) - ts_zscore(group_neutralize(A, sector), 20)` | 剥离行业 Beta 后的特质纯 Alpha 剪刀差 |
| **7. 三层尺度架构** | `three_tier_scaling` | `ts_scale(group_rank(A, subindustry), 30)` | 内层特征、中层行业分箱、外层滚动时序标准化 |
| **8. 跨源多数据协同**| `cross_interaction` | `group_neutralize(rank(A) * rank(B), subindustry)` | 另类情绪与基本面之间的多源非线性协同 |
| **9. 符号杂交进化** | `symbolic_evolution` | 递归 AST 1~4 层深度树生成 | 摆脱人工模板，自动生成高阶现代量化形态 |
| **10. 沉淀知识蒸馏**| `evolved_distillation` | 动态加载 `template_library` 骨架并注入新字段 | 站在历史成功因子的肩膀上跨数据集复用 |

---

## 四、 DDD 抽样探索算法

位于 `alpha_operator_framework/research/selection.py`：

1. **`D-Optimal`（推荐默认）**：
   - 构建候选因子的特征矩阵（操作符指纹、窗口跨度、分组维度）；
   - 最大化信息矩阵行列式 $\det(X^T X)$，确保在有限回测配额下覆盖最大化的假设特征空间。
2. **`Thompson Sampling`**：
   - 为每个模板族维护 Beta 分布后验胜率；
   - 每次回测时从后验分布抽样，自适应将更多配额倾斜给历史高夏普族群，同时保留探索能力。
3. **`UCB (Upper Confidence Bound)`**：
   - 平衡族群平均胜率与试验不确定性；
   - 优先尝试高潜力且试验次数较少的新兴结构族。
4. **`Stratified`**：
   - 严格分层均衡抽样，保证每个模板族均匀分配回测任务，适合全景摸底。
5. **`Diversity`**：
   - 基于 AST 树结构编辑距离最大化候选多样性，剔除同质化候选。

---

## 五、 统一构造策略 Python API 示例

```python
from alpha_operator_framework.research.strategy_config import (
    ConstructionPlan,
    ConstructionStrategyConfig,
    StructuralConstraint,
)
from alpha_operator_framework.research.strategies import ConstructionStrategyRegistry
from alpha_operator_framework.domain.fields import FieldSpec

# 1. 构造类型化配置方案
plan = ConstructionPlan(
    strategies=(
        ConstructionStrategyConfig(
            strategy_id="base_db_templates",
            kind="database_template",
            families=("unary", "binary"),
            order_depth=StructuralConstraint(minimum=1, maximum=2),
            field_count=StructuralConstraint(minimum=1, maximum=2),
            quota_per_leaf_family=8,
        ),
    ),
    platform_batch_size=8,
)

# 2. 注册与候选生成
registry = ConstructionStrategyRegistry()
fields = [
    FieldSpec(id="returns", dataset_id="pv1", type="MATRIX"),
    FieldSpec(id="volume", dataset_id="pv1", type="MATRIX"),
]
candidates = registry.generate_candidates(plan, fields=fields, seed=42)
print(f"✅ 统一构造管线生成并验收 {len(candidates)} 个规范候选")
```