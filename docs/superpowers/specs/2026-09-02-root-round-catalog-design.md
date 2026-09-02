# 根回合目录与子批次

## 目标

一批候选只保存一次根 `round_id` 目录，消除完整候选在 `round_candidates` 的重复写入；每个八表达式平台分片使用独立 `batch_id`。

## 模型

- `root_round_id`：生成候选、目录、选择状态、剪枝和后续派生的唯一归属；不带 `-catalog` 后缀。
- `batch_id`：格式为 `<root_round_id>-batch-<sequence>`，只归属一次平台回测执行、结果、重试和事件。
- `ResearchLoopCoordinator` 是完整目录的唯一写入者。`ResearchCycleService.plan()` 不创建第二份目录，只将本分片的选择决策回写到指定根目录。

## 不兼容边界

不保留旧调用兼容。所有调用 `ResearchCycleRequest` 的生产路径必须显式传入根目录 ID；缺失时视为配置/编排错误，不得回退为使用子批次 ID。

## 验收

对 64 个候选、每批 8 条的运行：`round_candidates` 仅有 64 个根目录行；创建 8 个唯一子批次；选择状态可在根目录中查询；不存在 `<root>-catalog` 行，也不存在子批次目录行。
