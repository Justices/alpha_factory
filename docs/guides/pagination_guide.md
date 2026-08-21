# 分页获取逻辑说明

## 改进内容

新增完整的分页支持，解决原问题：只能获取有限数量alpha。

## 核心改进

### 1. fetch_user_alphas - 分页获取

**新增参数**:
```python
async def fetch_user_alphas(
    region: Optional[str] = None,
    status: str = "IS",
    min_sharpe: Optional[float] = None,
    min_fitness: Optional[float] = None,
    limit: int = 100,           # 总数限制 (0=获取全部)
    order_by: str = "-is.sharpe",
    page_size: int = 50,         # ✨ 新增: 每页数量
    max_pages: int = 20,         # ✨ 新增: 最大页数
    enable_pagination: bool = True  # ✨ 新增: 是否分页
) -> List[Dict]
```

**分页逻辑**:
```python
while True:
    # 1. 检查是否达到最大页数
    if page >= max_pages:
        break

    # 2. 计算本次获取数量
    if limit > 0:
        remaining = limit - len(all_alphas)
        current_page_size = min(page_size, remaining)
    else:
        current_page_size = page_size

    # 3. 查询当前页
    alpha_rows = await fetch_user_alphas(offset=offset, limit=current_page_size)

    # 4. 没有更多数据
    if len(alpha_rows) < current_page_size:
        break

    # 5. 准备下一页
    page += 1
    offset += current_page_size
```

### 2. fetch_alpha_by_ids - 批量查询

**新增参数**:
```python
async def fetch_alpha_by_ids(
    alpha_ids: List[str],
    batch_size: int = 10,    # ✨ 新增: 每批数量
    max_retries: int = 3     # ✨ 新增: 失败重试次数
) -> List[Dict]
```

**批量逻辑**:
```python
# 分批查询
total_batches = (len(alpha_ids) + batch_size - 1) // batch_size

for batch_idx in range(total_batches):
    batch_ids = alpha_ids[start:end]

    # 重试逻辑
    for retry in range(max_retries):
        try:
            batch_alphas = await fetch_batch(batch_ids)
            all_alphas.extend(batch_alphas)
            break
        except:
            # 失败重试
            continue
```

## 使用示例

### 示例1: 获取全部alpha
```python
# 获取EUR市场所有未提交的alpha
alphas = await fetch_user_alphas(
    region="EUR",
    status="IS",
    limit=0,           # 0表示获取全部
    page_size=100,     # 每页100个
    max_pages=50       # 最多50页=最多5000个
)

print(f"总计: {len(alphas)}个alpha")
```

**输出**:
```
第1页: 获取100个, 累计100个
第2页: 获取100个, 累计200个
第3页: 获取100个, 累计300个
...
第50页: 获取45个, 累计4945个

总计获取: 4945个alpha
```

### 示例2: 限制总数
```python
# 获取前500个高质量alpha
alphas = await fetch_user_alphas(
    min_sharpe=1.2,
    limit=500,         # 最多500个
    page_size=100,     # 每页100个
    enable_pagination=True
)
```

**输出**:
```
第1页: 获取100个, 累计100个
第2页: 获取100个, 累计200个
第3页: 获取100个, 累计300个
第4页: 获取100个, 累计400个
第5页: 获取100个, 累计500个

总计获取: 500个alpha
```

### 示例3: 单页获取(不分页)
```python
# 快速获取前50个
alphas = await fetch_user_alphas(
    region="EUR",
    limit=50,
    enable_pagination=False  # 不分页
)
```

### 示例4: 批量查询alpha_id
```python
# 查询100个指定的alpha_id
alpha_ids = ["alpha_001", "alpha_002", ...]  # 100个ID

alphas = await fetch_alpha_by_ids(
    alpha_ids,
    batch_size=20,    # 每批20个
    max_retries=3     # 失败重试3次
)
```

**输出**:
```
查询批次1/5: 20个alpha
查询批次2/5: 20个alpha
查询批次3/5: 20个alpha
查询批次4/5: 20个alpha
查询批次5/5: 20个alpha

总计获取: 98/100个alpha
成功率: 98.0%
```

## 参数说明

