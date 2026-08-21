# Alpha Factory 文档全景索引与导航 (Documentation Index)

欢迎查阅 **Alpha Factory**（基于事件溯源内核与领域驱动设计的 WorldQuant BRAIN 全生命周期量化 Alpha 投研工业级框架）文档库。

---

## 🧭 文档全景导航与受众导读

```mermaid
mindmap
  root((Alpha Factory 文档体系))
    根目录核心入口
      README.md["项目概览 & 架构总览"]
      QUICKSTART.md["5分钟极速上手 & 命令速查"]
      ARCHITECTURE.md["系统架构 & 证据边界 & 防过拟合"]
      USAGE_GUIDE.md["完整使用指南 & CLI 权威手册"]
      DATABASE_DESIGN.md["数据库全景 & 17 表/视图规范"]
    架构与底层设计 docs/architecture
      event_sourced_core.md["事件溯源内核与 Outbox 规范"]
      strategy_architecture.md["生成策略模块架构设计"]
      directory_design.md["代码分层目录规范"]
      roadmap_and_evolution.md["演进与技术路线图"]
    功能与专项指南 docs/guides
      ai_integration.md["AI Agent / Python API 自动化集成"]
      alpha_filtering.md["因子多维筛选与优化队列管理"]
      alpha_source_guide.md["因子来源分析与分类体系"]
      pagination_guide.md["平台分页拉取与元数据流"]
      platform_config.md["BRAIN 平台认证与参数配置"]
      strategy_usage.md["策略模块使用手册"]
    审计与历史评估 docs/assessments
      PROJECT_ASSESSMENT_2026-08-21.md["第一阶段评估报告"]
      REASSESSMENT_2026-08-21.md["第二阶段复评与改进要求"]
      PRODUCTION_READINESS_2026-08-21.md["生产就绪性复核与处置清单"]
      code_cleanup_summary.md["代码与架构清理总结"]
      improvement_summary.md["核心能力增强总结"]
      project_summary.md["项目里程碑总结"]
      strategy_summary.md["策略体系总结"]
```

---

## 📌 核心文档分类速览

### 1. 根目录主文档 (Core Entrypoints)

