# BRAIN 论坛模板提取报告

## 来源帖子

| 帖子ID | 标题 | 作者 | 投票 | 日期 |
|--------|------|------|------|------|
| 37083826431895 | 条件动量模版 | MY82844 | 48 | 8个月前 |
| 40790666727575 | Earnings模板 | WL58980 | 29 | 2个月前 |
| 40847481080087 | nip族数据点亮news塔 | MY82844 | 89 | 2个月前 |
| 40902892248983 | 行业中性加时序标准化 | WX18521 | 26 | 2个月前 |
| 37140180319127 | MCP七十二变news-sentiment | CY96125 | 33 | 8个月前 |

---

## 模板1: 条件动量模板 (37083826431895)

### 核心表达式

```
ts_mean(if_else(<condition>, returns, 0), <days>)
```

### 经济逻辑

截取某种"有效"时间区间内的股票回报做度量，未来的表现会惯性持续一段时间。

### 槽位说明

| 槽位 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `<condition>` | 布尔表达式 | 事件/正负力对比 | `positive > negative`, `up > down` |
| `<days>` | 整数 | 时间窗口 | 252, 126, 66 |

### 变体思路

1. condition可以是某种事件，或正负数/正负力的对比关系
2. condition=1, days=252 时回到最简单的动量情形
3. sentiment类: `if_else(positive > negative, returns, 0)`
4. analyst类: `if_else(up > down, returns, 0)` (up/down力对比)
5. call/put力对比
6. 可配合group_op()进一步提升表现
7. ts_mean和ts_sum可对比，对NaN处理不同

### 适用category

- **sentiment** (EUR效果佳)
- **analyst** (up/down力对比)
- **news** (news85 DNN新闻做condition)
- 其他有正负/方向性字段的category

### 注意事项

- EUR Sentiment出低PC效果不错
- IND地区也有效果
- 可用news85做condition降低PC

---

## 模板2: Earnings回填模板 (40790666727575)

### 核心表达式

```
<time_series_operator>(ts_backfill(<data_field>, <days_1>), <days_2>)
```

### 经济逻辑

Earnings数据更新频率低（一年四次），使用ts_backfill回填缺失值，再应用时序算子。

### 槽位说明

| 槽位 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `<time_series_operator>` | 算子 | 时序算子 | ts_arg_max, ts_av_diff, ts_quantile, ts_scale, ts_zscore |
| `<data_field>` | 字段 | earnings类字段 | earnings_sent_matrix |
| `<days_1>` | 整数 | 回填窗口 | 10, 252 |
| `<days_2>` | 整数 | 时序窗口 | 252 |

### 变体思路

1. ts_mean可替换ts_backfill: `<ts_op>(ts_mean(<field>, <days_1>), <days_2>)`
2. 二阶嵌套: `<ts_op>(<ts_op>(ts_backfill(<field>, <days_1>), <days_2>), <days_2>)`
3. Universe建议: ILLIQUID_MINVOL1M 更易出货且低相关

### 适用category

- **earnings** (USA/EUR/GLB)
- earnings_sent_matrix 类字段

### 注意事项

- 新数据集相关性普遍低，抢占先机重要
- ts_backfill不计入操作符数量，可算作一阶模板
- USA使用ILLIQUID_MINVOL1M universe更佳

---

## 模板3: NIP相关性模板 (40847481080087)

### 核心表达式

```
ts_corr(<nip_field>, returns, <days>)
ts_covariance(<nip_field>, returns, <days>)
ts_regression(returns, <nip_field>, <days>, lag=0, rettype=2)
```

### 经济逻辑

nip字段(news impact projection)反映新闻对价格的影响投影，与returns相关性可捕捉信息扩散。

### 槽位说明

| 槽位 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `<nip_field>` | 字段 | nip后缀字段 | nws17_multiple_comp_nip, nws20_nip |
| `<days>` | 整数 | 时间窗口 | 180, 120, 66 |

### 变体思路

