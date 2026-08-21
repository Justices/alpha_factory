# Alpha Factory 生产运行就绪性复核（2026-08-21）

## 结论

**不建议现在放入无人值守的生产真实运行。** 可以继续以受控的小批真实回测进行研究，但尚不满足“自动批量探索 → 稳定恢复 → 完整终审 → 安全提交”的生产准入标准。

专项测试 `test_auto_pilot.py`、`test_recovery_drill.py`、`test_evidence_boundaries.py`、`test_event_sourced_core.py`、`test_storage_concurrency.py` 共 **16 项通过**；这证明了关键单元/模拟路径，不替代真实平台故障与长时间排队的端到端验证。

## 阻塞项

### P0：真实平台出现悬挂批次，尚无自动处置闭环

本次真实 USA/ILLIQUID_MINVOL1M 冒烟中，持久化批次 5 长时间停在平台 `progress=0.35`，无子任务 ID、无错误、无自动超时转移或告警。此前批次 2–3 的顶层返回 `ERROR`，但数据库子任务仍显示 `running`，说明顶层批次状态与子任务投影没有统一的终态语义。

**生产准入要求：** 定义最大运行时长、无进展 TTL、Retry-After、子任务优先状态聚合和人工升级队列；超时后只能“重试轮询/查已提交 Location”，不得直接重提。完成一次真实故障演练：杀死 worker、重启、恢复 accepted/running/stalled 三类任务且零重复提交。

### P0：一键生产入口的执行路径存在运行时错误

`alpha_operator_framework/orchestrator.py:804` 使用 `AlphaDatabase(db_path=args.db)`，但 `submit` 与 `run-all` 的 parser 没有定义 `--db`，而 `cmd_run_all` 构造的 `submit_args` 也未提供 `db`。一旦 `run-all --execute` 进入提交终审，会抛出 `AttributeError`，使“全流程”不能完成。

**生产准入要求：** 统一使用 `args.database` 或显式传递 `database`；为 `run-all --execute` 增加端到端测试，覆盖候选为空、候选拒绝、候选通过、平台 checks 缺失四种情形。

### P1：终审当前只能安全拒绝，尚未形成真实 OOS/提交闭环

CLI 在 `orchestrator.py:819-827` 以 `EvidenceLevel.PLATFORM_IS` 调用审批器，未传入 locked-OOS 证据；正确的严格审批应拒绝这种请求，但这也意味着旧 CLI 尚不能完成正式候选晋级。`--execute` 读取已存 checks，而不是触发或等待缺失的真实 checks。

**生产准入要求：** 用事件引擎唯一负责 `platform_is → locked_oos → checks_verified → submission_ready`；将 OOS artifact、SC/PC、成本/容量和人工审批作为不可绕过的写入条件。旧 CLI 必须委托该引擎或禁用提交终审入口。

### P1：生产核心与批量网关没有统一的运行路径

`EventSourcedResearchEngine.create_production_engine()` 已创建真实 `BrainPlatformAdapter`，但 Outbox 的适配函数按单表达式调用 `simulate_single()`；真正的批量持久化路径仍在 `alpha_machine.py`。这形成两个不同的状态机、恢复语义与记录格式，难以保证大批运行的一致性。

**生产准入要求：** 让 Outbox 以真实平台 batch 为原子操作，并复用 `SimulationTracker` 的 Location/child 状态；以一个入口启动、恢复和终审，而不是并行维护两套生产路径。

### P1：表达式字段类型在本地未被强约束

本轮 `shortinterest3` 的 EVENT 字段若直接传给 `ts_delta` / `ts_zscore`，平台才返回“operator does not support event inputs”；修正为 `vec_avg(...)` 后才可计算。此类类型错误应在生成/AST 验证阶段被拒绝，不能消耗真实回测额度。

**生产准入要求：** 字段缓存必须保存 `type`；AST validator 依据操作符签名校验 EVENT→标量转换、单位、group 字段与 lag。无效表达式在本地标记 `rejected_prior`，不能进入 outbox。

## 发布前最小清单

1. 修复并测试 `run-all --execute` 的数据库参数与全部终审分支。
2. 完成真实平台的悬挂/重启恢复演练，并设置 batch watchdog、告警和人工升级队列。
3. 将生产入口收敛到事件账本 + 批量 `SimulationTracker`，并移除并行状态机。
4. 在本地启用字段类型验证；用 20–30 条真实小批完成无语法/类型失败的验收。
5. 用已锁定 OOS、checks、SC/PC 和人工审批走通一条 `submission_ready` 流程；保持“不自动提交”策略。
6. 清理并提交当前工作区，打出可回滚版本与配置/数据快照清单。

满足上述清单后，建议先以受控配额和人工值守上线 1–2 周；确认无重复提交、无未告警悬挂、决策链可完整重放后，才转为无人值守运行。
