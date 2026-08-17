# CHN 区域 Alpha 表达式分析

## 概览

CHN 区域的表达式有明显的结构特征，与标准一元/二元模板不同，采用了**多层嵌套+特定算子组合**的模式。

---

## 1. Analyst 类 (VECTOR 字段)

### 表达式

```
a = vec_avg(<field>);
b = ts_decay_linear(a, 126) - ts_decay_exp_windows(a, 252, factor=0.95);
signed_power(b, 0.5)
```

### 结构分解

| 层级 | 操作 | 输出 | 说明 |
|------|------|------|------|
| L0 | `vec_avg(<field>)` | a | VECTOR→标量归约 |
| L1 | `ts_decay_linear(a, 126)` | decay_126 | 短窗口线性衰减 |
| L1 | `ts_decay_exp_windows(a, 252, factor=0.95)` | decay_252 | 长窗口指数衰减 |
| L2 | `decay_126 - decay_252` | b | **衰减差异** (跨窗口信号) |
| L3 | `signed_power(b, 0.5)` | 最终 | 保号压缩 |

### 核心模式

**衰减差异信号**：短窗口衰减 - 长窗口衰减，捕捉动量的变化率。

### 适用条件

- VECTOR 类型字段（需要 vec_avg 归约）
- analyst 类数据（更新频率适中）

### 变体空间

| 槽位 | 可选值 |
|------|--------|
| `<field>` | analyst VECTOR 字段 |
| 短窗口 | 63, 126, 252 |
| 长窗口 | 252, 500 |
| factor | 0.90, 0.95, 0.99 |
| power | 0.5, 1, 2 |

---

## 2. Fundamental 类

### 表达式

```
a = <funds_*>;
b = ts_decay_exp_windows(divide(ts_zscore(a, 500), ts_std_dev(ts_zscore(a, 63), 252)), 240, factor=0.5);
signed_power(b, 2)
```

### 结构分解

| 层级 | 操作 | 输出 | 说明 |
|------|------|------|------|
| L0 | `<funds_*>` | a | 原始字段 |
| L1 | `ts_zscore(a, 500)` | z1 | 长窗口标准化 |
| L1 | `ts_zscore(a, 63)` | z2 | 短窗口标准化 |
| L2 | `ts_std_dev(z2, 252)` | std | 短窗口zscore的波动率 |
| L2 | `divide(z1, std)` | ratio | **稳定性比率** (长窗口信号/短窗口波动) |
| L3 | `ts_decay_exp_windows(ratio, 240, factor=0.5)` | b | 指数衰减平滑 |
| L4 | `signed_power(b, 2)` | 最终 | 保号放大 |

### 核心模式

**稳定性比率**：长窗口标准化信号 / 短窗口信号波动率，衡量信号的稳定性。

### 经济逻辑

- 高比率 = 信号稳定持续
- 低比率 = 信号噪音大或反转

### 适用条件

- fundamental 类字段
- 需要衡量信号稳定性的场景

---

## 3. Model 类

### 表达式

```
ts_zscore(group_rank(vec_avg(<model_field>), industry), 500)
```

### 结构分解

| 层级 | 操作 | 输出 | 说明 |
|------|------|------|------|
| L0 | `vec_avg(<model_field>)` | a | VECTOR→标量归约 |
| L1 | `group_rank(a, industry)` | rank | 行业内排名 (0~1) |
| L2 | `ts_zscore(rank, 500)` | 最终 | 时序标准化 |

### 核心模式

**行业中性+时序标准化**：与论坛模板 T4 一致。

### 变体空间

| 槽位 | 可选值 |
|------|--------|
| `<model_field>` | model类VECTOR字段 |
| group | industry, sector, subindustry |
| 窗口 | 252, 500 |

---

## 4. PV 类

### 表达式

```
a = ts_quantile(ts_delta_limit(vec_avg(pv27_*), vc_avg(pv27_*), limit_volume=0.1), 500)
```

### 结构分解

| 层级 | 操作 | 输出 | 说明 |
|------|------|------|------|
| L0 | `vec_avg(pv27_*)` | price_field | 价格相关归约 |
| L0 | `vc_avg(pv27_*)` | vol_field | 成交量相关归约 |
| L1 | `ts_delta_limit(price_field, vol_field, limit_volume=0.1)` | delta | 带成交量约束的变化量 |
| L2 | `ts_quantile(delta, 500)` | 最终 | 时序分位数排名 |

### 核心模式

**量价约束变化**：以成交量为基准约束价格变化，再用分位数排名。

### ts_delta_limit 说明

```
ts_delta_limit(price, volume, limit_volume=0.1)
```
- 计算价格变化，但以成交量为约束
- 当成交量低时，限制价格变化的权重
- 避免低流动性时的噪音

### 适用条件

- pv 类数据（价格+成交量）
- 需要量价结合的场景

---

## 模式总结

| 类别 | 核心算子 | 核心模式 | 特点 |
|------|---------|---------|------|
| **analyst** | `ts_decay_linear - ts_decay_exp_windows` | 衰减差异 | 跨窗口动量变化 |
| **fundamental** | `divide(ts_zscore, ts_std_dev(ts_zscore))` | 稳定性比率 | 信号质量衡量 |
| **model** | `ts_zscore(group_rank(vec_avg))` | 行业中性标准化 | 与T4一致 |
| **pv** | `ts_quantile(ts_delta_limit)` | 量价约束变化 | 低流动性过滤 |

---

## 与现有模板对比

| 现有模板 | CHN表达式 | 相似度 | 差异 |
|---------|----------|--------|------|
| T4 行业中性时序标准化 | model表达式 | **高** | 结构一致，仅多vec_avg |
| T1 条件动量 | analyst表达式 | 低 | 结构完全不同 |
| cold_templates | fundamental表达式 | 低 | 多层嵌套更复杂 |
| BINARY_7 ts_delta_limit | pv表达式 | **中** | 结构相似，但加了ts_quantile |

---

## 潜在新增模板

### T6: 衰减差异模板 (analyst)

```
ts_decay_linear(vec_avg(<field>), <w1>) - ts_decay_exp_windows(vec_avg(<field>), <w2>, factor=<f>)
```

**适用**: analyst, sentiment (VECTOR)
**逻辑**: 短窗口动量 - 长窗口动量 = 动量变化率

### T7: 稳定性比率模板 (fundamental)

```
divide(ts_zscore(<field>, <w1>), ts_std_dev(ts_zscore(<field>, <w2>), <w3>))
```

**适用**: fundamental, analyst (MATRIX)
**逻辑**: 信号稳定性 = 长窗口信号 / 短窗口波动

### T8: 量价约束变化模板 (pv)

```
ts_quantile(ts_delta_limit(<price_field>, <vol_field>, limit_volume=<limit>), <window>)
```

**适用**: pv (需同时有价格和成交量字段)
**逻辑**: 过滤低流动性噪音的价格变化