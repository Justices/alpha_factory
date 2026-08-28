"""Pure, template-driven AST candidate construction for a ResearchRound."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from alpha_operator_framework.domain.ast import to_canonical_string, validate_expression
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.fields import FieldSpec, preprocess_fields_rotated
from alpha_operator_framework.domain.fields import ScalarField
from alpha_operator_framework.domain.operators import ACCESS_LIMITED_OPS
from alpha_operator_framework.database.models import Template
from alpha_operator_framework.generation.template_library import (
    TemplateStrategyConfig,
    _render_any,
    extract_slot_names,
    slot_context_types,
    template_creation_strategy,
)

from .round import Candidate


@dataclass(frozen=True)
class ConstructionTemplate:
    template_id: str
    expression_template: str
    family: str
    operators: tuple[str, ...]


class AstCandidateBuilder:
    """Instantiate configured templates while keeping only valid unique ASTs."""

    @staticmethod
    def _has_access_limited_operator(operators: Sequence[str]) -> bool:
        return bool(set(operators).intersection(ACCESS_LIMITED_OPS))

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
        return self._build_tasks(tasks, {field.id for field in fields})

    def build_order2(
        self,
        parent: Candidate,
        templates: Sequence[Template],
        *,
        limit_per_template: int = 200,
    ) -> list[Candidate]:
        """Apply every compatible active unary template to one signal expression."""
        return self._build_optimization_candidates(
            parent, (), templates, stage="order2", limit_per_template=limit_per_template,
        )

    def build_dimension2(
        self,
        parent: Candidate,
        fields: Sequence[FieldSpec],
        templates: Sequence[Template],
        *,
        limit_per_template: int = 200,
        seed: int | None = None,
    ) -> list[Candidate]:
        """Pair one signal expression with a different raw field in the same category."""
        parent_categories = {
            field.category for field in fields if field.id in parent.fields and field.category
        }
        partners = [
            (field, expression)
            for field, expression in preprocess_fields_rotated(fields, seed=seed)
            if field.id not in parent.fields and field.category in parent_categories
        ]
        return self._build_optimization_candidates(
            parent, partners, templates, stage="dimension2", limit_per_template=limit_per_template,
        )

    @staticmethod
    def _compatible_template_slots(template: Template, count: int) -> list[str] | None:
        if (
            template.active != 1
            or template.template_type != "placeholder"
            or any(f"{operator}(" in template.expression_template for operator in ACCESS_LIMITED_OPS)
        ):
            return None
        slots = extract_slot_names(template.expression_template)
        contexts = slot_context_types(template.expression_template)
        placeholders = template.placeholders or {}
        if len(slots) != count or template.group_slots or any(contexts.get(slot) == "vector" for slot in slots):
            return None
        if any(placeholders.get(slot, {}).get("role") not in {None, "scalar"} for slot in slots):
            return None
        return slots

    @classmethod
    def _build_optimization_candidates(
        cls,
        parent: Candidate,
        partners: Sequence[tuple[FieldSpec, str]],
        templates: Sequence[Template],
        *,
        stage: str,
        limit_per_template: int,
    ) -> list[Candidate]:
        if limit_per_template <= 0:
            return []
        if stage not in {"order2", "dimension2"}:
            raise ValueError(f"unsupported optimization stage: {stage}")
        family = f"optimization_{stage}"
        known_fields = set(parent.fields) | {field.id for field, _ in partners}
        candidates: list[Candidate] = []
        seen: set[str] = set()
        required_slots = 1 if stage == "order2" else 2
        for template in templates:
            slots = cls._compatible_template_slots(template, required_slots)
            if slots is None:
                continue
            values = [None] if stage == "order2" else list(partners[:limit_per_template])
            for partner in values:
                mapper = {slots[0]: parent.expression}
                if partner is not None:
                    mapper[slots[1]] = partner[1]
                expression = _render_any(template.expression_template, mapper)
                validation = validate_expression(expression, known_fields=known_fields)
                if (
                    not validation.is_valid
                    or any("Unknown or custom operator" in warning for warning in validation.warnings)
                    or cls._has_access_limited_operator(validation.operators_used)
                ):
                    continue
                canonical = to_canonical_string(expression)
                if canonical in seen:
                    continue
                seen.add(canonical)
                digest = hashlib.sha256(f"{stage}:{template.name}:{canonical}".encode("utf-8")).hexdigest()[:16]
                candidates.append(Candidate(
                    candidate_id=f"{template.name}:{digest}", expression=canonical, family=family,
                    fields=tuple(sorted(validation.fields_used)), operators=tuple(sorted(validation.operators_used)),
                    template_id=template.name, lineage_parent_id=parent.candidate_id,
                ))
        return candidates

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
                if (
                    not validation.is_valid
                    or any("Unknown or custom operator" in warning for warning in validation.warnings)
                    or AstCandidateBuilder._has_access_limited_operator(validation.operators_used)
                ):
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
