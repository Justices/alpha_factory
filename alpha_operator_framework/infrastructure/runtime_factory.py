"""Infrastructure composition root for the research lifecycle."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import yaml

from alpha_operator_framework.application.research_runtime import ResearchRuntime
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.infrastructure.brain import build_backtest_gateway
from alpha_operator_framework.infrastructure.sqlalchemy_migrations import migrate
from alpha_operator_framework.infrastructure.sqlalchemy_repositories import (
    SqlAlchemyEventRepository,
    SqlAlchemyExperimentRepository,
    SqlAlchemyKnowledgeRepository,
    SqlAlchemyResearchRepository,
)
from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine
from sqlalchemy import inspect
from alpha_operator_framework.infrastructure.telemetry import ResearchTelemetry
from alpha_operator_framework.database.connection import DatabaseConnectionManager
from alpha_operator_framework.database.repository import AlphaDatabase
from alpha_operator_framework.database.schema import migrate_legacy_schema


def load_runtime_config(path: Path) -> Mapping[str, Any]:
    content = path.read_text(encoding="utf-8")
    loader = getattr(yaml, "safe_load", None)
    if loader is not None:
        data = loader(content)
    else:
        data = _parse_simple_yaml(content)
    if not isinstance(data, Mapping):
        raise ValueError("runtime configuration must be a YAML mapping")
    storage = data.get("storage")
    if not isinstance(storage, Mapping):
        raise ValueError("storage configuration is required")
    StorageConfig.from_mapping(storage, base_path=path.parent)
    return data


def storage_config(config_path: Path) -> StorageConfig:
    """Resolve the single storage configuration consumed by every adapter."""
    return StorageConfig.from_mapping(load_runtime_config(config_path)["storage"], base_path=config_path.parent)


def resolve_research_options(config_path: Path, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Merge research YAML defaults with explicit (non-None) CLI overrides."""
    config = load_runtime_config(config_path)
    research = config.get("research", {})
    if not isinstance(research, Mapping):
        raise ValueError("research configuration must be a mapping")
    values = dict(research)
    values.update({key: value for key, value in overrides.items() if value is not None})
    for name in ("region",):
        if not values.get(name):
            raise ValueError(f"research.{name} is required in YAML or CLI")
    integer_fields = ("delay", "decay", "seed")
    float_fields = ("truncation",)
    for name in integer_fields:
        if name in values:
            values[name] = int(values[name])
    for name in float_fields:
        if name in values:
            values[name] = float(values[name])
    return values


