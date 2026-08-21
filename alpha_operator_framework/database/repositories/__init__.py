"""领域专属仓储模块 (Domain Repositories).

导出各个高内聚领域专用仓储：
  - AlphaRepository: 因子表达式主数据、平台 18 Checks、IS 绩效与分层采样
  - SimulationRepository: 仿真批次、回测明细与 PnL 相关性
  - DatafieldRepository: 数据字段元数据与单字段/配对信号自学习统计
  - TemplateRepository: 模板库管理、自进化淘汰规则
  - QueueRepository: 优化任务队列、提交候选池与 SuperAlpha 组合
  - EventLedgerRepository: 只追加事件日志流与多重检验试验账本
"""

from .alpha import AlphaRepository
from .simulation import SimulationRepository
from .datafield import DatafieldRepository
from .template import TemplateRepository
from .queue import QueueRepository
from .event_ledger import EventLedgerRepository

__all__ = [
    "AlphaRepository",
    "SimulationRepository",
    "DatafieldRepository",
    "TemplateRepository",
    "QueueRepository",
    "EventLedgerRepository",
]
