# Alpha Factory 核心大模块继续拆分设计

## 目标

拆分 `database/repositories/alpha.py`、`carpet/miner.py` 与 `domain/pruning.py`，并让框架内部消费者使用新规范模块。旧路径只承担外部兼容，不改变数据库事务、采矿阶段顺序、剪枝算法或平台调用语义。

## AlphaRepository

保留 `AlphaRepository` 作为统一门面，但将实现按职责组合为 mixin：写入与状态迁移、查询与筛选、指标与统计、工作流持久化。SQL、事务边界和返回数据形状原样迁移；数据库 schema 与连接管理不在本轮修改。目标是门面少于 180 行，每个实现模块少于 350 行。

## Carpet Miner

`StratifiedCarpetMiner` 保留协调器身份，将字段加载、候选生成、分层采样和阶段状态迁移分别抽到服务模块；现有 simulation、optimization、distillation 服务继续复用。协调器只保存依赖、调用顺序和公开兼容方法。目标是 `miner.py` 少于 300 行，且 facade monkeypatch seam 继续有效。

## Pruning

按算法边界拆为 `pruning/semantic.py`、`field_topk.py`、`self_correlation.py`、`correlation.py`、`canonical.py` 与 `sandbox.py`；`domain/pruning.py` 变为显式兼容门面。算法代码移动时不改阈值、排序稳定性、异步轮询、缓存和持久化格式。

## 内部依赖迁移

`loop.py`、`application/autopilot.py`、`cli/analysis.py` 及其他生产代码改为导入新规范模块；兼容路径仅保留给外部调用和兼容测试。使用 AST 依赖测试防止生产代码重新依赖 `ai_workflow.py`、`carpet_mining.py`、`orchestrator.py` 或新的 `domain/pruning.py` 门面。

## 验收

- 旧类、函数、方法签名和对象 identity 保持兼容。
- 数据库 SQL/事务、采矿顺序与剪枝结果使用黄金测试证明等价。
- 三个目标文件分别达到少于 180、300、150 行的门面/协调层目标。
- 无新循环导入，内部生产代码不依赖兼容门面。
- 全量测试、质量棘轮、Ruff、Mypy、compileall 通过。

