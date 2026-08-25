# Alpha Factory 核心大模块继续拆分设计

## 目标

拆分 `database/repositories/alpha.py`、`carpet/miner.py` 与 `domain/pruning.py`，并让全部消费者使用新规范模块。删除旧兼容模块，不改变数据库事务、采矿阶段顺序、剪枝算法或平台调用语义。

## AlphaRepository

保留 `AlphaRepository` 作为统一门面，但将实现按职责组合为 mixin：写入与状态迁移、查询与筛选、指标与统计、工作流持久化。SQL、事务边界和返回数据形状原样迁移；数据库 schema 与连接管理不在本轮修改。目标是门面少于 180 行，每个实现模块少于 350 行。

## Carpet Miner

`StratifiedCarpetMiner` 保留协调器身份，将字段加载、候选生成、分层采样和阶段状态迁移分别抽到服务模块；现有 simulation、optimization、distillation 服务继续复用。协调器只保存依赖、调用顺序和规范公开方法。目标是 `miner.py` 少于 300 行；旧 `carpet_mining.py` 删除。

## Pruning

按算法边界拆入 `pruning_components/semantic.py`、`field_topk.py`、`self_correlation.py`、`correlation.py`、`canonical.py` 与 `sandbox.py`；迁移完成后删除 `domain/pruning.py`。算法代码移动时不改阈值、排序稳定性、异步轮询、缓存和持久化格式。

## 内部依赖迁移

`loop.py`、`application/autopilot.py`、`cli/analysis.py`、测试与示例全部改为导入新规范模块。`ai_workflow.py`、`carpet_mining.py`、`orchestrator.py`、`domain/pruning.py` 删除；各自 CLI 入口迁入规范包的 `__main__.py`。使用 AST 和文件存在性测试防止旧模块重新出现。

## 验收

- 规范模块中的类、函数和方法签名保持不变；旧模块导入明确失效。
- 数据库 SQL/事务、采矿顺序与剪枝结果使用黄金测试证明等价。
- `alpha.py` 少于 180 行、`carpet/miner.py` 少于 300 行，四个旧兼容模块不存在。
- 无新循环导入，代码库不再引用已删除模块。
- 全量测试、质量棘轮、Ruff、Mypy、compileall 通过。