| 文档 | 定位与核心内容 | 适用对象 |
| :--- | :--- | :--- |
| [**README.md**](file:///d:/quant/alpha_factory/README.md) | 项目简介、系统架构大图、核心能力亮点、环境要求与快速运行。 | 全体量化开发者 / AI Agent |
| [**QUICKSTART.md**](file:///d:/quant/alpha_factory/QUICKSTART.md) | 5 分钟极速上手、常用单行 CLI 命令备忘、Python API 极简调用示例。 | 新人入门 / 常用操作速查 |
| [**ARCHITECTURE.md**](file:///d:/quant/alpha_factory/ARCHITECTURE.md) | 系统分层模型、事件溯源内核（8 大模块）、证据等级边界、5 层防御评级体系、防过拟合（DSR/PSR/PBO）。 | 架构师 / 核心开发人员 |
| [**USAGE_GUIDE.md**](file:///d:/quant/alpha_factory/USAGE_GUIDE.md) | 研报提炼、分层地毯式挖掘、A/B 分支科学对照、数据库运维与空间释放等全量命令与参数详解。 | 日常投研人员 / 运维人员 |
| [**DATABASE_DESIGN.md**](file:///d:/quant/alpha_factory/DATABASE_DESIGN.md) | SQLite `data/alpha_research.db` 17 张核心表/视图设计、索引规划、Zero-Commit 规范、`init-db` 与 `clean-db` 维护。 | 数据库管理员 / 数据工程人员 |

---

### 2. 架构与底层设计 (`docs/architecture/`)

| 文档 | 核心内容 |
| :--- | :--- |
| [**event_sourced_core.md**](file:///d:/quant/alpha_factory/docs/architecture/event_sourced_core.md) | 事件溯源研究内核深度规范：不可变事件事实、CAS 乐观锁、Outbox Saga 模式、物化视图投影与 A/B 分支比较。 |
| [**strategy_architecture.md**](file:///d:/quant/alpha_factory/docs/architecture/strategy_architecture.md) | 因子生成策略分层架构设计（Template 抽象、算子组合、组合生成器）。 |
| [**directory_design.md**](file:///d:/quant/alpha_factory/docs/architecture/directory_design.md) | 代码库分层目录设计规范与包隔离准则。 |
| [**roadmap_and_evolution.md**](file:///d:/quant/alpha_factory/docs/architecture/roadmap_and_evolution.md) | 平台演进历史、自进化机制与未来路线图。 |

---

### 3. 功能与专项指南 (`docs/guides/`)

| [**production_deployment_guide.md**](file:///d:/quant/alpha_factory/docs/guides/production_deployment_guide.md) | **生产环境部署与高可用运维手册**: Systemd 守护进程、Crontab 定时矩阵巡检、容灾恢复与零数据丢失保障。 |
| [**autonomous_evolution_guide.md**](file:///d:/quant/alpha_factory/docs/guides/autonomous_evolution_guide.md) | **全自主进化与高阶因子挖掘实战指南**: 符号语法树自由杂交、大模型自反思、模板自动蒸馏与知识库闭环。 |
| [**ai_integration.md**](file:///d:/quant/alpha_factory/docs/guides/ai_integration.md) | 面向大模型与自主 Agent 的结构化 API 接口、参数控制与异步调用范式。 |
| [**alpha_filtering.md**](file:///d:/quant/alpha_factory/docs/guides/alpha_filtering.md) | 候选 Alpha 多维条件过滤、高质量/边缘池筛选与优化队列分派。 |
| [**alpha_source_guide.md**](file:///d:/quant/alpha_factory/docs/guides/alpha_source_guide.md) | 因子来源溯源体系（研报提取、地毯挖掘、自进化突变、跨市场迁移）。 |
| [**pagination_guide.md**](file:///d:/quant/alpha_factory/docs/guides/pagination_guide.md) | 平台海量数据字段分页拉取、缓存加速与全量元数据持久化。 |
| [**platform_config.md**](file:///d:/quant/alpha_factory/docs/guides/platform_config.md) | BRAIN 平台凭据配置、Cookie 自动化管理与请求限流控制。 |
| [**strategy_usage.md**](file:///d:/quant/alpha_factory/docs/guides/strategy_usage.md) | 常用策略模板的使用方法与参数调优指南。 |

---

### 4. 审计与历史评估报告 (`docs/assessments/`)

| 文档 | 核心内容 |
| :--- | :--- |
| [**PROJECT_ASSESSMENT_2026-08-21.md**](file:///d:/quant/alpha_factory/docs/assessments/PROJECT_ASSESSMENT_2026-08-21.md) | 2026-08-21 第一阶段系统架构与科学性全面评估。 |
| [**REASSESSMENT_2026-08-21.md**](file:///d:/quant/alpha_factory/docs/assessments/REASSESSMENT_2026-08-21.md) | 2026-08-21 第二阶段复评（证据边界防御、Outbox 恢复、真实批处理）。 |
| [**PRODUCTION_READINESS_2026-08-21.md**](file:///d:/quant/alpha_factory/docs/assessments/PRODUCTION_READINESS_2026-08-21.md) | 2026-08-21 生产运行就绪性复核与真实平台故障处置清单。 |
| [**code_cleanup_summary.md**](file:///d:/quant/alpha_factory/docs/assessments/code_cleanup_summary.md) | 模块瘦身、冗余代码清理与工程规范化记录。 |
| [**improvement_summary.md**](file:///d:/quant/alpha_factory/docs/assessments/improvement_summary.md) | 核心算法演进与系统效能提升历史总结。 |
| [**project_summary.md**](file:///d:/quant/alpha_factory/docs/assessments/project_summary.md) | 项目阶段里程碑成果汇总。 |
| [**strategy_summary.md**](file:///d:/quant/alpha_factory/docs/assessments/strategy_summary.md) | 模板族策略覆盖度与有效性统计分析。 |
