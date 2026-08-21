# Alpha Factory 专业评估（2026-08-21）

## 结论

项目已具备研究平台的主体骨架：表达式 AST、字段与模板、BRAIN 实盘平台回测接口、候选持久化、相关性筛选和基础质量门均已存在。当前成熟度应定位为 **研究自动化原型（Research MVP）**，而不是可直接信赖的生产级 Alpha 工厂：最主要的缺口在于研究结果的真实性边界、数据窥视与多重检验控制，以及可复现实验与提交治理。

## 已验证的优势

1. **结构边界清晰。** `domain/`、`generation/`、`platform/`、`research/`、`database/` 分层合理；AST 规范化与表达式哈希为去重、统计试验计数和研究谱系奠定了正确基础。
2. **平台侧工程基础够用。** 已覆盖认证、重试、轮询、结果落库、SQLite WAL、线程本地连接及事务回滚；选定的单机 SQLite 模式适合当前单用户研究阶段。
3. **风险意识领先于一般因子生成器。** 项目已有 PSR/DSR/haircut、平台 checks、自相关/生产相关、模板剪枝和变异模块，而非只按 IS Sharpe 排序。
4. **基础单测可运行。** 统计防过拟合、沙盒和数据库事务相关测试共 13 项通过。

## 阻塞生产可信度的问题

### P0：离线候选会被人为抬升，不能与真实平台结果混排

`research/pipeline.py:375-381` 会将本地沙盒 Sharpe 强制下限设为 `1.35`，并给定固定 Fitness、Turnover；`research/pipeline.py:413-414` 又给定固定 `pc_value=0.20` 和 `sc_value=0.15`。这会把无效或较弱信号包装成看似达到门槛的候选，并进入同一个 AlphaJudge 排名流程。

**建议：** 将结果状态强制拆成 `synthetic`、`sandbox`、`platform_is`、`platform_os`；只有 `platform_is` 才能进入平台候选池，只有通过预注册 OOS / walk-forward 的结果才可标记为 `submission_ready`。删除指标下限与固定相关性占位，缺失值应保持 `NULL` / `PENDING`，不得以良好数值替代。

### P0：DSR/PSR 的输入不是真实研究自由度，无法作为抗过拟合证据

`research/pipeline.py:327-329` 与 `385-386` 将 `trial_count=50`、`t_days=504` 写死；而系统的生成、筛选、变异、参数试探数量远大于且不恒定于 50。PSR/DSR 同时未从候选日收益序列获取偏度、峰度和有效样本数。

**建议：** 建立不可修改的 `experiment_runs` / `trial_ledger`：每一次表达式、字段、参数、变异和重跑都记录，并按研究家族计算 effective trials。DSR 从真实收益序列统计量计算；把 CSCV/PBO 或 purged walk-forward 作为候选晋级的必经关，而不是报告性指标。

### P1：本地回测是信号诊断器，不是可交易回测器

`domain/sandbox/engine.py:257-286` 仅以 `zscore → scale` 权重计算 forward-return PnL 和换手；没有交易成本、冲击成本、借券、流动性/容量、停牌、可交易性、权重/行业/风格暴露及真实调仓日历。代码注释称“中性化”，但实现中未看到行业或风险模型中性化。

**建议：** 明确将 Sandbox 命名为 `SignalDiagnostic`；若需要本地投资组合验收，新增独立 `PortfolioBacktester`，输入 point-in-time universe、corporate actions、可交易掩码、成本与容量模型，并输出暴露、成交约束和成本后绩效。

### P1：批处理与提交 checks 闭环未落地，无法安全扩展到大规模挖掘

`platform/platform_simulator.py:270-338` 虽声明 `batch_size`，却逐条执行 `submit_batch([t], ...)`，参数实际未使用；这与文档中的批量提交及 5,000+ 候选规模不一致。`orchestrator.py:789-791` 的 `--execute` 提交前 checks 仍是 TODO，因此命令不能完成其声明的终审闭环。

**建议：** 统一使用 `simulation_tracker.py` 的持久化批次模型；为每批记录幂等键、子任务状态、Retry-After、失败原因和恢复点。实现 `trigger_submission_checks` 后，平台 checks / 本地相关性 / 人工批准应形成显式状态机，严禁自动提交。

## 重要但非阻塞的架构改进

| 优先级 | 主题 | 需要补齐的能力 |
|---|---|---|
| P1 | 实验可复现 | 数据快照 ID、字段元数据版本、代码 commit、配置 hash、随机种子、表达式规范化版本和运行环境写入每个 run。 |
| P1 | 研究泄漏治理 | 将 IS、验证、OOS、提交后监控分区建模；禁止同一 OOS 被反复用于调参。 |
| P2 | 数据库谱系 | 当前 `alpha_details.expression_sha` 等关联大多是应用层约定，缺少实验实体及完整外键/审计约束；增加不可变 run、artifact 与 decision 记录。 |
| P2 | 资源治理 | 按数据集/模板族/研究假设设置额度、停止规则和 hit-rate 的置信区间，避免 carpet mining 成为不可控的数据挖掘。 |
| P2 | 监控 | 对平台 API 成功率、429、轮询延迟、失败率、候选漏斗转化率、数据字段漂移和提交后衰减提供日报与告警。 |

## 建议的推进顺序与验收标准

