# Alpha Factory 延迟包初始化设计

## 目标

在不破坏 `from alpha_operator_framework import <symbol>`、子模块导入和 CLI 命令行为的前提下，移除包根的批量热启动导入。冷进程执行 `import alpha_operator_framework` 与 `alpha_machine.py --help` 的中位耗时目标均小于 1.5 秒。

## 现状

`alpha_operator_framework/__init__.py` 约 598 行，包含 35 组框架内导入。一次空包导入平均约 4.9 秒并加载约 1570 个模块；导入任意 `alpha_operator_framework.*` 子模块时也会先承担这部分成本。

## 设计

包根只保留版本信息、类型检查导入和一份声明式延迟导出表。模块级 `__getattr__` 首次访问公开符号时导入其真实模块、缓存到 `globals()` 并返回；`__dir__` 与显式 `__all__` 继续支持发现和 IDE 补全。子模块对象导出也进入同一张表，不保留隐式星号导入。

循环依赖风险通过两条规则控制：真实实现不得依赖包根重导出；内部代码改为导入定义模块。兼容测试覆盖现有公开符号、对象 identity、未知属性错误和重复访问缓存。

## 性能验证

新增独立子进程基准测试，避免当前进程的模块缓存污染。测试采集三次冷启动的中位数，并记录模块数量；CI 使用宽松的 2.5 秒上限防止共享 runner 抖动，本地验收目标仍为 1.5 秒。性能测试不访问网络、数据库或平台凭证。

## 验收

- 现有包根公开符号与 `__all__` 保持兼容。
- `import alpha_operator_framework` 和 CLI `--help` 本地冷启动中位数小于 1.5 秒。
- 包根导入不主动初始化数据库、NumPy/Pandas、平台会话或研究引擎。
- 全量测试、Ruff、Mypy、compileall 与 CLI help 通过。

