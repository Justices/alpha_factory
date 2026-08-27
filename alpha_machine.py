#!/usr/bin/env python3
"""Alpha Factory system entry, command router, and stable compatibility facade."""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "alpha-factory.yaml"

_COMPATIBILITY_EXPORTS: dict[str, tuple[str, str]] = {
    "simulate": ("alpha_operator_framework.cli.simulation", "simulate"),
    "fetch_datafields": ("alpha_operator_framework.platform.datafields", "fetch_datafields"),
    "field_from_dict": ("alpha_operator_framework.cli.field_pipeline", "field_from_dict"),
    "select_fields": ("alpha_operator_framework.cli.field_pipeline", "select_fields"),
    "write_json": ("alpha_operator_framework.cli.field_pipeline", "_write_json"),
    "read_json": ("alpha_operator_framework.cli.field_pipeline", "_read_json"),
    "QualityGate": ("alpha_operator_framework.cli.field_pipeline", "QualityGate"),
    "filter_alpha_results": ("alpha_operator_framework.cli.field_pipeline", "filter_alpha_results"),
    "group_candidates": ("alpha_operator_framework.cli.field_pipeline", "group_candidates"),
    "FieldSpec": ("alpha_operator_framework.application.task_construction", "FieldSpec"),
    "preprocess_field": ("alpha_operator_framework.application.task_construction", "preprocess_field"),
    "command_simulate": ("alpha_operator_framework.cli.simulation", "command_simulate"),
    "fetch_user_alphas": ("cnhkmcp.untracked.platform_functions", "get_user_alphas"),
    "get_alpha_details": ("cnhkmcp.untracked.platform_functions", "get_alpha_details"),
}


def command_domains() -> Mapping[str, tuple[str, ...]]:
    from alpha_operator_framework.cli.router import command_domains as catalog

    return catalog()


def build_parser() -> argparse.ArgumentParser:
    from alpha_operator_framework.cli.router import build_parser as factory

    return factory()


def route(argv: Sequence[str] | None = None) -> Any:
    import logging
    # 统一配置全局日志格式，确保输出包含具体文件名、行号等位置信息
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d) - %(message)s",
        level=logging.INFO
    )
    from alpha_operator_framework.cli.router import route as dispatch

    return dispatch(argv)


def main(argv: Sequence[str] | None = None) -> Any:
    return route(argv)


def positive_seconds(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return value


def mark_stalled_before_poll(tracker: Any, batch_id: int, max_idle_seconds: float | None) -> bool:
    if max_idle_seconds is None:
        return False
    return bool(tracker.mark_stalled_if_expired(batch_id, max_idle_seconds))


def database_path(args: Any) -> Path | None:
    from alpha_operator_framework.infrastructure.maintenance import storage_path

    return storage_path(Path(getattr(args, "config", DEFAULT_RUNTIME_CONFIG_PATH)))


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _COMPATIBILITY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(importlib.import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_COMPATIBILITY_EXPORTS))


__all__ = [
    "DEFAULT_RUNTIME_CONFIG_PATH", "build_parser", "command_domains", "database_path",
    "main", "mark_stalled_before_poll", "positive_seconds", "route",
    *_COMPATIBILITY_EXPORTS,
]


if __name__ == "__main__":
    main()
