# 目录与模块调整方案（深化设计后）

> 背景：把散落的因子挖掘能力，重构为「字段选择 → 表达式合成 → 批量回测 → 信号优化 → 提交 → 沉淀与抽象」的**研究闭环**。
> 本文给出目标目录分层、现状映射与渐进迁移路径。

## 一、设计原则

1. **按职责分层，不按流程步骤分**。一个模块可能被多步复用（如 `pruning` 同时服务于字段选择和信号优化），所以按「领域 / 生成 / 平台 / 蒸馏 / 编排」分层，而非「第1步/第2步」。
2. **纯函数与网络隔离**。领域层（字段/算子/模板/密度/剪枝/评价/优化）零网络访问；平台交互集中在 `platform/`。
3. **稳定 API 不破**。`alpha_operator_framework/__init__.py` 持续 re-export，旧的 `from alpha_operator_framework import X` 全部兼容，目录搬迁不影响下游。
4. **沉淀可回放**。蒸馏层产物带 `round` / `source_expression_sha` / 时间戳。

## 二、目标目录结构

```
alpha_factory/
├── alpha_machine.py                    # 平台回测入口 (brain_client 单例) —— 稳定，不动
│
├── alpha_operator_framework/           # 核心包
│   ├── __init__.py                     # 稳定 API：统一 re-export（兼容旧 import）
│   │
│   ├── domain/                         # 领域层（纯函数，无网络）
│   │   ├── fields.py                   #   字段建模 + 采样          (第1步)
│   │   ├── economic_rules.py           #   字段经济可采性规则       (第1步)
│   │   ├── operators.py                #   算子库                  (第2步)
│   │   ├── families.py                 #   模板族 1/2/3/4 元       (第2步)
│   │   ├── semantic_pairs.py           #   语义配对                (第2步)
│   │   ├── paired_bases.py             #   配对基准                (第2步)
│   │   ├── density.py                  #   密度/信号门评估         (第4步)
│   │   ├── pruning.py                  #   三阶段剪枝              (第1/4步)
│   │   ├── evaluation.py               #   Alpha 评价/Failed Gate  (第4/5步)
│   │   └── optimize.py                 #   筛选                    (第4步)
│   │
│   ├── generation/                     # 生成层（表达式 → Task）
│   │   ├── creation_strategy.py
│   │   ├── template_library.py         #   模板注册表（沉淀容器）
│   │   └── super_alpha.py              #   Super Alpha 构建        (第4步)
│   │
│   ├── platform/                       # 平台交互层（有网络）
│   │   ├── alpha_source.py             #   alpha 获取
│   │   ├── datafield_ingest.py         #   字段采集（节流防429）
│   │   ├── local_fields.py             #   本地字段读取
│   │   ├── platform_config.py
│   │   └── simulation_tracker.py
│   │
│   ├── distill/                        # 蒸馏层（新增，闭环核心）★ 本轮已落地
│   │   ├── field_signals.py            #   字段级信号聚合 + 加权采样 (第6→1)
│   │   └── template_abstractor.py      #   模板骨架抽象             (第6→2)
│   │
│   ├── database/                       # 数据访问层（已存在，保留）
│   ├── cache/                          # 平台元数据缓存（已存在，保留）
│   ├── strategies/                     # 策略组件（已存在，保留）
│   │
│   ├── orchestrator.py                 # CLI 三段工作流 (survey/deepen/submit)
│   ├── ai_workflow.py                  # run_full_workflow 单次全流程
│   └── loop.py                         # 研究闭环编排（新增）★ 本轮已落地
│
├── cnhkmcp/                            # 平台连接器（本地，不动）
├── data/                               # 数据资产
├── docs/                               # 文档（本文件 + architecture 等）
├── examples/                           # 示例脚本
├── runs/                               # 运行输出
├── tests/                              # 测试
└── tools/                              # 辅助脚本
```

## 三、现状 → 目标映射

| 现状（扁平，38 个 .py） | 目标归属 | 搬迁方式 |
|------------------------|----------|----------|
| fields / economic_rules / operators / families / semantic_pairs / paired_bases / density / pruning / evaluation / optimize | `domain/` | 移动 + 相对 import 改写 |
| creation_strategy / template_library / super_alpha | `generation/` | 移动 + 相对 import 改写 |
| alpha_source / datafield_ingest / local_fields / platform_config / simulation_tracker | `platform/` | 移动 + 相对 import 改写 |
| **distill/field_signals.py（新增）** | `distill/` | ✅ 已落地 |
| **distill/template_abstractor.py（新增）** | `distill/` | ✅ 已落地 |
| **loop.py（新增）** | 顶层 | ✅ 已落地 |
| database / cache / strategies | 原位保留 | 不动 |
| orchestrator / ai_workflow | 顶层 | 不动 |

## 四、迁移执行（已完成，设计期一次性清理）

按老刘要求「设计期不考虑兼容、直接清理」，本次为**一次性推倒重来**，不留兼容层：

1. 18 个扁平模块按映射搬入 `domain/`（10）、`generation/`（3）、`platform/`（5）。
2. 全部相对 import 统一改为绝对 import（`from alpha_operator_framework.<层>.<模块>`），消除跨层反向依赖（`platform → ai_workflow` 的 `filter_*` 便捷函数下沉到 `domain/optimize.py`）。
3. 顶层 `__init__.py` 从新路径 re-export，公共 API 不变。
4. 外部引用（`alpha_machine.py`、`examples/`、`tests/`）同步改写。
5. 验证：包导入 OK、`alpha_machine` 导入 OK、离线测试全绿、`demo_workflow` 跑通。

## 五、本轮已落地（P0 沉淀回流 + 目录重构）

| 产物 | 说明 |
|------|------|
| `distill/field_signals.py` | `aggregate_field_signals`（按字段聚合信号命中率）+ `weighted_field_sample`（hit_rate 加权采样） |
| `distill/template_abstractor.py` | `abstract_template` / `abstract_templates`（达标表达式 → 模板骨架，按 support 去重） |
| `database/schema/008_field_signal_stats.sql` | 字段信号统计表（版本化留档） |
| `database/repository.py` | `upsert_field_signal_stats`（支持 accumulate 累积）+ `get_field_signal_stats` |
| `loop.py` | `LoopConfig` + `run_research_loop` + `distill_and_plan_next` + `distill_templates_round`（平台回测接入点留 TODO） |
| `tests/test_distill.py` | 12 项离线测试，全绿 |
| `latest_schema.sql` | 已同步 field_signal_stats 快照 |
| `domain/` `generation/` `platform/` | 目录重构完成，18 模块归位 |
| `distill/template_abstractor.py` | `to_template` + `distill_templates_into_library`（P1：达标表达式 → 骨架 → 回填 `template_library`） |

## 六、后续路线

- ~~**P1（模板抽象回流闭环）**~~ ✅ 已完成：`distill_templates_into_library` 把达标表达式抽象回填 `template_library`（family=`distilled`，name=`distilled_<sha12>` 幂等），`template_creation_strategy` 用 `families=("distilled",)` 即可消费。
- **P2（多轮编排）**：`loop._run_round_survey` 接入 `run_full_workflow` / `alpha_machine`，跑通多轮「回测→沉淀→加权采样」真实闭环。
