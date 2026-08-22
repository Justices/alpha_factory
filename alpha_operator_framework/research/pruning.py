"""Pure pre-backtest pruning policies for ResearchRound."""

from __future__ import annotations

import hashlib
from typing import Sequence

from alpha_operator_framework.domain.ast import to_canonical_string, validate_expression

from .round import Candidate, PruningDecision, ResearchPolicy


class AstPrePruner:
    def evaluate(self, candidates: Sequence[Candidate], policy: ResearchPolicy) -> list[PruningDecision]:
        seen_hashes: set[str] = set()
        decisions: list[PruningDecision] = []
        for candidate in candidates:
            validation = validate_expression(candidate.expression)
            if not validation.is_valid:
                decisions.append(PruningDecision(candidate.candidate_id, True, "AST_INVALID", {"errors": tuple(validation.errors)}))
                continue
            matched = next((pattern for pattern in policy.prohibited_patterns if pattern in candidate.expression), None)
            if matched is not None:
                decisions.append(PruningDecision(candidate.candidate_id, True, "PROHIBITED_PATTERN", {"pattern": matched}))
                continue
            canonical = to_canonical_string(candidate.expression)
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                decisions.append(PruningDecision(candidate.candidate_id, True, "AST_CANONICAL_DUPLICATE", {"canonical": canonical}))
                continue
            seen_hashes.add(digest)
            decisions.append(PruningDecision(candidate.candidate_id, False, "PASS"))
        return decisions
