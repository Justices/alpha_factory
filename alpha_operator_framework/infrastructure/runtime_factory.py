"""Infrastructure composition root for the research lifecycle."""

from __future__ import annotations

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
    SqlAlchemyTemplatePromotionRepository,
)
from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine
from alpha_operator_framework.infrastructure.telemetry import ResearchTelemetry
from alpha_operator_framework.database import AlphaDatabase


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
    for name in ("region", "universe"):
        if not values.get(name):
            raise ValueError(f"research.{name} is required in YAML or CLI")
    integer_fields = ("delay", "decay", "sample_per_family", "seed")
    float_fields = ("truncation",)
    for name in integer_fields:
        if name in values:
            values[name] = int(values[name])
    for name in float_fields:
        if name in values:
            values[name] = float(values[name])
    return values


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
    migrate(engine)
    alpha_database = AlphaDatabase(storage)
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
        template_repository=SqlAlchemyTemplatePromotionRepository(engine),
        knowledge_base=knowledge_repository.load(),
        backtest_gateway=backtest_gateway or build_backtest_gateway(execute_platform=platform_execution),
        telemetry=ResearchTelemetry(),
        evidence_gateway=evidence_gateway,
        submission_outbox=submission_outbox,
        alpha_database=alpha_database,
    )


def build_submission_outbox(config_path: Path):
    """Create the submission outbox through the same storage configuration."""
    from alpha_operator_framework.infrastructure.submission import SqlAlchemySubmissionOutbox

    config = load_runtime_config(config_path)
    storage = storage_config(config_path)
    engine = create_storage_engine(storage)
    migrate(engine)
    return SqlAlchemySubmissionOutbox(engine)
