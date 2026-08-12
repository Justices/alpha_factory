# Alpha数据库设计文档

## 数据库选择

**SQLite** - 轻量级、无服务器、单文件存储，适合本地研究和单用户场景。

## 表结构设计

### 表1: alpha_expressions (Alpha表达式表)

**用途**: 存储alpha表达式，基于expression_sha去重。

**字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 自增主键 |
| `expression_sha` | TEXT | 表达式SHA256哈希，唯一索引 |
| `expression` | TEXT | alpha表达式 |
| `expression_origin` | TEXT | `unary_template` / `first_order` / `semantic_pair` 等生成来源 |
| `settings` | TEXT | 回测设置JSON |
| `created_at` | TEXT | 创建时间(ISO格式) |
| `updated_at` | TEXT | 更新时间 |

**示例**:
```sql
INSERT INTO alpha_expressions (expression_sha, expression, settings, created_at, updated_at)
VALUES (
    'sha256...',
    'group_neutralize(ts_rank(rank(close)/rank(volume), 10), industry)',
    '{"region":"EUR","universe":"TOP2500",...}',
    '2025-07-29T10:30:00',
    '2025-07-29T10:30:00'
);
```

**关键特性**:
- `expression_sha` 唯一索引，避免重复存储相同表达式
- `settings` JSON存储回测设置
- 插入时自动计算SHA并去重

---

### 表2: alpha_details (当前回测状态表)

`alpha_details` 是本项目唯一的回测结果表。每个 `alpha_id` 使用 upsert
保存最新回测状态；项目不保存重复回测历史。

---

### 表3: alpha_details (Alpha详情表)

**用途**: 平铺所有字段，便于查询和分析。

**字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 自增主键 |
| `alpha_id` | TEXT | 平台alpha_id，唯一索引 |
| `expression_sha` | TEXT | 表达式哈希 |
| `expression` | TEXT | 表达式 |
| **回测设置** | | |
| `region` | TEXT | 地区 |
| `universe` | TEXT | 股票池 |
| `delay` | INTEGER | 延迟 |
| `decay` | REAL | Decay |
| `neutralization` | TEXT | 中性化方法 |
| `truncation` | REAL | 截断值 |
| **回测指标** | | |
| `sharpe` | REAL | Sharpe |
| `fitness` | REAL | Fitness |
| `turnover` | REAL | Turnover |
| `margin` | REAL | Margin |
| `pnl` | REAL | PnL |
| `returns` | REAL | Returns |
| `drawdown` | REAL | Drawdown |
| `long_count` | INTEGER | Long数量 |
| `short_count` | INTEGER | Short数量 |
| **平台信息** | | |
| `grade` | TEXT | 等级(INFERIOR/AVERAGE) |
| `stage_platform` | TEXT | 平台阶段(IS/OS) |
| `status_platform` | TEXT | 平台状态(UNSUBMITTED) |
| **提交检查指标** | | |
| `sc_result` | TEXT | SELF_CORRELATION 结果(PASS/FAIL/WARNING/ERROR/PENDING) |
| `sc_value` | REAL | self-correlation max(标量) |
| `pc_result` | TEXT | PROD_CORRELATION 结果 |
| `pc_value` | REAL | prod-correlation max(标量) |
| `checks_json` | TEXT | 完整 `is.checks` 数组原样 JSON |
| **时间戳** | | |
| `created_at` | TEXT | 创建时间 |
| `updated_at` | TEXT | 更新时间 |

**索引**:
- `alpha_id` (唯一)
- `expression_sha`
- `sharpe` (支持排序查询)
- `fitness` (支持排序查询)
- `stage_platform`

**示例**:
```sql
INSERT INTO alpha_details (alpha_id, expression_sha, expression, region, universe, ..., sharpe, fitness, ...)
VALUES (
    'alpha_001',
    'sha256...',
    'ts_rank(close, 22)',
    'EUR',
    'TOP2500',
    ...,
    1.85,
    1.45,
    ...
);
```