def resolve_literature_llm_options(config_path: Path, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve literature-pipeline LLM settings from YAML and CLI overrides."""
    config = load_runtime_config(config_path)
    research = config.get("research", {})
    if not isinstance(research, Mapping):
        raise ValueError("research configuration must be a mapping")
    raw = research.get("literature_llm", {})
    if not isinstance(raw, Mapping):
        raise ValueError("research.literature_llm must be a mapping")
    values = {"enabled": False, "config_path": None, "provider": None, "model": None, **raw}
    values.update({key: value for key, value in overrides.items() if value is not None})
    if not isinstance(values["enabled"], bool):
        raise ValueError("research.literature_llm.enabled must be a boolean")
    path_value = values["config_path"]
    values["config_path"] = (config_path.parent / path_value).resolve() if path_value else None
    return values


def resolve_construction_plan(config_path: Path, *, mode: str | None = None):
    """Load one explicit, ordered construction pipeline before field access."""
    from alpha_operator_framework.research.strategy_config import ConstructionPlan

    config = load_runtime_config(config_path)
    research = config.get("research")
    if not isinstance(research, Mapping):
        raise ValueError("research configuration must be a mapping")
    construction = research.get("construction")
    if not isinstance(construction, Mapping):
        raise ValueError("research.construction explicit strategy configuration is required")
    plan = ConstructionPlan.from_mapping(construction, base_path=config_path.parent)
    modes = research.get("construction_modes")
    selected_mode = mode or research.get("default_construction_mode")
    if selected_mode is None:
        return plan
    if not isinstance(modes, Mapping):
        raise ValueError("research.construction_modes is required when a construction mode is selected")
    raw_mode = modes.get(str(selected_mode))
    if not isinstance(raw_mode, Mapping):
        available = ", ".join(sorted(str(name) for name in modes))
        raise ValueError(f"unknown construction mode: {selected_mode} (available: {available})")
    raw_stages = raw_mode.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise ValueError(f"construction mode {selected_mode} requires a non-empty stages list")

    by_id = {strategy.strategy_id: strategy for strategy in plan.strategies}
    selected: list[Any] = []
    seen: set[str] = set()
    for stage_number, raw_stage in enumerate(raw_stages, start=1):
        if not isinstance(raw_stage, list) or not raw_stage:
            raise ValueError(f"construction mode {selected_mode} stage {stage_number} must be a non-empty list")
        for raw_strategy_id in raw_stage:
            strategy_id = str(raw_strategy_id)
            strategy = by_id.get(strategy_id)
            if strategy is None:
                raise ValueError(f"construction mode {selected_mode} references unknown strategy: {strategy_id}")
            if strategy_id in seen:
                raise ValueError(f"construction mode {selected_mode} repeats strategy: {strategy_id}")
            if stage_number == 1 and strategy.consumes_parents:
                raise ValueError(f"construction mode {selected_mode} stage 1 cannot consume qualified parents")
            if stage_number > 1 and not strategy.consumes_parents:
                raise ValueError(f"construction mode {selected_mode} stage {stage_number} must consume qualified parents")
            seen.add(strategy_id)
            selected.append(replace(strategy, stage=stage_number))
    return ConstructionPlan(
        tuple(selected), plan.parent_gate, plan.platform_batch_size, plan.promotion,
        plan.rolling_capacity_queue, plan.selection_window_batches,
    )


def _parse_simple_yaml(content: str) -> dict[str, Any]:
    """Parse the small mapping-only configuration shape when PyYAML is absent."""
    root: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith(" "):
            if current is None or ":" not in line:
                raise ValueError("unsupported YAML configuration syntax")
            key, value = (part.strip() for part in line.split(":", 1))
            current[key] = value.lower() == "true" if value.lower() in {"true", "false"} else value
            continue
        if not line.endswith(":"):
            raise ValueError("unsupported YAML configuration syntax")
        key = line[:-1].strip()
        current = {}
        root[key] = current
    return root


def build_research_runtime(
    config_path: Path,
    *,
    execute_platform: bool | None = None,
    evidence_records: Mapping[str, Mapping[str, Any]] | None = None,
    submission_authorized: bool = False,
    backtest_gateway: Any | None = None,
) -> ResearchRuntime:
    config = load_runtime_config(config_path)
    storage = storage_config(config_path)
    engine = create_storage_engine(storage)
    if inspect(engine).has_table("alpha_expressions"):
        migrate(engine)
    else:
        migrate_legacy_schema(engine)
    alpha_database = AlphaDatabase(DatabaseConnectionManager(storage))
    research = config.get("research", {})
    platform_execution = bool(research.get("execute_platform", False)) if execute_platform is None else execute_platform
    knowledge_repository = SqlAlchemyKnowledgeRepository(engine)
    evidence_gateway = submission_outbox = None
    if evidence_records is not None:
        from alpha_operator_framework.infrastructure.submission import ConfiguredSubmissionEvidenceGateway, SqlAlchemySubmissionOutbox

        evidence_gateway = ConfiguredSubmissionEvidenceGateway(evidence_records, submission_authorized)
        submission_outbox = SqlAlchemySubmissionOutbox(engine)
    return ResearchRuntime(
        event_store=EventStore(persistent=True, repository=SqlAlchemyEventRepository(engine)),
        research_repository=SqlAlchemyResearchRepository(engine),
        experiment_repository=SqlAlchemyExperimentRepository(engine),
        knowledge_repository=knowledge_repository,
        knowledge_base=knowledge_repository.load(),
        backtest_gateway=backtest_gateway or build_backtest_gateway(execute_platform=platform_execution),
        telemetry=ResearchTelemetry(),
        evidence_gateway=evidence_gateway,
        submission_outbox=submission_outbox,
        alpha_database=alpha_database,
        engine=engine,
    )


def build_submission_outbox(config_path: Path):
    """Create the submission outbox through the same storage configuration."""
    from alpha_operator_framework.infrastructure.submission import SqlAlchemySubmissionOutbox

    storage = storage_config(config_path)
    engine = create_storage_engine(storage)
    migrate(engine)
    return SqlAlchemySubmissionOutbox(engine)
