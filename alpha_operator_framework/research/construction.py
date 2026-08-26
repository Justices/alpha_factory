"""Pure, template-driven AST candidate construction for a ResearchRound."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from alpha_operator_framework.domain.ast import to_canonical_string, validate_expression
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.fields import FieldSpec, preprocess_fields_rotated
from alpha_operator_framework.domain.fields import ScalarField
from alpha_operator_framework.database.models import Template
from alpha_operator_framework.generation.template_library import TemplateStrategyConfig, template_creation_strategy

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
        return self._build_expressions(field_ids, set(field_ids), templates)

    def build_preprocessed(
        self,
        fields: Sequence[FieldSpec],
        templates: Sequence[ConstructionTemplate],
        *,
        seed: int | None = None,
    ) -> list[Candidate]:
        """Preprocess every scalar-capable field before template instantiation."""
        expressions = [expression for _, expression in preprocess_fields_rotated(fields, seed=seed)]
        return self._build_expressions(expressions, {field.id for field in fields}, templates)

    def build_template_library(
        self,
        templates: Sequence[Template],
        fields: Sequence[FieldSpec],
        *,
        sample_n: int = 80,
        seed: int | None = None,
    ) -> list[Candidate]:
        """Instantiate every active template-library entry with typed field slots."""
        scalar_fields = [
            ScalarField(expression, field.category, field.id)
            for field, expression in preprocess_fields_rotated(fields, seed=seed)
        ]
        active_families = tuple(dict.fromkeys(template.family for template in templates if template.active == 1))
        tasks = template_creation_strategy(
            templates,
            scalar_fields,
            [field.id for field in fields if field.type == "GROUP"],
            TemplateStrategyConfig(families=active_families, all_combinations=False, sample_n=sample_n),
            vector_fields=[field.id for field in fields if field.type == "VECTOR"],
        )
        tasks = [task for task in tasks if "vector_neut" not in task.expression]
        return self._build_tasks(tasks, {field.id for field in fields})

    @classmethod
    def _build_tasks(cls, tasks: Sequence[Task], known_fields: set[str]) -> list[Candidate]:
        candidates: list[Candidate] = []
        seen_canonical: set[str] = set()
        for task in tasks:
            template = ConstructionTemplate(
                f"{task.family}_{task.template_index}", "{field}", task.family, (),
            )
            for candidate in cls._build_expressions((task.expression,), known_fields, (template,)):
                if candidate.expression not in seen_canonical:
                    seen_canonical.add(candidate.expression)
                    candidates.append(candidate)
        return candidates

    @staticmethod
    def _build_expressions(
        field_expressions: Sequence[str],
        known_fields: set[str],
        templates: Sequence[ConstructionTemplate],
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        seen_canonical: set[str] = set()
        for field_expression in field_expressions:
            for template in templates:
                expression = template.expression_template.format(field=field_expression)
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
