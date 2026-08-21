# 研报认知提炼与 Alpha 终审研发报告

- **文献标题**: 2605.09712v1 Quantifying the Risk-Return Tradeoff in Forecasting
- **文献类型**: academic_paper
- **回测模式**: 🌐 WorldQuant BRAIN 真实平台在线回测
- **动态字段库**: 载入 28 个真实数据字段
- **提炼假说数**: 1 个 | **生成 AST 任务数**: 1 个
- **数据库状态**: ✅ 已持久化入库 (1 条表达式, 1 条回测详情)
- **全流程耗时**: 113.08 秒

## 一、 提交优先级排序与终审裁决

| 排名 | Alpha 标识 | 终审评级 | 综合得分 | Sharpe | Fitness | 换手率 | 年化收益 | 最大回撤 | 推荐 Decay | 行动建议 |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| 🥇 | `pwjgX8ex` | `BLOCK` | **-0.2** | -0.02 | 0.00 | 13.0% | -0.15% | 30.64% | `8` | 平台硬性未过项: LOW_SHARPE, LOW_FITNESS, LOW_2Y_SHARPE，禁止直接提交 |

## 二、 推荐首发提交 Alpha 详情

- **Alpha ID**: `pwjgX8ex`
- **AST 规范表达式**: `rank(close) / (0.01 + rank(volume))`
- **经济学机理**: Directly evaluated on WorldQuant BRAIN platform