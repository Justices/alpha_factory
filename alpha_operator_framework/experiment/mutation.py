"""AST-valid mutations proposed after experiment evaluation."""

from __future__ import annotations

from typing import Any

from alpha_operator_framework.domain.ast import to_canonical_string, validate_expression

from .models import ExperimentBatch, MutationProposal


def propose_mutations(
    batch: ExperimentBatch,
    *,
    max_proposals: int,
    random_source: Any,
) -> list[MutationProposal]:
    proposals: list[MutationProposal] = []
    for parent in sorted(batch.mutation_parents(), key=lambda result: result.task_id):
        if len(proposals) >= max_proposals:
            break
        expression = f"ts_rank({parent.expression}, 22)"
        if validate_expression(expression).is_valid:
            proposals.append(MutationProposal(parent.task_id, to_canonical_string(expression), "wrap_ts_rank_22"))
    return proposals
