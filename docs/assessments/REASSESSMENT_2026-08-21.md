# Alpha Factory 复评：剩余改进项（2026-08-21）

## 复评结论

新增的 `EvidenceLevel`、`TrialLedger`、事件存储、工件存储、Outbox 与 A/B 比较骨架，说明项目已从研究脚本迈向可治理的研究平台；针对证据边界、可复现性和分支实验的方向是正确的。当前仍不能将新内核视为生产研究事实来源：存在一条默认模拟结果可被标为真实平台 IS 并通过提交门禁的路径，且恢复、批处理和对照公平性尚未闭合。

## 已确认改善

- `domain/evidence.py` 区分了 synthetic、sandbox、platform IS/OS 和提交候选，研究结果不再天然同质。
- `core/events.py`、`event_store.py`、`artifacts.py` 和 `projections.py` 已提供事件、投影与内容寻址的基础结构。
- `core/policy.py` 冻结研究策略、验证分区、预算和停止规则；`core/engine.py` 记录 `PartitionLocked` 事件。
- `TrialLedger` 不再将试验数固定为 50，并能由收益序列计算偏度/峰度。
- 聚焦测试 `test_evidence_boundaries.py`、`test_event_sourced_core.py`、`test_overfitting.py` 共 **14 项通过**。

## 仍需优先修复

### P0：默认 mock 回测伪装成 `platform_is`

证据链目前仍可被绕过。`core/outbox_worker.py:44` 在未注入真实平台适配器时使用 `_default_mock_simulator`；该函数在 `:119-132` 用表达式哈希生成 Sharpe/Fitness，并明确返回 `"evidence_level": "platform_is"`。随后 `domain/evidence.py:32-37` 把 `platform_is` 列为可进入提交候选池的证据等级。

**要求：** mock 只能返回 `synthetic`，生产构造 `EventSourcedResearchEngine` 时必须要求真实 `PlatformGateway`、持久化 store 和显式 `production=True`；任何外部结果必须有平台 alpha ID、原始 payload hash 和签名/来源验证后才能提升至 `platform_is`。

### P0：提交门禁未要求 locked OOS，状态跳转也没有顺序约束

`EvidenceLevel.is_eligible_for_submission` 允许 `platform_is`（`evidence.py:32-37`）；`DecisionState.can_transition_to` 仅检查目标是否平台级证据，未检查“当前状态 → 下一状态”的合法边（`:51-57`）。因此 IS 结果可直接跃迁到提交相关状态，不符合已确定的 locked OOS 设计。

**要求：** 提交候选只接受 `submission_ready`；审批函数需验证 `locked_oos` evidence、完整 checks、SC/PC、成本/容量、谱系、人工批准六类证据。状态转移应改为显式邻接表，并将拒绝理由写入事件。

### P1：Outbox 崩溃恢复有丢任务风险

worker 会把 `SIMULATION_ACCEPTED` 和 `SIMULATION_COMPLETED` 都加入已处理幂等键（`outbox_worker.py:52-56`）。若平台已接受任务、进程在完成事件写入前崩溃，重启后该键会被跳过，既不会轮询也不会补偿，任务会永久停在 accepted。

**要求：** 只有 `COMPLETED`/明确终态才关闭 idempotency key；`ACCEPTED` 需要保存真实 Location 并进入可恢复轮询队列。为 accepted→completed、网络超时、重复 worker 三种情形增加集成测试。

### P1：真实网关仍是逐条提交，`batch_size` 未生效

`platform/platform_simulator.py:270-338` 公开 `batch_size` 参数，却在循环中执行 `submit_batch([t], settings)`（`:293-297`），没有使用该参数。它仍会限制批量探索吞吐、增加平台调用与额度浪费。

**要求：** 按 `batch_size` 切分任务，提交完整 chunk；将 batch/child Location 写入 durable outbox，并使用 Retry-After 和子任务终态实现恢复。

### P1：A/B 比较没有真正校验对照条件，并且用 IS 命中率判胜

`core/engine.py:149-187` 没有验证两分支是否同 policy hash、数据快照、locked partitions、预算和 seed；判胜仅为 `sharpe >= 1.25 and fitness >= 1.0` 的命中率（`:167-173`）。这可能比较到不同数据、不同成本或不同候选规模，也会把 IS 过拟合判为胜出。

**要求：** 对照请求必须 fail-closed 校验所有冻结输入一致；主指标改为单位平台预算获得的 locked-OOS 合格因子族数，辅以 OOS 稳定性、增量相关性、成本后换手和置信区间。

### P2：`TrialLedger` 仍是内存对象且尚未接入真实流水线

`TrialLedger` 在 `overfitting.py:283-338` 仅维护进程内计数；除测试外没有生产调用点。重启、跨分支和近似表达式相关性都会使有效试验数失真。

**要求：** 每次生成（包括被先验拒绝、变异、参数重跑）均在 `ExperimentLedger` 持久化；按结构族相关性计算 effective trials，并由 `ValidationService` 唯一提供 DSR 输入。

### P2：原 CLI 的提交 checks 仍未实现

`orchestrator.py:789-791` 仍保留 `trigger_submission_checks` TODO。新状态机接入前，旧 CLI 会造成行为与治理规则不一致。

**要求：** 实现该命令或让旧入口显式拒绝 `--execute` 并引导到新 DecisionEngine；不能输出“已触发 checks”的成功语义。

## 建议的下一轮验收顺序

1. 移除 mock→`platform_is` 路径，并将 submission gate 收紧到 locked OOS 后的 `submission_ready`。
2. 修复 accepted 任务恢复与真实分批提交，做带故障注入的端到端集成测试。
3. 将 TrialLedger 写入事件/数据库并接入所有生成入口；DSR 仅消费持久化账本。
4. 重写 A/B 比较器，强制冻结输入一致并使用 OOS/成本/相关性主指标。
5. 收口旧 CLI，避免新旧流程产生两套冲突的提交标准。

完成前述 1–2 项后，研究可信度会有实质提升；完成全部项目后，才适合以小额度真实实验评估新架构相对旧流程的产出改进。
