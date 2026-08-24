# Alpha Factory 生产级优化路线图

## 目标

建立单一、可重放的投研闭环：策略配置驱动候选构造；事件账本记录事实；worker 可恢复执行；知识、模板、遥测与提交共享同一组合根。

## 已完成基线

- 生产主入口：`research-cycle → research-worker → submission-dispatch`。
- 研究规划仅写入事件与 batch 投影；worker 只运行未完成任务并可恢复 `SUBMITTED`、`PARTIAL_FAILED`。
- EventStore 是新批次审计账本；知识、实验 batch、模板晋升、提交 outbox 为 SQLite 投影。
- 提交要求平台 Alpha、完整证据与显式授权；outbox 有租约和有界重试。
- 策略文件支持权重、模板、剪枝、评估阈值及回测 settings；CLI 冲突 fail-fast。

## 优先级 P0：生产正确性

### P0-1 策略先于字段加载

**问题**：策略文件的 `settings.delay` 已传至 batch，但字段加载仍可能使用 CLI 默认 Delay。

**改造**：先解析 `ResearchPolicy`，再以 `policy.region/universe/delay` 加载字段；CLI 仅作为无策略文件时的默认来源。

**验收**：同一 policy file 在字段快照事件、batch task settings 与平台请求中产生相同的 region/universe/delay/decay/neutralization/truncation。

### P0-2 Batch worker 调度、退避与告警

**问题**：`PARTIAL_FAILED` 可恢复，但需要再次人工启动 worker。

**改造**：增加 worker scheduler；持久化 `attempts/next_retry_at/last_error`；指数退避并对预算耗尽发出告警。

**验收**：进程中断、平台 429、超时后自动恢复；同一 task 不重复回测；耗尽预算后 batch 进入明确终态并产出告警事件。

### P0-3 Event 投影重建

**问题**：现有 SQLite 投影可恢复，但尚不能完全由事件重新构建。

**改造**：提供 `research-rebuild --round-id`，从 PolicyCreated、SimulationRequested/Completed、ValidationComputed、Decision* 事件重建 batch、知识与模板投影。

**验收**：删除测试数据库投影后执行 rebuild，结果与原投影等价；重复执行幂等。

## 优先级 P1：可追溯与治理

### P1-1 知识快照血缘

为 `knowledge_snapshot_history` 增加 `round_id`、`policy_version`、`created_at`、事件 offset；支持按 round、版本和时间查询。

**验收**：任一知识评分均可追到来源 round、模板和回测结果。

### P1-2 提交证据治理

将静态 JSON 证据替换为带 `source`、`verified_at`、`expires_at`、平台回执引用和内容摘要的证据记录；过期或缺少来源时拒绝入队。

**验收**：审批事件包含证据引用；无法验证的 JSON 不可提交。

### P1-3 遥测与告警统一

统一输出 batch 状态、剪枝原因、配额、平台限流、重试、outbox 状态和模板晋升指标；定义 JSONL/Prometheus 适配器与告警阈值。

**验收**：一次完整 round 可得到单一 telemetry snapshot；P0 失败可定位到 round/task/alpha。

## 优先级 P2：策略与研究质量

### P2-1 策略驱动模板构造

将硬编码 `rank_field`、`ts_rank_22` 移入 policy templates；校验模板 AST、字段类型与算子约束。

**验收**：修改策略文件即可增删模板，无需修改 Python；无效模板在规划前失败。

### P2-2 选择与剪枝实验注册

为 weighted/diversity/Thompson/UCB 记录策略版本、随机种子、评分组件、配额消耗和剪枝理由；增加离线对比报告。

**验收**：同 seed/policy 重放获得同一选择；不同算法可按质量、覆盖与成本比较。

### P2-3 模板晋升门槛

将 `min_support`、最小 Sharpe/Fitness、最大相关性和观察窗口写入 policy；模板表记录晋升、降级和淘汰事件。

**验收**：模板不会因单轮偶然结果晋升；阈值变化可审计并可回放。

## 优先级 P3：工程演进

### P3-1 SQLite 迁移管理

为 schema 引入顺序 migration、版本表、升级/回滚演练，替代运行时隐式 `CREATE/ALTER`。

### P3-2 CLI 分层

将 `alpha_machine.py` 拆为 CLI parser、composition root、应用命令和基础设施适配器；每个入口仅解析参数和调用 use case。

### P3-3 运行手册与演练

编写平台限流、worker 卡死、事件重建、提交失败、数据库升级和回滚 runbook；在 CI 中运行崩溃恢复演练。

## 实施顺序

1. P0-1 → P0-2 → P0-3：先保证参数真实性、自动恢复和账本可重建。
2. P1-1 → P1-3：补齐血缘、证据和观测能力。
3. P2-1 → P2-3：将研究能力完全配置化并提升统计稳健性。
4. P3-1 → P3-3：降低长期维护和运维成本。

## 完成定义

一轮生产运行可从 policy、字段快照和事件账本完整重放；任何平台失败自动、有界地恢复；任一提交和模板晋升均可追溯到证据、任务、策略版本与指标；所有入口共享同一 runtime 与迁移后的数据库模式。
