"""Composable candidate sources and their shared deterministic acceptance pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

from alpha_operator_framework.database.models import Template
from alpha_operator_framework.domain.ast import to_canonical_string, validate_expression
from alpha_operator_framework.domain.fields import (
    FieldSpec,
    preprocess_field,
    preprocess_fields_rotated,
)
from alpha_operator_framework.domain.operators import ACCESS_LIMITED_OPS, basic_ops, group_ops, ts_ops

from .construction import AstCandidateBuilder
from .round import Candidate
from .strategy_config import ConstructionPlan, ConstructionStrategyConfig
from .structure import NON_DATA_VARIABLES, leaf_family, measure_expression_structure


@dataclass(frozen=True)
class CandidateDraft:
    expression: str
    strategy_id: str
    strategy_kind: str
    template_family: str
    template_id: str = ""
    hypothesis_id: str = ""
    parent_ids: tuple[str, ...] = ()
    seed: int = 0


@dataclass(frozen=True)
class CandidateProvenance:
    candidate_id: str
    strategy_id: str
    strategy_kind: str
    leaf_family: str
    template_id: str
    hypothesis_id: str
    parent_ids: tuple[str, ...]
    order_depth: int
    field_count: int
    seed: int
    strategy_priority: int = 0

    @property
    def provenance_id(self) -> str:
        payload = "|".join((
            self.candidate_id,
            self.strategy_id,
            self.leaf_family,
            self.template_id,
            self.hypothesis_id,
            *self.parent_ids,
        ))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StrategyStatus:
    strategy_id: str
    kind: str
    status: str
    generated_count: int = 0
    error: str = ""


@dataclass(frozen=True)
class ConstructionContext:
    fields: tuple[FieldSpec, ...]
    templates: tuple[Template, ...]
    parents: tuple[Candidate, ...] = ()
    seed: int = 0
    region: str = ""
    universe: str = ""
    delay: int | None = None


@dataclass
class ConstructionOutcome:
    candidates: list[Candidate] = field(default_factory=list)
    provenances: list[CandidateProvenance] = field(default_factory=list)
    strategy_statuses: list[StrategyStatus] = field(default_factory=list)
    rejected: list[tuple[CandidateDraft, str]] = field(default_factory=list)

    @property
    def partial_failed(self) -> bool:
        return any(status.status == "FAILED" for status in self.strategy_statuses)


class ConstructionStrategy(Protocol):
    kind: str

    def generate(
        self,
        context: ConstructionContext,
        config: ConstructionStrategyConfig,
    ) -> Sequence[CandidateDraft]: ...


class DatabaseTemplateStrategy:
    kind = "database_template"

    def __init__(self, builder: AstCandidateBuilder | None = None) -> None:
        self.builder = builder or AstCandidateBuilder()

    def generate(self, context: ConstructionContext, config: ConstructionStrategyConfig) -> list[CandidateDraft]:
        templates = _select_templates(context.templates, config.families)
        candidates = self.builder.build_template_library(templates, context.fields, seed=context.seed)
        return [_draft_from_candidate(candidate, config, context.seed) for candidate in candidates]


class RawFirstOrderStrategy:
    """Machine-lib style first-order expansion with no template-library dependency."""

    kind = "raw_first_order"
    windows = (5, 22, 66, 120, 252, 504)

    def generate(self, context: ConstructionContext, config: ConstructionStrategyConfig) -> list[CandidateDraft]:
        if config.source != "raw_fields":
            return []
        family = config.families[0]
        drafts: list[CandidateDraft] = []
        for field_spec, expression in preprocess_fields_rotated(context.fields, seed=context.seed):
            drafts.append(self._draft(expression, field_spec.id, "identity", family, config, context.seed))
            for operator in basic_ops:
                drafts.append(self._draft(
                    f"{operator}({expression})", field_spec.id, operator, family, config, context.seed,
                ))
            for operator in ts_ops:
                for window in self.windows:
                    drafts.append(self._draft(
                        f"{operator}({expression}, {window})", field_spec.id,
                        f"{operator}:{window}", family, config, context.seed,
                    ))
        return drafts

    @staticmethod
    def _draft(
        expression: str,
        field_id: str,
        operator: str,
        family: str,
        config: ConstructionStrategyConfig,
        seed: int,
    ) -> CandidateDraft:
        return CandidateDraft(
            expression=expression,
            strategy_id=config.strategy_id,
            strategy_kind=config.kind,
            template_family=family,
            template_id=f"{field_id}:{operator}",
            seed=seed,
        )


class AiNakedSignalStrategy:
    """LLM-generated simple economic seeds with deterministic code-side guards."""

    kind = "ai_naked_signal"
    allowed_operators = (
        "reverse", "inverse", "rank", "zscore", "quantile", "normalize",
        "ts_rank", "ts_zscore", "ts_delta", "ts_mean", "ts_sum", "ts_std_dev",
    )
    windows = (5, 22, 66, 120, 252, 504)

    def __init__(self, llm_client: object | None = None) -> None:
        self._llm_client = llm_client

    def generate(self, context: ConstructionContext, config: ConstructionStrategyConfig) -> list[CandidateDraft]:
        if config.source != "raw_fields" or config.llm_profile is None:
            return []
        usable_fields = [item for item in context.fields if item.type != "GROUP"]
        scalar_variants_by_id: dict[str, tuple[str, ...]] = {}
        for field_spec in usable_fields:
            variants = tuple(preprocess_field(field_spec))
            if variants:
                scalar_variants_by_id[field_spec.id] = variants
        if not scalar_variants_by_id:
            return []
        requested = min(100, max(8, config.quota_per_leaf_family * 4))
        field_payload = [
            {"id": field_spec.id, "description": field_spec.description[:160]}
            for field_spec in usable_fields[:50]
            if field_spec.id in scalar_variants_by_id
        ]
        prompt = (
            f"为 WorldQuant BRAIN 生成 {requested} 个简单、纯粹、具有经济学含义的裸信号。\n"
            "输入只包含字段名和描述。每个信号只能使用一个字段，最多嵌套两个算子；"
            "不要使用分组、中性化、回填、winsorize 或 vec 算子，这些由代码处理。\n"
            f"允许算子：{', '.join(self.allowed_operators)}。"
            f"时间窗口只能使用：{', '.join(map(str, self.windows))}。\n"
            "严格输出 JSON 数组，每项必须含 title、expression、rationale；"
            "rationale 必须说明市场低效、经济机制、错价来源和因子类别。\n"
            f"字段：{json.dumps(field_payload, ensure_ascii=False, separators=(',', ':'))}"
        )
        client = self._llm_client
        if client is None:
            from alpha_operator_framework.research.llm_client import UnifiedLLMClient

            client = UnifiedLLMClient()
        response = client.chat(  # type: ignore[attr-defined]
            prompt=prompt,
            provider=config.llm_profile,
            system_prompt=(
                "你是严谨的 Alpha 裸信号研究员。只返回 JSON，不展示思维过程，"
                "优先经济含义明确的简单表达式。"
            ),
        )
        items = self._parse_response(str(response))
        drafts: list[CandidateDraft] = []
        family = config.families[0]
        for index, item in enumerate(items[:requested]):
            expression = str(item.get("expression") or "").strip()
            title = str(item.get("title") or f"AI naked signal {index + 1}").strip()
            rationale = str(item.get("rationale") or "").strip()
            if not expression or not rationale:
                continue
            grounded = self._ground_expression(
                expression, scalar_variants_by_id, variant_index=index,
            )
            hypothesis = json.dumps(
                {"title": title, "rationale": rationale},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            drafts.append(CandidateDraft(
                expression=grounded,
                strategy_id=config.strategy_id,
                strategy_kind=config.kind,
                template_family=family,
                template_id=f"ai-naked-{index + 1}",
                hypothesis_id=hypothesis,
                seed=context.seed,
            ))
        return drafts

    @staticmethod
    def _parse_response(response: str) -> list[dict[str, object]]:
        match = re.search(r"\[.*\]", response, flags=re.DOTALL)
        if match is None:
            raise ValueError("AI naked signal response does not contain a JSON array")
        payload = json.loads(match.group(0))
        if not isinstance(payload, list):
            raise ValueError("AI naked signal response must be a JSON array")
        return [dict(item) for item in payload if isinstance(item, Mapping)]

    @staticmethod
    def _ground_expression(
        expression: str,
        scalar_variants_by_id: Mapping[str, Sequence[str]],
        *,
        variant_index: int = 0,
    ) -> str:
        grounded = expression
        for field_id in sorted(scalar_variants_by_id, key=len, reverse=True):
            variants = scalar_variants_by_id[field_id]
            if not variants:
                continue
            scalar = variants[variant_index % len(variants)]
            grounded = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(field_id)}(?![A-Za-z0-9_])",
                f"({scalar})",
                grounded,
            )
        return grounded


class _ParentTransformStrategy:
    kind = ""

    def __init__(self, builder: AstCandidateBuilder | None = None) -> None:
        self.builder = builder or AstCandidateBuilder()

    def generate(self, context: ConstructionContext, config: ConstructionStrategyConfig) -> list[CandidateDraft]:
        templates = _select_templates(context.templates, config.families)
        drafts: list[CandidateDraft] = []
        if config.source in {"raw_fields", "raw_and_qualified_candidates"}:
            base = self.builder.build_template_library(templates, context.fields, seed=context.seed)
            drafts.extend(_draft_from_candidate(candidate, config, context.seed) for candidate in base)
        if config.source in {"qualified_candidates", "raw_and_qualified_candidates"}:
            for parent in context.parents:
                children = self.builder.build_transform(
                    parent,
                    context.fields,
                    templates,
                    order_depth=config.order_depth,
                    field_count=config.field_count,
                    seed=context.seed,
                )
                drafts.extend(_draft_from_candidate(candidate, config, context.seed) for candidate in children)
        return drafts


class DepthConstructionStrategy(_ParentTransformStrategy):
    kind = "depth_construction"


class FieldCompositionStrategy(_ParentTransformStrategy):
    kind = "field_composition"


class GroupSecondOrderStrategy:
    """Apply group transforms to qualified parents using scoped cached GROUP fields."""

    kind = "group_second_order"

    def generate(self, context: ConstructionContext, config: ConstructionStrategyConfig) -> list[CandidateDraft]:
        if config.source not in {"qualified_candidates", "raw_and_qualified_candidates"}:
            return []
        groups = self._resolve_groups(context)
        if not groups:
            return []
        family = config.families[0]
        drafts: list[CandidateDraft] = []
        for parent in context.parents:
            for group in groups:
                for operator in group_ops:
                    drafts.append(CandidateDraft(
                        expression=f"{operator}({parent.expression}, densify({group.id}))",
                        strategy_id=config.strategy_id,
                        strategy_kind=config.kind,
                        template_family=family,
                        template_id=f"{operator}:{group.id}",
                        parent_ids=(parent.candidate_id,),
                        seed=context.seed,
                    ))
        return drafts

    @staticmethod
    def _resolve_groups(context: ConstructionContext) -> tuple[FieldSpec, ...]:
        """Prefer exact-scope cache; explicit context fields are offline fallback."""
        if context.region and context.universe and context.delay is not None:
            from alpha_operator_framework.research.field_loader import load_or_fetch_group_fields

            return tuple(load_or_fetch_group_fields(context.region, context.universe, context.delay))
        return tuple(field for field in context.fields if field.type == "GROUP")


class SignalValidationStrategy:
    """Generate terminal rank/sign invariance checks for qualified signals."""

    kind = "signal_validation"

    def generate(self, context: ConstructionContext, config: ConstructionStrategyConfig) -> list[CandidateDraft]:
        if config.source not in {"qualified_candidates", "raw_and_qualified_candidates"}:
            return []
        family = config.families[0]
        drafts: list[CandidateDraft] = []
        for parent in context.parents:
            for operator in ("rank", "sign"):
                drafts.append(CandidateDraft(
                    expression=f"{operator}({parent.expression})",
                    strategy_id=config.strategy_id,
                    strategy_kind=config.kind,
                    template_family=family,
                    template_id=f"validation:{operator}",
                    hypothesis_id=f"invariance:{operator}",
                    parent_ids=(parent.candidate_id,),
                    seed=context.seed,
                ))
        return drafts


class LiteratureHypothesisStrategy:
    kind = "literature_llm"

    def generate(self, context: ConstructionContext, config: ConstructionStrategyConfig) -> list[CandidateDraft]:
        if config.document is None or config.llm_profile is None:
            raise ValueError(f"literature strategy {config.strategy_id} is incomplete")
        from alpha_operator_framework.research.pipeline import ingest_literature_to_alphas

        tasks = ingest_literature_to_alphas(
            str(config.document),
            context.fields,
            title_hint=config.document.stem,
            use_llm=True,
            provider=config.llm_profile,
            allow_llm_fallback=False,
        )
        drafts = []
        for index, task in enumerate(tasks):
            hypothesis = str(task.meta.get("paper_title") or task.meta.get("idea_title") or index)
            drafts.append(CandidateDraft(
                expression=task.expression,
                strategy_id=config.strategy_id,
                strategy_kind=config.kind,
                template_family=(
                    task.family
                    if "*" in config.families or task.family in config.families
                    else config.families[0]
                ),
                template_id=f"paper-{task.template_index}",
                hypothesis_id=hypothesis,
                seed=context.seed,
            ))
        return drafts


class CandidateAcceptancePipeline:
    """Accept untrusted drafts and assign one canonical identity plus all provenance."""

    def accept(
        self,
        drafts: Sequence[CandidateDraft],
        plan: ConstructionPlan,
        known_fields: set[str],
    ) -> ConstructionOutcome:
        configs = {config.strategy_id: config for config in plan.strategies}
        priorities = {config.strategy_id: index for index, config in enumerate(plan.strategies)}
        candidates_by_expression: dict[str, Candidate] = {}
        provenance_by_id: dict[str, CandidateProvenance] = {}
        rejected: list[tuple[CandidateDraft, str]] = []
        for draft in drafts:
            config = configs.get(draft.strategy_id)
            if config is None:
                rejected.append((draft, "unknown_strategy"))
                continue
            validation = validate_expression(
                draft.expression,
                known_fields=set(known_fields) | set(NON_DATA_VARIABLES),
            )
            if not validation.is_valid:
                rejected.append((draft, "invalid_ast"))
                continue
            if set(validation.operators_used).intersection(ACCESS_LIMITED_OPS):
                rejected.append((draft, "access_limited_operator"))
                continue
            if any("Unknown or custom operator" in warning for warning in validation.warnings):
                rejected.append((draft, "unknown_operator"))
                continue
            if any("not found in known fields catalogue" in warning for warning in validation.warnings):
                rejected.append((draft, "unknown_field"))
                continue
            canonical = to_canonical_string(draft.expression)
            try:
                structure = measure_expression_structure(canonical, known_fields)
            except ValueError:
                rejected.append((draft, "invalid_structure"))
                continue
            if not config.order_depth.contains(structure.order_depth):
                rejected.append((draft, "order_depth_out_of_range"))
                continue
            if not config.field_count.contains(structure.field_count):
                rejected.append((draft, "field_count_out_of_range"))
                continue
            claimed_family = leaf_family(config.kind, draft.template_family, structure)
            candidate_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            provenance = CandidateProvenance(
                candidate_id=candidate_id,
                strategy_id=config.strategy_id,
                strategy_kind=config.kind,
                leaf_family=claimed_family,
                template_id=draft.template_id,
                hypothesis_id=draft.hypothesis_id,
                parent_ids=draft.parent_ids,
                order_depth=structure.order_depth,
                field_count=structure.field_count,
                seed=draft.seed,
                strategy_priority=priorities[config.strategy_id],
            )
            provenance_by_id.setdefault(provenance.provenance_id, provenance)
            if canonical not in candidates_by_expression:
                candidates_by_expression[canonical] = Candidate(
                    candidate_id=candidate_id,
                    expression=canonical,
                    family=claimed_family,
                    fields=structure.fields,
                    operators=tuple(sorted(validation.operators_used)),
                    template_id=draft.template_id,
                    lineage_parent_id=draft.parent_ids[0] if draft.parent_ids else None,
                    origin_strategy=config.strategy_id,
                    leaf_family=claimed_family,
                    order_depth=structure.order_depth,
                    field_count=structure.field_count,
                    provenance_ids=(provenance.provenance_id,),
                )
            else:
                current = candidates_by_expression[canonical]
                candidates_by_expression[canonical] = Candidate(
                    **{
                        **current.__dict__,
                        "provenance_ids": tuple(dict.fromkeys((*current.provenance_ids, provenance.provenance_id))),
                    }
                )
        return ConstructionOutcome(
            candidates=list(candidates_by_expression.values()),
            provenances=list(provenance_by_id.values()),
            rejected=rejected,
        )


class ConstructionStrategyRegistry:
    def __init__(self, strategies: Sequence[ConstructionStrategy] | None = None) -> None:
        registered = strategies or (
            DatabaseTemplateStrategy(),
            RawFirstOrderStrategy(),
            AiNakedSignalStrategy(),
            DepthConstructionStrategy(),
            FieldCompositionStrategy(),
            GroupSecondOrderStrategy(),
            SignalValidationStrategy(),
            LiteratureHypothesisStrategy(),
        )
        self._strategies: Mapping[str, ConstructionStrategy] = {strategy.kind: strategy for strategy in registered}
        self._acceptance = CandidateAcceptancePipeline()

    def generate(self, plan: ConstructionPlan, context: ConstructionContext) -> ConstructionOutcome:
        drafts: list[CandidateDraft] = []
        statuses: list[StrategyStatus] = []
        for config in plan.strategies:
            strategy = self._strategies.get(config.kind)
            if strategy is None:
                statuses.append(StrategyStatus(config.strategy_id, config.kind, "FAILED", error="strategy adapter is unavailable"))
                continue
            try:
                generated = list(strategy.generate(context, config))
            except Exception as error:
                statuses.append(StrategyStatus(config.strategy_id, config.kind, "FAILED", error=str(error)))
                continue
            drafts.extend(generated)
            statuses.append(StrategyStatus(
                config.strategy_id,
                config.kind,
                "GENERATED" if generated else "EXHAUSTED",
                generated_count=len(generated),
            ))
        outcome = self._acceptance.accept(drafts, plan, {field.id for field in context.fields})
        accepted_counts: dict[str, int] = {}
        for provenance in outcome.provenances:
            accepted_counts[provenance.strategy_id] = accepted_counts.get(provenance.strategy_id, 0) + 1
        outcome.strategy_statuses = [
            status
            if status.status == "FAILED"
            else StrategyStatus(
                status.strategy_id,
                status.kind,
                "GENERATED" if accepted_counts.get(status.strategy_id, 0) else "EXHAUSTED",
                generated_count=accepted_counts.get(status.strategy_id, 0),
            )
            for status in statuses
        ]
        return outcome


def _draft_from_candidate(
    candidate: Candidate,
    config: ConstructionStrategyConfig,
    seed: int,
) -> CandidateDraft:
    return CandidateDraft(
        expression=candidate.expression,
        strategy_id=config.strategy_id,
        strategy_kind=config.kind,
        template_family=candidate.family,
        template_id=candidate.template_id,
        parent_ids=(candidate.lineage_parent_id,) if candidate.lineage_parent_id else (),
        seed=seed,
    )


def _select_templates(
    templates: Sequence[Template],
    families: tuple[str, ...],
) -> list[Template]:
    if "*" in families:
        return list(templates)
    return [template for template in templates if template.family in families]


__all__ = [
    "CandidateAcceptancePipeline",
    "CandidateDraft",
    "CandidateProvenance",
    "ConstructionContext",
    "ConstructionOutcome",
    "ConstructionStrategyRegistry",
    "StrategyStatus",
]