### fetch_user_alphas

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `limit` | 总数限制 (0=获取全部) | 100 |
| `page_size` | 每页获取数量 | 50 |
| `max_pages` | 最大页数(防止无限循环) | 20 |
| `enable_pagination` | 是否启用分页 | True |

### fetch_alpha_by_ids

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `batch_size` | 每批查询数量 | 10 |
| `max_retries` | 失败重试次数 | 3 |

## 典型场景

### 场景1: 分析所有alpha
```python
# AI分析用户全部alpha
alphas = await fetch_user_alphas(
    status="IS",
    limit=0,          # 获取全部
    page_size=100,
    max_pages=50
)

# 分类统计
high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)
marginal = filter_marginal_alphas(alphas, sharpe_range=(1.2, 1.8))

print(f"总计: {len(alphas)}个")
print(f"高质量: {len(high_quality)}个")
print(f"边缘: {len(marginal)}个")
```

### 场景2: 批量查询
```python
# 用户: "查询这100个alpha的状态"

# 从文件读取alpha_id列表
alpha_ids = ["alpha_001", "alpha_002", ...]  # 100个

# 批量查询
alphas = await fetch_alpha_by_ids(
    alpha_ids,
    batch_size=20,
    max_retries=3
)

# AI回复
print(f"查询完成: {len(alphas)}/{len(alpha_ids)}个")
print(f"成功率: {len(alphas)/len(alpha_ids)*100:.1f}%")
```

### 场景3: 快速预览
```python
# AI快速预览前50个alpha
alphas = await fetch_user_alphas(
    region="EUR",
    limit=50,
    enable_pagination=False  # 不分页,更快
)

# 分析
if len(alphas) > 0:
    avg_sharpe = sum(a['sharpe'] for a in alphas) / len(alphas)
    print(f"平均Sharpe: {avg_sharpe:.2f}")
```

## 最佳实践

### 1. 控制分页速度
```python
# 慢速分页,避免触发平台限流
alphas = await fetch_user_alphas(
    page_size=50,    # 每页较少
    max_pages=10     # 限制页数
)
```

### 2. 处理大量alpha_id
```python
# 查询1000个alpha_id
alphas = await fetch_alpha_by_ids(
    large_alpha_list,  # 1000个ID
    batch_size=50,     # 每批50个
    max_retries=5      # 失败重试5次
)
```

### 3. 错误处理
```python
# 查询失败的alpha会自动重试
# 最终仍失败的会记录在输出中
alphas = await fetch_alpha_by_ids(alpha_ids)

# 检查成功率
success_rate = len(alphas) / len(alpha_ids)
if success_rate < 0.9:
    print("⚠ 成功率低于90%,部分alpha查询失败")
```

## 性能考虑

### 分页查询
- **优点**: 可获取大量alpha,避免单次查询超时
- **缺点**: 查询时间较长(每页约1-2秒)
- **建议**: 大量数据时使用,小数据量用单页

### 批量查询
- **优点**: 并行查询,失败自动重试
- **缺点**: 批次间无法并发(顺序执行)
- **建议**: alpha_id数量>50时使用批量查询

## 故障排除

### Q: 为什么获取数量少于预期?
A: 可能原因:
1. 达到`max_pages`限制
2. 平台限流
3. 符合条件的alpha不足

**解决**: 增加`max_pages`或`page_size`

### Q: 批量查询失败率高?
A: 可能原因:
1. alpha_id不存在
2. 平台响应慢
3. 网络问题

**解决**: 增加`max_retries`,减小`batch_size`

### Q: 如何知道分页进度?
A: 函数会打印进度:
```
第1页: 获取100个, 累计100个
第2页: 获取100个, 累计200个
...
```

## 示例代码

完整示例: `examples/pagination_examples.py`

```bash
python3 examples/pagination_examples.py
```

## 总结

改进内容:
- ✅ 添加分页逻辑(`page_size`, `max_pages`, `enable_pagination`)
- ✅ 添加批量查询(`batch_size`, `max_retries`)
- ✅ 进度显示
- ✅ 失败重试机制
- ✅ 完整示例

现在可以获取任意数量的alpha!