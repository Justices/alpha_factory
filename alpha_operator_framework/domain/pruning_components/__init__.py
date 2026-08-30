"""Canonical pruning APIs, organized by concern."""

from .canonical import ast_canonical_prune
from .correlation import (
    CorrelationPruneConfig,
    MultiChannelCorrelationConfig,
    correlation_prune,
    flat_pnl_reason,
    multi_channel_correlation_prune,
)
from .field_topk import FieldTopKConfig, extract_field_ids, extract_fields, field_topk_prune
from .sandbox import sandbox_prefilter
from .self_correlation import LocalCheckConfig, compute_self_correlation, local_sc_precheck
from .semantic import SemanticPruneConfig, classify_field, semantic_prune_fields

__all__ = [
    "CorrelationPruneConfig", "MultiChannelCorrelationConfig", "FieldTopKConfig", "LocalCheckConfig", "SemanticPruneConfig",
    "ast_canonical_prune", "classify_field", "compute_self_correlation", "correlation_prune",
    "extract_field_ids", "extract_fields", "field_topk_prune", "local_sc_precheck",
    "flat_pnl_reason", "multi_channel_correlation_prune", "sandbox_prefilter", "semantic_prune_fields",
]
