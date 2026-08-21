# 项目数据目录

- `fields/<region>/<delay>/<universe>/`：BRAIN 平台导出的字段 CSV / JSON；例如
  `data/fields/GBR/1/TOP700/risk68.json`。`delay` 使用平台数值目录，例如 `0` 或 `1`。
- `imports/`：外部导入的 Alpha、回测结果或其他 CSV 文件。

真实数据文件默认不提交到仓库；仅保留本说明文件。

Survey 默认按参数查找本地文件：传入 `region`、`delay`、`universe`、`dataset` 时，直接读取
`data/fields/<region>/<delay>/<universe>/<dataset>.json`（不存在时尝试 CSV）；未传 `dataset`
时才合并该范围内全部字段文件。本地文件不存在或没有匹配字段时，才会请求平台。使用
`--field-source local` 强制本地，使用 `--field-source platform` 强制平台。显式指定文件时，请同时声明格式：

```text
--fields-file data/fields/GBR/1/TOP700/risk68.csv --fields-file-type csv
```