1. 不同nip字段有区分度，替换使用可降低相关性
2. 数据集来源: news18(Ravenpack), pv87
3. 结合ts算子和group算子控制PC
4. 短窗口版本: `ts_corr(nip_field, returns, 20)` 信号更敏捷

### 适用category

- **news** (news18, pv87)
- **sentiment** (相关性算子+FAST neutralization组合)

### 注意事项

- EUR D0/D1出PPA容易
- 长窗口(如180天)可能混入非事件期噪声
- 建议对比短窗口(10/20天)与长窗口效果
- 使用FAST neutralization

---

## 模板4: 行业中性时序标准化模板 (40902892248983)

### 核心表达式

```
ts_scale(group_rank(<data_field>, industry), <days>)
```

### 经济逻辑

三层结构：
1. 内层: 原始信号（ML分数）
2. 中间层: 行业内排名（消除行业偏差）
3. 外层: 时序标准化（让因子值在不同截面可比）

### 槽位说明

| 槽位 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `<data_field>` | 字段 | 原始信号 | mdl250_maltahc_eq_score |
| `<days>` | 整数 | 标准化窗口 | 30, 22, 66, 120 |

### 变体思路

1. `ts_rank(group_rank(...), <days>)` — 保留排序信息
2. `ts_zscore(group_rank(...), <days>)` — z-score版本
3. 市值中性: `group_rank(..., bucket(rank(cap), range='0.1,1,0.1'))`
4. sector分组 vs industry分组对比
5. 不同分组: industry, sector, subindustry

### 适用category

- **model** (mdl250类)
- 任意需要中性化的标量字段

### 注意事项

- 已提交ind/eur/mea三个地区
- group_rank输出范围0~1
- ts_scale公式: `(x - ts_min(x,d)) / (ts_max(x,d) - ts_min(x,d)) + constant`

---

## 模板5: News-Sentiment相关性模板 (37140180319127)

### 核心表达式

```
group_zscore(-ts_corr(<news_field>, <sentiment_field>, <days>), <group>)
```

### 经济逻辑

捕捉新闻交易活跃度与市场情感之间的动态关系：
- 注意力驱动交易
- 信息扩散理论
- 反应过度与反应不足

### 槽位说明

| 槽位 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `<news_field>` | 字段 | news类字段 | news volume/score |
| `<sentiment_field>` | 字段 | sentiment类字段 | sentiment score |
| `<days>` | 整数 | 相关性窗口 | 30, 66, 120 |
| `<group>` | 分组 | 中性化分组 | industry, sector |

### 变体思路

1. `ts_delay(news, 1)和sentiment的ts_corr` — 新闻与第二天情绪关系
2. 不同group算子: group_zscore, group_rank, group_neutralize
3. 正负号选择: `-ts_corr` vs `ts_corr`

### 适用category

- **news** + **sentiment** 跨category组合
- 需要点两个塔的场景

### 注意事项

- 可能存在混信号嫌疑，需稳定性检测
- sentiment字段早期数据缺失，需筛选
- 跨数据集可能有量纲问题
- 建议提交前做稳定性检测

---

## 模板汇总表

| 模板ID | 名称 | 表达式模板 | 适用category | 中性化建议 |
|--------|------|-----------|--------------|------------|
| T1 | 条件动量 | `ts_mean(if_else(<cond>, returns, 0), <days>)` | sentiment, analyst, news | group_op |
| T2 | Earnings回填 | `<ts_op>(ts_backfill(<field>, <d1>), <d2>)` | earnings | 可选 |
| T3 | NIP相关性 | `ts_corr(<nip>, returns, <days>)` | news, sentiment | FAST |
| T4 | 行业中性时序标准化 | `ts_scale(group_rank(<field>, industry), <days>)` | model, universal | industry |
| T5 | News-Sentiment | `group_zscore(-ts_corr(<news>, <sent>, <days>), <group>)` | news+sentiment | group |

---

## 保存信息

- 提取日期: 2026-08-17
- 来源: BRAIN中文论坛
- 原始数据: `data/brain_forum_posts.json`