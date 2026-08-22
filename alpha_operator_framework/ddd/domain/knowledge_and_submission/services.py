"""Knowledge and Submission Bounded Context - Domain Services."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Sequence
from .models import (
    KnowledgeBase,
    PruneRuleEvidence,
    SelectionFeedback,
    SignalDistillationEvidence,
    SubmissionApprovalRecord,
    SubmissionCase,
)
from ..experiment_governance.models import NormalizedBacktestResult
from ..experiment_governance.models import PostPruneDecision


class SignalDistiller:
    """Abstracts winning expressions into placeholder skeletons ({a}, {b}) and registers to KnowledgeBase."""

    @staticmethod
    def abstract_to_skeleton(expr: str) -> str:
        # Replace specific feature tokens with {a}, {b}
        tokens = list(set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr)))
        exclude = {
            "rank", "group_rank", "group_neutralize", "group_zscore", "group_scale",
            "ts_scale", "ts_rank", "ts_zscore", "ts_decay_linear", "ts_delta", "ts_mean", "ts_std_dev",
            "subindustry", "industry", "sector", "market", "cap", "winsorize", "ts_backfill",
            "a", "b", "c", "d"
        }
        actual_fields = [t for t in tokens if t not in exclude and not t.isdigit()]

        skel = expr
        placeholders = ["{a}", "{b}", "{c}", "{d}"]
        for idx, f in enumerate(actual_fields[:4]):
            skel = re.sub(rf"\b{f}\b", placeholders[idx], skel)
        return skel

    def distill_winners(
        self,
        winners: Sequence[NormalizedBacktestResult],
        knowledge_base: KnowledgeBase,
    ) -> List[SignalDistillationEvidence]:
        new_evidences: List[SignalDistillationEvidence] = []
        for idx, w in enumerate(winners):
            skel = self.abstract_to_skeleton(w.expression)
            name = f"evolved_template_{hash(skel) & 0xfffffff}"
            ev = SignalDistillationEvidence(
                template_name=name,
                expression_template=skel,
                source_expressions=[w.expression],
                distinct_fields_count=1,
                avg_sharpe=w.sharpe,
            )
            knowledge_base.register_template(ev)
            new_evidences.append(ev)

        return new_evidences


class SelectionFeedbackBuilder:
    """Builds feedback deltas from a finished batch to guide the next exploration round."""

    def build_feedback(
        self,
        results: Sequence[NormalizedBacktestResult],
        distilled_templates: List[SignalDistillationEvidence],
        post_prunes: Sequence[PostPruneDecision] = (),
    ) -> SelectionFeedback:
        field_deltas: Dict[str, float] = {}
        fam_deltas: Dict[str, float] = {}

        for r in results:
            # Reward high sharpe
            delta = 0.2 if r.sharpe >= 1.0 else (-0.1 if r.sharpe <= 0.0 else 0.0)
            # Extract fields
            tokens = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", r.expression))
            exclude = {"rank", "group_rank", "group_neutralize", "ts_scale", "subindustry"}
            for f in tokens - exclude:
                if not f.isdigit():
                    field_deltas[f] = field_deltas.get(f, 0.0) + delta

        prune_rules = [
            PruneRuleEvidence(
                pattern=str(decision.evidence.get("template_id") or decision.evidence.get("skeleton") or ""),
                pattern_type="template_id",
                reason=decision.reason_code,
                failure_rate=1.0,
                sample_n=1,
            )
            for decision in post_prunes
            if decision.is_pruned and (decision.evidence.get("template_id") or decision.evidence.get("skeleton"))
        ]

        return SelectionFeedback(
            field_weight_deltas=field_deltas,
            family_weight_deltas=fam_deltas,
            new_templates=distilled_templates,
            new_prune_rules=prune_rules,
        )


class SubmissionApprovalService:
    """Fail-closed validation service for SubmissionCase."""

    def validate_for_submission(
        self,
        candidate_result: NormalizedBacktestResult,
    ) -> SubmissionApprovalRecord:
        checks = {
            "sharpe_threshold": candidate_result.sharpe >= 1.0,
            "fitness_threshold": candidate_result.fitness >= 0.8,
            "turnover_threshold": 0.01 <= candidate_result.turnover <= 0.70,
            "all_checks_passed": candidate_result.checks_passed,
        }

        all_ok = all(checks.values())
        reason = "PASS" if all_ok else "Failed hard evidence submission gate: " + ", ".join([k for k, v in checks.items() if not v])

        return SubmissionApprovalRecord(
            is_approved=all_ok,
            approval_timestamp=datetime.now().isoformat(),
            gate_checks=checks,
            rejection_reason=reason,
        )
