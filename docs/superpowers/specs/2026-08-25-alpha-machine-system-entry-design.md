# Alpha Machine 系统入口设计

## 目标

`alpha_machine.py` 是 Alpha Factory 的稳定系统入口：展示并注册命令域、构建总解析器、把命令转发到领域 CLI，同时为现有内部调用提供明确的兼容门面。

## 边界

- `alpha_machine.py` 只做组合、路由、延迟能力导出和进程启动，不承载研究或平台业务算法。
- `alpha_operator_framework.cli.router` 保留解析器构建与命令分派能力，并暴露结构化命令域目录。
- 各命令处理器继续位于 `cli/*` 与 `application/*`。
- 兼容门面只覆盖仓库中仍被调用的稳定能力，不通过通配符重新导出大型旧模块。

## 入口契约

- `build_parser()` 返回完整系统解析器。
- `route(argv=None)` 解析并执行一条命令，返回处理器结果。
- `main(argv=None)` 是进程入口并委托给 `route`。
- `command_domains()` 返回命令域到命令名称的只读映射，用于帮助、测试和后续编排。
- 系统入口显式提供平台仿真、字段发现、JSON IO、结果过滤和轮询守卫等现有兼容能力。

## 命令域

- `fields`: discover、prepare、filter、second-order。
- `simulation`: simulate、poll-simulation。
- `super_alpha`: prepare-super、simulate-super、poll-super。
- `research`: research、mine、auto-pilot、research-cycle、research-worker、research-rebuild。
- `submission`: submission-dispatch。
- `operations`: init-db、clean-db、storage-backup、storage-restore、drill-recovery、status。

## 验收

- 根入口可以列举上述命令域并解析每个已注册命令。
- `route(argv)` 无需修改 `sys.argv` 即可测试和嵌入调用。
- 仓库内现有 `import alpha_machine` 调用的兼容能力可解析。
- 入口契约测试、CLI 测试和全量测试通过。
