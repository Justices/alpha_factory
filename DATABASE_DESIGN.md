# Alpha 研究主数据库架构与设计规范 (Database Design Document)

本文档定义 **Alpha Factor Operator Framework** 主数据库 [`data/alpha_research.db`](file:///d:/quant/alpha_factory/data/alpha_research.db) 的全量核心数据表/视图结构、索引规划、关联模型、并发调优与运维指南。

---

## 一、 数据库定位与并发控制

### 1.1 存储引擎与架构定位
- **SQLite 3.37+**：以单文件形式存储在 `data/alpha_research.db`，轻量、零维护、便携且具备强 ACID 事务保障。
- **单一事实来源 (Single Source of Truth)**：承载全生命周期的 AST 表达式基因、平台回测绩效、18 项 Checks 审计、事件溯源流、试验账本、统一构造策略与自进化知识库。
- **表结构体系**：包含 **24 张核心业务与谱系表** 以及 **5 张事件溯源与快照运行时表**（共 29 张表）。

### 1.2 高性能与 Windows 并发保障机制
针对 Windows 环境下多进程/多线程写入与锁争用，系统底层连接管理器内置如下优化：
1. **WAL 模式 (`PRAGMA journal_mode = WAL`)**：读写互不阻塞，读操作不持有排它锁；
2. **安全同步 (`PRAGMA synchronous = NORMAL`)**：大幅降低磁盘 I/O 延迟同时保证断电数据一致性；
3. **繁忙等待重试 (`PRAGMA busy_timeout = 30000`)**：设置 30 秒锁等待重试，消除 `sqlite3.OperationalError: database is locked`；
4. **幂等 DDL 守卫**：启动时检测关键表是否存在，若已初始化则直接跳过 `CREATE TABLE` / `ALTER TABLE`，杜绝重复 DDL 锁表。

### 1.3 数据库代码库零提交策略 (Zero-Commit Policy)
- **Git 忽略规范**：二进制数据库文件（`*.db`, `*.db-wal`, `*.db-shm`, `data/*.db`）严格加入 `.gitignore`，严禁提交至 Git 仓库，保证代码库纯净轻量；
- **一键初始化与校验工具**：
  ```bash
  python init_db.py           # 默认在本地初始化或增量更新 data/alpha_research.db
  python init_db.py --verify  # 校验当前数据库完整性与已应用的 Schema 版本
  python init_db.py --reset   # 清空并全新初始化数据库 (重新填充 30+ 模板种子)
  # 或通过统一 CLI:
  python alpha_machine.py init-db --verify
  ```

### 1.4 数据库智能清理与物理空间彻底释放 (VACUUM)
系统提供细粒度清理工具，支持淘汰项清除、全量重置与 SQLite 空间物理回收：
- **常用清理指令**：
  ```bash
  python clean_db.py                  # 清理失败/异常任务并执行 VACUUM 释放空间 (默认)
  python clean_db.py --mode stale     # 清理失败项、被剪枝项与孤儿数据
  python clean_db.py --mode all_data  # 清空所有历史回测数据 (保留表结构与模板库)
  python clean_db.py --mode stale --dry-run  # 仅预览预计清理条目数，不实际删除
  # 或通过统一 CLI:
  python alpha_machine.py clean-db --mode stale
  ```

### 1.5 全局数据库配置中心与存储解耦
系统通过 `alpha_operator_framework/database/config.py` 实现了全局数据库配置中心：
- **统一单例与默认路径**：默认指向 `data/alpha_research.db`，所有模块（Repository、EventStore、TrialLedger、CLI）统一通过 `get_database_path()` / `get_database_config()` 获取；
- **环境变量一键覆盖**：
  - `ALPHA_DATABASE_PATH`: 自定义 SQLite 数据库文件绝对/相对路径；
  - `ALPHA_DATABASE_URL`: 标准数据库连接 URL（支持 `sqlite:///`、`mysql://`、`postgresql://`）。
- **极高内聚与低耦合封装**：所有数据库连接管理、驱动适配、SQL 语句与事务提交 100% 封装在 `alpha_operator_framework/database/` 模块内部。上层领域与应用层完全不直接接触原生 SQL。

---

## 二、 实体关系图 (Entity Relationship Diagram)

```mermaid
erDiagram
    construction_tasks ||--o{ construction_strategy_runs : "1 : N (task_id)"
    construction_tasks ||--o{ candidate_provenance : "1 : N (scope_hash)"
    alpha_expressions ||--o{ candidate_provenance : "1 : N (candidate_sha)"
    alpha_expressions ||--o{ alpha_details : "1 : N (expression_sha)"
    alpha_details ||--o{ alpha_checks : "1 : 18 (alpha_id)"
    simulation_batches ||--o{ simulation_results : "1 : N (batch_id)"
    template_library ||--o{ template_prune_rules : "模式关联"
    template_library ||--o{ candidate_provenance : "template_id"

    construction_tasks {
        INTEGER id PK "自增主键"
        TEXT task_id UK "任务唯一ID"
        TEXT scope_hash "探索范围哈希"
        TEXT plan_json "构造方案配置 JSON"
        INTEGER seed "随机种子"
        TEXT status "状态"
        TEXT error_message "错误信息"
        TEXT created_at "创建时间"
        TEXT updated_at "更新时间"
    }

    candidate_provenance {
        INTEGER id PK "自增主键"
        TEXT provenance_id UK "来源指纹"
        TEXT scope_hash "范围哈希"
        TEXT candidate_sha "候选 SHA256"
        TEXT strategy_id "生成策略 ID"
        TEXT strategy_kind "策略类型"
        INTEGER strategy_priority "优先级"
        TEXT leaf_family "叶子族群"
        TEXT template_id "模板 ID"
        TEXT hypothesis_id "假说 ID"
        TEXT parent_shas_json "父因子 SHA 列表"
        INTEGER order_depth "算子嵌套深度"
        INTEGER field_count "去重原始字段数"
        INTEGER seed "随机种子"
        TEXT created_at "创建时间"
    }

    alpha_expressions {
        INTEGER id PK "自增主键"
        TEXT alpha_sha UK "表达式 SHA256 指纹"
        TEXT expression "规范 AST 表达式字符串"
        TEXT expression_origin "生成来源标记"
        TEXT settings "回测环境设置 JSON"
        INTEGER batch_id "关联批次 ID"
        TEXT fields "依赖字段列表 JSON"
        TEXT status "状态"
        TEXT pruning_status "剪枝状态"
        TEXT first_operator "顶层操作符名称"
        TEXT created_at "录入时间"
    }

    alpha_details {
        INTEGER id PK "自增主键"
        TEXT alpha_id UK "平台分配唯一 ID"
        TEXT alpha_sha "关联表达式 SHA256"
        TEXT expression "实际回测表达式"
        TEXT region "市场区域"
        TEXT universe "股票宇宙"
        REAL sharpe "IS 夏普比率"
        REAL fitness "因子健康度 Fitness"
        REAL turnover "日均换手率"
        REAL margin "利润率 Margin"
        REAL returns "年化收益率"
        REAL drawdown "最大回撤"
        TEXT wf_stage "工作流阶段"
        TEXT created_at "回测入库时间"
    }

    template_library {
        INTEGER id PK "自增主键"
        TEXT name UK "模板唯一名称 (含 evolved_hash)"
        TEXT title "模板标题"
        TEXT family "所属族群"
        TEXT template_type "模板类型"
        TEXT expression_template "带槽位抽象公式"
        TEXT example_expression "首个成功示例"
        TEXT source_json "来源任务/演化证据"
        INTEGER fields_per_alpha "字段数"
        INTEGER active "是否激活"
    }

    trial_ledger {
        INTEGER id PK "自增序列"
        TEXT trial_id UK "试验编号"
        TEXT expression "测试表达式"
        TEXT family "所属模板族"
        TEXT region "市场区域"
        TEXT universe "股票宇宙"
        TEXT metrics_json "实测绩效指标 JSON"
        TEXT created_at "记录时间"
    }
```

---

## 三、 核心数据表分类清单 (24 + 5 Tables)

### 3.1 统一构造策略与多源谱系表 (Unified Construction & Lineage)
1. **`construction_tasks`**: 统一构造任务元数据、`scope_hash`、完整 `plan_json` 与种子记录；
2. **`construction_strategy_runs`**: 记录各策略实例（`database_template`, `depth_construction`, `field_composition`, `literature_llm`）的生成状态与产出计数；
3. **`candidate_provenance`**: 记录候选因子的确定性多源谱系（`strategy_id`、`leaf_family`、`order_depth`、`field_count`、`parent_shas_json` 等）；
4. **`construction_lineage`**: 广义算子变换血缘追踪（`parent_alpha_sha` $\to$ `child_alpha_sha`，记录 `transform_kind` 与 `strategy_id`）；
5. **`construction_parent_runs`**: 记录合格父因子在各策略下的派生与衍生状态；
6. **`optimization_lineage`**: 记录迭代优化过程中的父子因子演进关系。

### 3.2 探索轮次与批次调度表 (Exploration & Batches)
7. **`round_candidates`**: 记录研究轮次候选因子池、打分构成与选择状态；
8. **`simulation_batches`**: 向 BRAIN 平台提交的多仿真批次元数据、状态与进度跟踪；
9. **`simulation_results`**: 批次中各个子任务的执行明细、平台子 URL 与关联 `alpha_id`。

### 3.3 表达式、绩效与审计表 (Expressions & Backtests)
10. **`alpha_expressions`**: 存储所有经过 AST 编译器规范化的候选表达式、哈希指纹、依赖字段列表与状态；
11. **`alpha_details`**: 记录从平台获取的真实回测指标（Sharpe, Fitness, Turnover, Margin, PnL, Returns, Drawdown, Long/Short Count 等）；
12. **`alpha_checks`**: 记录每个 Alpha 的 18 项平台硬性 Checks（如 LOW_SHARPE, LOW_FITNESS, HIGH_TURNOVER 等）详细数值与审计结论。

### 3.4 准入、优化与金字塔提交表 (Admission & Submission)
13. **`alpha_submission_candidates`**: 记录符合 6 维硬门禁、准备上报平台的金字塔待提交候选；
14. **`alpha_optimization_queue`**: 记录接近达标但需微调（如换手偏高、衰减需调整）的因子优化队列；
15. **`super_alpha_candidates`**: 记录通过 Gram-Schmidt 正交化与 HRP 算法生成的超级组合因子候选。

### 3.5 知识库、统计信号与剪枝表 (Knowledge Base & Distillation)
16. **`template_library`**: 模板库（单一可信源，支撑从胜出因子到可复用模板的闭环晋升）；
17. **`template_prune_rules`**: 2D 跨字段共识剪枝规则库，记录多字段连续失败的模板模式；
18. **`result_prune_rules`**: 局部范围内的失败模式剪枝规则；
19. **`datafields`**: 目标市场所有可用特征字段的元数据与覆盖率缓存；
20. **`field_signal_stats`**: 统计各原子字段在历史回测中的有效信号数、夏普与命中率；
21. **`pair_signal_stats`**: 统计字段对的协同信号表现；
22. **`operator_signal_stats`**: 统计各顶层算子的实测有效率；
23. **`backtest_dataset_records`**: 记录各市场/宇宙下数据集的回测覆盖足迹。

### 3.6 试验账本与事件溯源运行时表 (Overfitting Defense & Event Runtime)
24. **`trial_ledger`**: 持久化试验账本，记录所有回测与剪枝尝试，为 DSR/PSR/PBO 统计防过拟合提供多重检验基础；
25. **`event_log`**: 事件溯源不可变事实流，记录全生命周期所有状态流转事件；
26. **`knowledge_snapshot`**: 知识聚合根的持久化快照；
27. **`submission_outbox`**: 幂等 Saga 模式平台提交外箱，保障网络中断或崩溃后断点续传；
28. **`research_round_snapshot`**: 探索轮次聚合根快照；
29. **`experiment_batch_snapshot`**: 实验批次聚合根快照。

---

## 四、 常用分析 SQL 查询速查

### 1. 查询 IS 夏普最高的前 10 个 Alpha
```sql
SELECT alpha_id, expression, sharpe, fitness, turnover, returns, drawdown, wf_stage
FROM alpha_details
ORDER BY sharpe DESC
LIMIT 10;
```

### 2. 查询各生成策略 (Strategy) 与叶子族的候选产出与胜率
```sql
SELECT p.strategy_id, p.leaf_family, COUNT(DISTINCT p.candidate_sha) AS total_candidates,
       AVG(d.sharpe) AS avg_sharpe, MAX(d.sharpe) AS max_sharpe
FROM candidate_provenance p
LEFT JOIN alpha_details d ON p.candidate_sha = d.alpha_sha
GROUP BY p.strategy_id, p.leaf_family
ORDER BY total_candidates DESC;
```

### 3. 查询模板库中晋升的自进化模板及其来源证据
```sql
SELECT name, title, family, expression_template, source_json, active, created_at
FROM template_library
WHERE name LIKE 'evolved_%'
ORDER BY id DESC;
```

### 4. 查看指定 Alpha 的 18 项 Checks 详细状态
```sql
SELECT check_name, result, value, "limit"
FROM alpha_checks
WHERE alpha_id = 'ALPHA_12345'
ORDER BY result ASC;
```

