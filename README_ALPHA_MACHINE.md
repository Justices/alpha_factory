# alpha_machine 统一 CLI 与工业级研究流水线指南

`alpha_machine.py` 是与 WorldQuant BRAIN 平台无缝交互的工业级入口，提供从**前沿学术文献研报深度转化**到**大规模分层地毯式挖掘、流式回测入库、智能剪枝、正向自优化与超级组合因子 (Super Alpha)** 的全套闭环能力。

---

## ⚡ 核心流水线命令一览

| 命令 | 模式类型 | 核心功能与应用场景 | 关键参数 |
| :--- | :---: | :--- | :--- |
| **`mine`** 🌟 | **全闭环地毯挖掘** | 一键基于指定区域、股票宇宙和数据集，海量生成 AST 表达式、按 6 大模板族分层抽样、分批回测、实时流式入库、零信号剪枝、正向信号二次突变自优化 | `--region`, `--universe`, `--datasets`, `--sample-per-family`, `--batch-size`, `--execute` |
| **`research`** 🌟 | **文献研究流水线** | 一键解析学术研报/PDF/Markdown，提取经济学因果机理与量化假设，动态映射真实字段，生成规范 AST 表达式，在线回测并执行 AlphaJudge 5 层终审与落库 | `--paper`, `--region`, `--universe`, `--datasets`, `--use-llm`, `--execute`, `--output` |
| **`discover`** | 字段动态探索 | 按平台条件快速检索并筛选全量可用字段（只读，零额度消耗） | `--region`, `--universe`, `--delay`, `--dataset`, `--min-coverage`, `--output` |
| **`prepare`** | 任务池笛卡尔生成 | 原子预处理字段、生成一阶特征池、配置多重 Decay、随机 Shuffle 生成标准 Task Pool | `--fields`, `--windows`, `--decays`, `--batch-size`, `--output` |
| **`simulate`** | 平台分批模拟 | 安全并发向 BRAIN 提交回测任务并轮询完整绩效指标与 18 项 Checks | `--tasks`, `--execute`, `--output` |
| **`simulate-super`** | 超级因子正交组合 | 将多个异构优胜 Alpha 聚合为单子/多子 Super Alpha，通过 HRP 风险平价与 Gram-Schmidt 正交化生成合成 Alpha | `--alphas`, `--weights`, `--execute` |
| **`filter`** | 离线质量门筛选 | 按 Sharpe、Fitness、Margin、Turnover 范围及 2Y 稳定性离线精细筛选 | `--results`, `--sharpe`, `--fitness`, `--margin`, `--output` |

---

## 🚀 场景 1: 一键分层地毯式 Alpha 挖掘与自优化 (`mine`)

针对指定市场区域和纯另类数据集（如高管增减持、技术形态模式识别、基本面因子等），执行大规模生成、分层抽样与自优化全闭环：

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

### 全自动执行流程：
1. **海量生成**：0.1 秒内从目标数据集中生成 5,000+ 条多阶 AST 表达式；
2. **分类分层抽样**：按 `ts_momentum`（时序动量）、`mean_reversion`（均值回归）、`macd_velocity`（长短均线差分）、`relative_ratio`（相对比率）、`asymmetric_risk`（不对称风险）、`cross_interaction`（跨源协同）6 大族分类，每类随机抽选 4 条代表因子；
3. **分批回测与流式落库**：每批 5 个任务跑完立刻持久化到主库 `alpha_expressions`, `alpha_details`, `alpha_checks`；
4. **零信号智能剪枝**：对整体零信号/违规模式自动生成剪枝规则并写入 `template_prune_rules`；
5. **正向信号自进化**：对 Sharpe $\ge 0.35$ 或年化收益 $\ge 2\%$ 的优胜因子，自动触发 AST 变异修复（降换手、调衰减、反义反转），提交二代优化回测并落库。

---

## 📚 场景 2: 一键学术文献/研报端到端研发流水线 (`research`)

直接将学术论文（PDF 或 Markdown）转化为在线实测 Alpha 并完成评级落库：

```powershell
python alpha_machine.py research `
  --paper papers/2605.09712v1.pdf `
  --region GBR `
  --universe TOP700 `
  --datasets "model30,risk71" `
  --decay 10 `
  --neutralization SUBINDUSTRY `
  --execute `
  --output data/gbr_paper_report.md
```

### 全自动执行流程：
1. **文献因果解析**：提取论文核心经济学逻辑（例如非对称下行风险、分析师盈利预期修正残差）；
2. **动态字段映射**：自动对接目标区域真实市场字段（如 `model30`, `risk71` 中的分析师预期与特质残差）；
3. **AST 编译器转译**：生成纯净合规的 BRAIN FASTEXPR 表达式；
4. **真实平台回测**：向 BRAIN 官方服务器提交在线回测；
5. **AlphaJudge 终审评估**：执行 5 层防线裁决（Quality Gate, DSR/PSR/Haircut 抗过拟合, 18 项平台 Checks, Super Alpha 权重建议）；
6. **自动持久化**：完整同步写入 `data/alpha_research.db`。

---

## 🗄️ 数据库架构与双向关联

所有流水线统一沉淀至单一大主库 [`data/alpha_research.db`](file:///d:/quant/alpha_factory/data/alpha_research.db)：
- **`alpha_expressions`**：记录唯一规范化表达式原型、SHA 校验和、来源标记（`carpet_mining:*`, `paper:*`, `evolution:*`, `super_alpha:*`）；
- **`alpha_details`**：记录各表达式在 WorldQuant BRAIN 平台上的真实性能（Sharpe, Fitness, Turnover, Margin, Returns, Drawdown, PnL, wf_stage）；
- **`alpha_checks`**：记录每次回测对应的 18 项平台级硬性检查明细；
- **`template_prune_rules`**：记录剪枝引擎总结的负向经验模式，防止后续重复回测垃圾模板。

---

## 🔑 认证与配置

- 账号凭据保存在项目根目录的 `.brain.json`（权限 600）；
- 首次请求会自动登录并缓存 Cookie 会话到 `.brain_session.json`；
- 所有只读探索（如 `discover` 或不带 `--execute` 的 `mine`）不消耗任何回测额度。