**关键特性**:
- 平铺结构，便于SQL查询
- 支持Upsert (INSERT ... ON CONFLICT DO UPDATE)
- 所有指标字段可直接查询和排序
- PC/SC 独立列便于快速过滤；完整 checks 存 `alpha_checks` 子表 + `checks_json` 原样
- 旧行(迁移前写入)新列可能为 NULL，查询时用 `or ""` / 容忍 None

---

### 表4: alpha_checks (检查子表)

**用途**: 存平台全部提交检查项(PASS/FAIL/WARNING/ERROR/PENDING)，按 `(alpha_id, check_name)` 唯一。

**背景**: check 集合按地区动态(约18种)，不能硬编码成 `alpha_details` 的列，故拆成子表 1:N。

**字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `alpha_id` | TEXT | 平台alpha_id(联合主键) |
| `check_name` | TEXT | 检查名，如 SELF_CORRELATION |
| `result` | TEXT | PASS/FAIL/WARNING/ERROR/PENDING |
| `limit` | REAL | 阈值(如 0.7) |
| `value` | REAL | 当前值 |
| `extra_json` | TEXT | 额外字段(year/startDate/endDate/pyramids/themes/effective/multiplier 等)JSON |
| `created_at` | TEXT | 创建时间 |
| `updated_at` | TEXT | 更新时间 |

**DDL**:
```sql
CREATE TABLE IF NOT EXISTS alpha_checks (
    alpha_id TEXT NOT NULL,
    check_name TEXT NOT NULL,
    result TEXT,
    "limit" REAL,           -- limit 是SQLite保留字, 需加引号
    value REAL,
    extra_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (alpha_id, check_name)
);
CREATE INDEX IF NOT EXISTS idx_checks_alpha ON alpha_checks(alpha_id);
CREATE INDEX IF NOT EXISTS idx_checks_name ON alpha_checks(check_name);
```

**check 名枚举**(按地区动态，以下为常见项):
- `SELF_CORRELATION` / `PROD_CORRELATION` — 阈值 0.7，结果存 `alpha_details.sc_result/sc_value/pc_result/pc_value`
- `LOW_SHARPE` / `LOW_FITNESS` / `LOW_TURNOVER` / `HIGH_TURNOVER` / `LOW_MARGIN`
- `IS_LADDER_SHARPE` / `OS_LADDER_SHARPE` — 带 `year/startDate/endDate`
- `MATCHES_PYRAMID` / `MATCHES_THEMES` / `CONCENTRATED_WEIGHT` / `REGIONAL_MARGIN` 等

**写入方式**: 替换式(DELETE + INSERT)，保证子表与平台返回一致。写入由 `save_result_with_checks` 在单事务内完成。

---

## 数据关系

```
alpha_expressions (表达式表)
    ↓ expression_sha
alpha_details (详情表)
    ↓ alpha_id
alpha_checks (检查子表, 1:N)
```

**关系说明**:
1. `alpha_expressions` 存储唯一表达式
2. `alpha_details` 存储每个 alpha 的最新平铺详情(含PC/SC/checks_json)
3. `alpha_checks` 每个alpha的多条提交检查项(1:N)

---

## 使用示例

### 插入表达式

```python
from alpha_operator_framework.database import AlphaDatabase

db = AlphaDatabase("runs/alpha_research.db")

expression = "ts_rank(close, 22)"
settings = {"region": "EUR", "universe": "TOP2500", ...}

expr_id = db.insert_expression(expression, settings)
```

### 保存回测结果

```python
result = {
    "sharpe": 1.85,
    "fitness": 1.45,
    "turnover": 0.05,
    ...
}

db.insert_backtest_result(
    alpha_id="alpha_001",
    expression=expression,
    result=result,
    stage="backtest",
    status="pending"
)
```

### 保存详情

```python
from alpha_operator_framework.database import AlphaDetail

detail = AlphaDetail(
    alpha_id="alpha_001",
    expression_sha=db.compute_sha(expression),
    expression=expression,
    region="EUR",
    universe="TOP2500",
    sharpe=1.85,
    fitness=1.45,
    ...
)

db.insert_alpha_detail(detail)
```

### 查询alpha

