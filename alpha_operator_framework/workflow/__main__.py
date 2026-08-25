"""Workflow package command entry."""

from __future__ import annotations

import asyncio
import json

from .full import run_full_workflow


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Alpha Operator Framework workflow")
    parser.add_argument("--region", default="EUR")
    parser.add_argument("--universe", default="TOP2500")
    parser.add_argument("--delay", type=int, default=1)
    parser.add_argument("--dataset", default="")
    parser.add_argument("--fields", nargs="*")
    parser.add_argument("--sample", type=int, default=80)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--min-sharpe", type=float, default=1.2)
    parser.add_argument("--operator-min-trials", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_full_workflow(region=args.region, universe=args.universe, delay=args.delay, dataset_id=args.dataset, field_ids=args.fields, sample_n=args.sample, top_n=args.top_n, min_sharpe=args.min_sharpe, operator_min_trials=args.operator_min_trials, execute=args.execute))
    print(json.dumps({stage: {"success": item.success, "message": item.message, "tasks_generated": item.tasks_generated, "simulations_run": item.simulations_run, "top_templates": len(item.top_templates), "candidates": len(item.candidates)} for stage, item in result.items()}, indent=2))


if __name__ == "__main__":
    main()
