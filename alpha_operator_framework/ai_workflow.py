"""Compatibility facade for the AI workflow API.

Implementations live in :mod:`alpha_operator_framework.workflow`; this module
keeps the original import path and CLI entry point stable.
"""

from __future__ import annotations

import asyncio
import json
import sys
from types import ModuleType

from alpha_operator_framework.platform.simulation_gateway import simulate
from alpha_operator_framework.workflow import branches as _branches
from alpha_operator_framework.workflow import full as _full
from alpha_operator_framework.workflow import survey as _survey
from alpha_operator_framework.workflow import (
    DeepenConfig,
    OptimizeConfig,
    SignalBranchConfig,
    SurveyConfig,
    WorkflowResult,
    build_signal_branches,
    run_full_workflow,
    run_signal_branches,
    run_survey_with_fields,
)


class _CompatibilityModule(ModuleType):
    """Forward legacy monkeypatches to the module that owns each implementation."""

    _PATCH_TARGETS = {
        "build_signal_branches": ((_branches, "build_signal_branches"),),
        "run_signal_branches": ((_full, "run_signal_branches"),),
        "run_survey_with_fields": ((_full, "run_survey_with_fields"),),
        "simulate": ((_branches, "simulate"), (_survey, "simulate")),
    }

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for module, attribute in self._PATCH_TARGETS.get(name, ()):
            setattr(module, attribute, value)


sys.modules[__name__].__class__ = _CompatibilityModule


def main() -> None:
    """Run the legacy AI-workflow CLI."""
    import argparse

    parser = argparse.ArgumentParser(description="Alpha Operator Framework (AI-friendly)")
    parser.add_argument("--region", default="EUR")
    parser.add_argument("--universe", default="TOP2500")
    parser.add_argument("--delay", type=int, default=1)
    parser.add_argument("--dataset", default="")
    parser.add_argument("--fields", nargs="*", help="指定字段ID列表")
    parser.add_argument("--sample", type=int, default=80)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--min-sharpe", type=float, default=1.2)
    parser.add_argument(
        "--operator-min-trials",
        type=int,
        default=3,
        help="模板 operator 槽淘汰阈值: 零命中且样本充足(trials>=该值)的算子淘汰",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(
        run_full_workflow(
            region=args.region,
            universe=args.universe,
            delay=args.delay,
            dataset_id=args.dataset,
            field_ids=args.fields,
            sample_n=args.sample,
            top_n=args.top_n,
            min_sharpe=args.min_sharpe,
            operator_min_trials=args.operator_min_trials,
            execute=args.execute,
        )
    )
    print(
        json.dumps(
            {
                stage: {
                    "success": item.success,
                    "message": item.message,
                    "tasks_generated": item.tasks_generated,
                    "simulations_run": item.simulations_run,
                    "top_templates": len(item.top_templates),
                    "candidates": len(item.candidates),
                }
                for stage, item in result.items()
            },
            indent=2,
        )
    )


__all__ = [
    "SurveyConfig",
    "DeepenConfig",
    "SignalBranchConfig",
    "OptimizeConfig",
    "WorkflowResult",
    "build_signal_branches",
    "run_signal_branches",
    "run_survey_with_fields",
    "run_full_workflow",
    "main",
]


if __name__ == "__main__":
    main()
