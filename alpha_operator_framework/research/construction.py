"""Pure, template-driven AST candidate construction for a ResearchRound."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from alpha_operator_framework.domain.ast import to_canonical_string, validate_expression

from .round import Candidate


@dataclass(frozen=True)
class ConstructionTemplate:
    template_id: str
    expression_template: str
    family: str
    operators: tuple[str, ...]


class AstCandidateBuilder:
    """Instantiate configured templates while keeping only valid unique ASTs."""

    def build(
        self,
        field_ids: Sequence[str],
        templates: Sequence[ConstructionTemplate],
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        seen_canonical: set[str] = set()
        known_fields = set(field_ids)
        for field_id in field_ids:
            for template in templates:
                expression = template.expression_template.format(field=field_id)
                validation = validate_expression(expression, known_fields=known_fields)
                if not validation.is_valid or any("Unknown or custom operator" in warning for warning in validation.warnings):
                    continue
                canonical = to_canonical_string(expression)
                if canonical in seen_canonical:
                    continue
                seen_canonical.add(canonical)
                candidate_hash = hashlib.sha256(
                    f"{template.template_id}:{canonical}".encode("utf-8")
                ).hexdigest()[:16]
                candidates.append(Candidate(
                    candidate_id=f"{template.template_id}:{candidate_hash}",
                    expression=canonical,
                    family=template.family,
                    fields=tuple(sorted(validation.fields_used)),
                    operators=tuple(sorted(validation.operators_used)) or template.operators,
                    template_id=template.template_id,
                ))
        return candidates
