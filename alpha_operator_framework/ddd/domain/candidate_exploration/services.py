"""Candidate Exploration Bounded Context - Domain Services."""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Set
from .models import Candidate, PrePruneDecision, ResearchPolicy


class AstCanonicalizer:
    """Canonicalizes AST expressions and calculates deterministic hashes."""

    @staticmethod
    def canonicalize(expr: str) -> str:
        # Standardize spacing around operators and parentheses
        cleaned = re.sub(r"\s+", "", expr)
        # Normalize double negation or invalid tokens
        cleaned = cleaned.replace("--", "")
        return cleaned


class PrePruningService:
    """Evaluates candidates before backtest (syntax, type compatibility, duplicate hash, hard budget)."""

    def __init__(self, prohibited_patterns: Sequence[str] = ()):
        self.prohibited_patterns = list(prohibited_patterns)

    def evaluate_candidate(
        self,
        candidate: Candidate,
        seen_canonical_hashes: Set[str],
        policy: ResearchPolicy,
    ) -> PrePruneDecision:
        # 1. Syntax check
        if not candidate.expression or candidate.expression.count("(") != candidate.expression.count(")"):
            return PrePruneDecision(
                candidate_id=candidate.candidate_id,
                is_rejected=True,
                reason_code="SYNTAX_UNBALANCED_PARENS",
                policy_version=policy.version,
            )

        # 2. Prohibited patterns check (e.g. division by zero or nesting ts_delta)
        for pat in self.prohibited_patterns:
            if pat in candidate.expression:
                return PrePruneDecision(
                    candidate_id=candidate.candidate_id,
                    is_rejected=True,
                    reason_code="PROHIBITED_SYNTAX_PATTERN",
                    evidence={"matched_pattern": pat},
                    policy_version=policy.version,
                )

        # 3. Canonical duplicate check
        chash = candidate.canonical_hash or candidate.compute_canonical_hash()
        if chash in seen_canonical_hashes:
            return PrePruneDecision(
                candidate_id=candidate.candidate_id,
                is_rejected=True,
                reason_code="EXACT_CANONICAL_DUPLICATE",
                evidence={"hash": chash},
                policy_version=policy.version,
            )

        seen_canonical_hashes.add(chash)
        return PrePruneDecision(
            candidate_id=candidate.candidate_id,
            is_rejected=False,
            reason_code="PASS",
            policy_version=policy.version,
        )


class CandidateFactory:
    """Generates structural candidate expressions across multiple operator families."""

    def generate_family_candidates(
        self,
        fields: Sequence[str],
        family: str,
        decay: int = 12,
        neutralization: str = "SUBINDUSTRY",
    ) -> List[Candidate]:
        candidates: List[Candidate] = []
        for idx, f in enumerate(fields):
            cid = f"cand_{family}_{f}_{idx}"
            if family == "ts_momentum":
                expr = f"ts_decay_linear(ts_delta({f}, 5), {decay})"
            elif family == "reversion":
                expr = f"-1 * ts_rank({f}, 22)"
            elif family == "group_neutral":
                expr = f"group_neutralize(rank({f}), {neutralization})"
            elif family == "three_tier_standard":
                expr = f"ts_scale(group_rank({f}, {neutralization}), 30)"
            elif family == "volatility_ratio":
                expr = f"ts_delta({f}, 5) / (ts_std_dev({f}, 22) + 0.001)"
            else:
                expr = f"rank({f})"

            cand = Candidate(
                candidate_id=cid,
                expression=expr,
                family=family,
                fields=[f],
                decay=decay,
                generation_strategy="carpet_standard",
            )
            cand.compute_canonical_hash()
            candidates.append(cand)

        return candidates
