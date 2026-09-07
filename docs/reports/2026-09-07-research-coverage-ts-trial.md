# 研究覆盖与 TS 窗口：首版实现及生产试验

## 结论

已实现覆盖调度与有限 TS 窗口搜索，并使用生产 ResearchLoopCoordinator → ResearchRuntime → LiveBrainGateway 完成三轮真实平台回测，每轮 8 条，共 24 条。全部结果成功落库，24 条均有失败检查，合格候选为 0，未提交 Alpha。

这轮证明调度、持久化、反馈及预算停止可以运转；没有证明收益表现提升。所有探测结果均未达到窗口细化的探索门，因而没有生成或执行细化窗口，也没有进入终端验证。新细化分支的正向路径目前由本地回归测试覆盖。

## 改动

| 项目 | 首版行为 |
|---|---|
| 字段准入覆盖 | 在字段总数限制内跨数据集轮转；不再在前几个大文件中凑满 500 条后停止读取。 |
| 回测覆盖 | 根据根任务已选记录，优先补齐数据集、字段和算子/结构组覆盖；顺序由固定 seed 确定。 |
| 阶段调度 | 探索、优化、验证采用 4:2:2 累计权重；空阶段释放容量。 |
| 反馈频率 | 平衡模式每 8 条反馈一次，不等待 64 条全部完成。 |
| TS 粗探 | raw-first-order 外层 TS 初始窗口从 6 个缩为 `[5, 66, 252]`。 |
| TS 细化 | 同字段、同标量化、同算子的相邻探测均通过探索门，且 Sharpe/Fitness 相邻保持比例达到 0.5，才补测有限网格中的中间窗口；单点高分不触发。 |
| 恢复预算 | 用根任务已选表达式保留预算，修正候选重新加载后的 ID 对应，恢复不重新发放整份预算。 |
| 恢复批次 | 从持久化回合编号取下一序号，避免中断恢复后复用旧批次。 |
| 执行保护 | 错误结果和缺失结果遵守重试上限；平台模拟入口保持每批 8 条及配置 truncation。 |
| 证据保留 | 重复发现候选不覆盖已有验证状态和相关指标；任务局部晋升与共享剪枝的全局反例证据分开处理。 |

本版本不改预处理、数据库模板或 AI 表达式内的固定窗口。缓存没有可靠更新频率时不会猜测；显式 frequency 元数据仅保留，尚未用于自动限制窗口。邻域指标一致性不是跨时间或样本外验证。

## 覆盖证据

- 当前 GBR/TOP700 缓存，旧入口加载 500 个字段时只涉及 5 个数据集；新入口同样加载 500 个字段，涉及 140 个数据集。
- 两字段、四算子的本次试验初始池共有 24 条表达式。在相同初始池、相同首批 8 条预算的离线比较中，旧排序前缀与新调度都覆盖了 8 个字段×算子组合；这个小样本没有显示额外覆盖率增益。
- 三轮完成后覆盖两个字段、四个算子和三个粗探窗口，即本次限定初始网格的 24/24。该分母只是实验网格，不是整个 analyst15 数据集，更不是全部平台字段。

因此目前可确认的是入口偏置改善和调度约束有效；还不能把“140 个数据集进入字段池”说成“140 个数据集已回测”，也不能把较小候选池的穷尽说成全市场覆盖。

## 生产试验设置与结果

任务：`coverage-ts-gbr-20260907-v1`。

- 设置：GBR / TOP700，Delay 1，Decay 8，SUBINDUSTRY，Truncation 0.08。
- 数据集：analyst15；字段为 `anl15_dps_gr_12_m_mean`、`anl15_dps_gr_12_m_1m_chg`。
- 算子：ts_mean、ts_delta、ts_rank、ts_zscore；字段及算子经过实时平台查询核实。
- 使用生产协调器的受限 raw-first-order → signal-validation 试验方案；没有将所有默认多阶构造模式都视为已经过生产验证。
- 预算同时限制为 24 个已选候选和 24 次试验调用中的表达式尝试；三轮实际无额外重试。

| 轮次 | 累计完成 | 分类 | 可交候选 |
|---|---:|---|---:|
| 1 | 8 | has_fail_checks × 8 | 0 |
| 2 | 16 | has_fail_checks × 16 | 0 |
| 3 | 24 | has_fail_checks × 24 | 0 |

最高 Sharpe 为 **0.40**、对应 Fitness **0.16**，Alpha ID **9qV99Vge**。最终状态 `BUDGET_EXHAUSTED`，生成优化候选数 0，三个实验批次均为 `EVALUATED`。这些字段/结构目前没有提供继续雕刻时间窗口的依据。

## 验证

- 完整回归：**530 passed**。将原有依赖“当前时间 + 1 分钟”的证据测试放在前面执行，避免它在长测试过程中自然过期；没有放宽生产证据门。
- 收尾发现的批次编号与共享反例证据问题先由测试复现失败，修正后相关定向回归：**81 passed**。这 81 项是在上述完整回归之后、针对最后两处修复执行，未把它们描述成又一次完整套件结果。
- 新调度模块独立 Ruff 检查通过；git diff 空白检查通过。
- 使用实际试验库再次调用协调器，禁止任何平台调用：返回 `BUDGET_EXHAUSTED`，新增回合 0、新增回测 0，已保留候选预算 24，下一批序号为 4。
- 试验数据库 `PRAGMA quick_check` 返回 `ok`。

首次完整测试曾出现新增模块导致质量基线文件计数不一致，以及上述时间敏感测试失败。文件计数已同步，后续完整回归通过。收尾一次独立 PowerShell 启动出现内存不足，后续必要验证命令正常完成；它未导致本次平台回测或落库失败。

## 数据库边界

原配置的 `D:/quant/alpha_factory/data/alpha_research.db` 只读查询仍报 `database disk image is malformed`。本次没有修复、清空或替换原库；真实回测写入独立的试验库。因此现有历史任务恢复与原库可用性仍需另行处理，不能据此宣布原生产数据库已恢复。

## 交付与证据

- [配置与使用说明](D:/quant/alpha_factory/docs/guides/research-coverage-ts-windows.md)
- [默认配置](D:/quant/alpha_factory/configs/alpha-factory.yaml)
- [试验清单](D:/quant/alpha_factory/.codex/research_coverage_ts/20260907/manifest.json)
- [回测决策摘要](D:/quant/alpha_factory/.codex/research_coverage_ts/20260907/backtest_decision.json)
- [运行汇总](D:/quant/alpha_factory/.codex/research_coverage_ts/20260907/run_summary.json)
- [覆盖统计](D:/quant/alpha_factory/.codex/research_coverage_ts/20260907/coverage.json)
- [同预算调度对照](D:/quant/alpha_factory/.codex/research_coverage_ts/20260907/coverage_comparison.json)
- [实际库恢复验证](D:/quant/alpha_factory/.codex/research_coverage_ts/20260907/resume_verification.json)
- [受限生产试验脚本](D:/quant/alpha_factory/.codex/research_coverage_ts/20260907/run_trial.py)

原始结果保存在试验目录中的 backtest_results.json，由指定 brain_sim_summary.py 投影为决策摘要；聊天不展示原始记录。
