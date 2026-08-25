# Alpha Factory 渐进式质量棘轮设计

## 目标

让 CI 对全部 Python 文件可见，同时不为本轮擅自重写历史代码。现有债务被记录为基线；任何新增 Ruff、Mypy 或死代码退化都使 CI 失败。按用户最新要求，不采集或门禁代码覆盖率。

## 现状

当前 Ruff/Mypy 严格门禁只覆盖部分改动文件；全库仍有历史问题，Mypy 全包检查会触发内部序列化错误，且尚未建立死代码检测基线。

## 设计

保留零错误严格门禁，并由 `tools/quality_ratchet.py` 运行 Ruff、Mypy 和 Vulture，把问题规范化为稳定指纹，与版本控制中的 `quality-baseline.json` 比较；旧指纹允许存在，新指纹返回非零。工具崩溃单独记为失败，不伪装为零问题。

Mypy 按分片运行，绕过一次性全包序列化崩溃，并把每片错误指纹合并。Vulture 使用 80% confidence，动态入口通过显式白名单保留。

CI 顺序为：compileall、严格 Ruff、严格 Mypy、全量 pytest、全库质量棘轮及 CLI/dry-run 流程验证。提供 `baseline --update` 显式更新命令，但 CI 永不自动更新基线。

## 验收

- 所有 Python 文件均进入至少一种全库扫描，新增问题能由回归测试证明会失败。
- 现有严格范围继续保持 Ruff/Mypy 零错误。
- 死代码工具使用固定版本，结果可在 Windows 与 CI 重现。
- 基线文件只保存计数、指纹和阈值，不保存大段原始日志。
- 全量测试与质量工作流通过。
