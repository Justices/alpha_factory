# Alpha Factory 四阶段模块化设计

## 目标

在不改变现有 CLI、公共 Python 导入和平台执行语义的前提下，消除路由重复、内部反向依赖，建立统一质量入口，并把三个千行模块拆成职责清晰的组件。

## 阶段一：命令注册与依赖方向

新增声明式 `CommandSpec` 注册表。每个命令域提供自己的命令规格，根路由只聚合、建 parser 和分派；命令域目录直接从同一规格生成。框架内部不再 `import alpha_machine`，改为直接依赖 CLI、platform 或 application 接口；`alpha_machine.py` 仅服务进程入口和外部兼容。

## 阶段二：质量工具链

新增 `pyproject.toml`，统一 pytest、Ruff 与 Mypy 的项目范围；新增 `requirements-dev.txt`。现有慢 LLM 测试保留，但标注 `slow`，默认 CI 仍执行全部测试，开发者可用 marker 快速运行。

## 阶段三：编排模块拆分

- `orchestration/survey.py`：字段发现、语义剪枝、survey 命令。
- `orchestration/deepen.py`：二阶深化与回测批次。
- `orchestration/submission.py`：提交检查、证据审批与输出。
- `orchestration/commands.py`：run-all 与参数编排。
- 原 `orchestrator.py` 保留兼容导出和 CLI parser。

## 阶段四：研究引擎拆分

- `carpet/models.py` 保存配置和结果类型；`carpet/miner.py` 保存主协调器；`carpet/simulation.py`、`carpet/optimization.py`、`carpet/distillation.py` 保存独立阶段服务；原 `carpet_mining.py` 作为兼容门面。
- `workflow/models.py` 保存配置和结果；`workflow/branches.py` 保存分支构建/执行；`workflow/survey.py` 与 `workflow/full.py` 保存主流程；原 `ai_workflow.py` 作为兼容门面。

## 兼容与错误处理

原模块路径和公开符号继续有效；新模块之间只通过显式函数、dataclass 和 Protocol 通信。移动过程中不吞异常、不改变 dry-run/execute 门禁、不增加平台调用。

## 验收

每阶段先增加结构/契约测试，再移动实现；旧入口与新入口返回同一对象。入口、领域、数据库和全量 pytest 通过；Ruff 及选定模块 Mypy 通过；三个原千行模块均降为薄兼容门面。