```python
# 查询高质量alpha
high_quality = db.query_alphas(
    min_sharpe=1.58,
    min_fitness=1.0,
    limit=50
)

# 查询边缘alpha
marginal = db.query_alphas(
    min_sharpe=1.2,
    max_sharpe=1.8,
    limit=20
)

# 查询特定地区
eur_alphas = db.query_alphas(region="EUR", limit=100)
```

---

## 工作流集成

### Survey阶段

```python
# 1. 插入表达式 + 保存结果 + checks (一次调用)
from alpha_operator_framework.database import persist_workflow_row

db = AlphaDatabase("runs/alpha_research.db")
for row in results:                        # results = simulate 返回的结果行
    persist_workflow_row(db, row, settings, stage="survey", status="pending")
db.close()
```

### Deepen阶段

```python
# 1. 查询候选alpha
candidates = db.query_alphas(min_sharpe=1.2, max_sharpe=1.8)

# 2. 深挖优化
for detail in candidates:
    # 优化逻辑...

    # 3. 更新状态
    db.update_backtest_status(detail.alpha_id, stage="optimize", status="ready")
```

### Submit阶段

```python
# 1. 保存最新结果 + 全部 checks
db.save_result_with_checks(alpha_id, is_block, settings)

# 2. 读回 checks, 判断 SC/PC 是否通过
checks = {c["name"]: c for c in db.get_checks(alpha_id)}
sc = checks.get("SELF_CORRELATION")
pc = checks.get("PROD_CORRELATION")
sc_ok = sc is None or sc.get("result") in ("PASS", "WARNING")
pc_ok = pc is None or pc.get("result") in ("PASS", "WARNING")

# 3. 更新状态
status = "ready" if (sc_ok and pc_ok) else "optimize"
db.update_backtest_status(alpha_id, stage="submit", status=status)
```

### 查询带 PC/SC 的 alpha

```python
# 全部检查通过的 alpha
ready = db.query_alphas(min_sharpe=1.58)
for d in ready:
    if d.sc_result == "PASS" and d.pc_result == "PASS":
        print(f"{d.alpha_id}: SC={d.sc_value} PC={d.pc_value}")
```

---

## 与文件存储对比

| 特性 | 文件存储 | SQLite数据库 |
|------|---------|-------------|
| **查询能力** | 弱(JSON文件) | 强(SQL查询) |
| **去重** | 手动 | 自动(expression_sha) |
| **状态跟踪** | 无 | 有(alpha_details 最新状态) |
| **并发安全** | 否 | 是 |
| **数据完整性** | 弱 | 强(事务) |
| **备份** | 复制文件 | 复制文件 |
| **扩展性** | 有限 | 可扩展表 |

---

## 最佳实践

### 1. 批量导入

```python
# 从CSV导入
count = db.import_from_csv("simulated_alphas.csv")

# 批量插入
for alpha in alphas:
    db.insert_alpha_detail(alpha)
```

### 2. 定期清理

```python
# 清理旧记录
conn.execute("DELETE FROM alpha_details WHERE created_at < ?", (old_date,))
conn.commit()
```

### 3. 备份

```bash
# 备份数据库
cp runs/alpha_research.db runs/alpha_research_backup.db
```

---

## 性能考虑

### 索引优化

已创建的索引:
- `alpha_id` (唯一)
- `expression_sha`
- `sharpe`/`fitness` (排序查询)
- `stage_platform` (过滤查询)

### 批量操作

```python
# 使用事务
conn = db._get_connection()
cursor = conn.cursor()

for i in range(1000):
    cursor.execute("INSERT INTO ...")

conn.commit()  # 批量提交
```

---

## 示例代码

完整示例: `examples/database_examples.py`

运行:
```bash
python3 examples/database_examples.py
```

---

## 总结

数据库设计核心:
- ✅ 表达式去重(expression_sha)
- ✅ 当前状态查询(alpha_details)
- ✅ 平铺查询(alpha_details)
- ✅ 提交检查指标(PC/SC列 + alpha_checks子表 + checks_json)
- ✅ 工作流集成(survey→deepen→submit 均写入数据库)
- ✅ 批量导入支持