1. **先修结果真实性边界。** 离线路径不再产生可提交评级；所有候选均携带 `evidence_level`。验收：无法通过 API 或 CLI 把 `sandbox/synthetic` 结果写入 `alpha_submission_candidates`。
2. **建立实验账本与严格验证集。** 记录全部试验并以真实有效试验次数计算 DSR。验收：任一候选可追溯到数据快照、代码、配置、表达式、父代及所有同族试验。
3. **完成持久化批次与 checks 状态机。** 验收：进程中断后可无重复提交地恢复；`--execute` 要么完成 checks 并落库，要么明确失败，不能静默跳过。
4. **再建设成本后本地组合回测和提交后监控。** 验收：每个提交候选都有成本后、受约束的 OOS 指标，以及可复核的相关性和暴露报告。

## 架构与 Alpha 构建策略：进一步的优化空间

### 一、将“表达式生成器”升级为“假设驱动的研究系统”

当前主要链路是字段 × 模板 × 变异 × 筛选，覆盖广但自由度极高。建议把每个研究单元固定为：**经济假设 → 因果链 → 可观测代理字段 → 表达式族 → 预注册检验 → 失败归因**。这样模板库不再只是 FASTEXPR 片段，而有 `hypothesis_id`、适用市场、预期持有期、预期方向、风险暴露、失效条件和禁止组合。

最有效的变化不是从 86 个模板扩到更多，而是对每个模板族设置研究预算与停止规则：例如一个字段/假设族连续完成 80 个真实试验且其置信下界的命中率仍低于基准时停止；若在不同市场或时间片稳定有效，才分配更多预算。

### 二、从“单表达式选优”改为“因子族 + 稳定性选择”

同一经济机制的相邻表达式通常高度相关，选 IS Sharpe 最大者很容易选到噪声。建议把 canonical AST、字段集合、算子序列和语义标签共同定义为因子族，并按族而非单表达式竞争。

建议的晋级分数：

`score = median(OOS Sharpe across folds) - instability_penalty - correlation_penalty - complexity_penalty - cost_penalty`

其中 `instability_penalty` 由分期 Sharpe/IC 的离散度、符号翻转率和参数敏感性决定；`complexity_penalty` 对深嵌套、过多自由参数、脆弱的除法/条件分支加罚；`cost_penalty` 来自换手、流动性及借券约束。每个家族保留一个代表和少数正交变体，防止大量近似表达式重复消耗回测额度。

### 三、用分层验证取代单一 IS 门槛

推荐采用四段式时间治理：

1. **Discovery IS：** 可用于生成和初筛；
2. **Validation：** 只允许有限次数的结构修订；
3. **Locked OOS：** 禁止再调参，只做一次晋级判定；
4. **Post-submission：** 监控衰减、拥挤与结构断裂。

横截面因子还应采用滚动或 purged/embargo 的 walk-forward 切分，并按市场状态（波动、利率、行业集中度、流动性）报告条件表现。跨区域推广必须视为新的假设检验，而不是复用一次成功的结果。

### 四、建立“字段质量与新颖性”优先队列

字段选择应在生成前完成，而不是只依赖回测后淘汰。建议在 `datafields` 之上增加字段准入画像：point-in-time 可得性、缺失模式、覆盖率稳定性、更新频率、滞后、单位/量纲、与价格量字段的相关性、已使用次数与历史命中率。

优先挖掘“高覆盖、低拥挤、语义明确、跨期稳定”的字段；对已被大量候选使用且同类因子普遍高相关的字段降权。对于替代数据，必须显式保存供应商版本、发布时间与可交易时点，防止信息时间戳泄漏。

### 五、把参数搜索降维为少数可解释的旋钮

目前 decay、窗口、winsorization、neutralization 等容易形成隐性大规模搜索。每个机制只保留少量先验支持的参数网格，并要求参数邻域稳定：最佳参数周边（如窗口 ±20%、decay ±2）至少多数仍通过验证。否则判定为参数挖掘而非有效 Alpha。

建议将算子分为三层：原始信号变换、风险/缺失处理、组合构造；禁止在单表达式中无限堆叠同类算子。AST 可据此计算复杂度、重复算子、字段复用和潜在未来函数风险，并在提交平台前自动阻断。

### 六、组合层不要直接对 Alpha 收益做 HRP

HRP 可作为权重候选，但不能替代组合约束。先以 OOS 日收益和共同暴露构建协方差，再做带约束的稳健配置：单族权重上限、数据集上限、行业/风格/流动性暴露上限、相关性预算、换手预算和不确定性收缩。权重应按因子置信度与容量折减，并为结构断裂设置 kill-switch。

### 七、推荐的最小目标架构

```text
ResearchSpec (假设与预算，不可变)
  → CandidateFactory (AST + 语义/复杂度约束)
  → ExperimentLedger (全部试验与谱系)
  → ValidationService (walk-forward / DSR / PBO / 稳定性)
  → PlatformGateway (幂等批次与真实结果)
  → DecisionEngine (证据等级状态机)
  → PortfolioService (OOS 协方差、约束、容量与监控)
```

其中 `ExperimentLedger` 与 `DecisionEngine` 最应优先落地：前者让统计显著性可信，后者保证未验证候选无法混入提交池。

## 本次核验范围

静态检查覆盖架构文档、核心回测/平台/研究/数据库模块和当前工作区变更；未读取凭证，未提交或修改业务代码。已运行：`pytest tests/test_overfitting.py tests/test_sandbox.py tests/test_storage_concurrency.py -q`，结果为 **13 passed**。该结果仅证明所测单元行为，不构成真实平台、完整回测或数据质量验证。
