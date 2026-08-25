"""Backward-compatible public Alpha repository composition."""

from __future__ import annotations

from .alpha_analytics import AlphaAnalyticsMixin
from .alpha_checks import AlphaChecksMixin
from .alpha_query import AlphaQueryMixin
from .alpha_write import AlphaWriteMixin


class AlphaRepository(
    AlphaWriteMixin,
    AlphaQueryMixin,
    AlphaChecksMixin,
    AlphaAnalyticsMixin,
):
    """Alpha 表达式、回测指标与 18 项 Checks 仓储."""

