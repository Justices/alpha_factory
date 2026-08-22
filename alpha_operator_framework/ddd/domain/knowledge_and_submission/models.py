"""Knowledge and Submission Bounded Context - Domain Models & Aggregate Roots."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class SignalDistillationEvidence:
    """Evidence of a generalized template skeleton derived from winning alphas."""
    template_name: str
    expression_template: str
    source_expressions: List[str]
    distinct_fields_count: int
    avg_sharpe: float
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass(frozen=True)
class PruneRuleEvidence:
    """Immutable evidence for structural pattern pruning."""
    pattern: str
    pattern_type: str  # prefix | substring | regex
    reason: str
    failure_rate: float
    sample_n: int


@dataclass(frozen=True)
class SelectionFeedback:
    """Feedback deltas exported to candidate exploration and field research."""
    field_weight_deltas: Dict[str, float]
    family_weight_deltas: Dict[str, float]
    new_templates: List[SignalDistillationEvidence]
    new_prune_rules: List[PruneRuleEvidence]


@dataclass(frozen=True)
class SubmissionApprovalRecord:
    """Fail-closed audit record of submission eligibility validation."""
    is_approved: bool
    approval_timestamp: str
    gate_checks: Dict[str, bool]
    rejection_reason: str = ""


@dataclass
class SubmissionCase:
    """Aggregate Root: Owns the platform submission lifecycle for an approved alpha."""
    case_id: str
    candidate_id: str
    alpha_id: str
    expression: str
    approval_record: Optional[SubmissionApprovalRecord] = None
    status: str = "DRAFT"  # DRAFT | APPROVED | SUBMITTED | REJECTED
    platform_submission_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def approve(self, approval: SubmissionApprovalRecord) -> None:
        if approval.is_approved:
            self.approval_record = approval
            self.status = "APPROVED"
        else:
            self.approval_record = approval
            self.status = "REJECTED"

    def record_submission(self, platform_sub_id: str) -> None:
        if self.status != "APPROVED":
            raise ValueError("Cannot submit an unapproved SubmissionCase!")
        self.platform_submission_id = platform_sub_id
        self.status = "SUBMITTED"


@dataclass
class KnowledgeBase:
    """Aggregate Root: Accumulates learned template skeletons, field/operator evidence, and prune rules."""
    templates: Dict[str, SignalDistillationEvidence] = field(default_factory=dict)
    prune_rules: Dict[str, PruneRuleEvidence] = field(default_factory=dict)
    field_signals: Dict[str, Dict[str, float]] = field(default_factory=dict)
    version: int = 1
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def register_template(self, evidence: SignalDistillationEvidence) -> None:
        self.templates[evidence.template_name] = evidence
        self.version += 1

    def register_prune_rule(self, rule: PruneRuleEvidence) -> None:
        self.prune_rules[rule.pattern] = rule
        self.version += 1
