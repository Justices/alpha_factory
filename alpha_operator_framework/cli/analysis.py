"""Literature research and carpet-mining command adapters."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "alpha-factory.yaml"


def _datasets(args: Namespace) -> list[str] | None:
    raw = getattr(args, "datasets", None)
    return [item.strip() for item in raw.split(",") if item.strip()] if raw else None


def command_research(args: Namespace) -> None:
    from alpha_operator_framework.research import run_literature_research_pipeline

    result = run_literature_research_pipeline(
        literature_source=args.paper, region=args.region, universe=getattr(args, "universe", None),
        neutralization=getattr(args, "neutralization", "SUBINDUSTRY"), delay=getattr(args, "delay", 1),
        decay=int(getattr(args, "decay", 8)), datasets=_datasets(args), use_llm=getattr(args, "use_llm", False),
        provider=getattr(args, "provider", None), model=getattr(args, "model", None),
        execute_on_platform=False, config_path=Path(getattr(args, "config", DEFAULT_CONFIG_PATH)),
        save_to_db=True, output_report_path=getattr(args, "output", None),
    )
    print(result.summary_markdown())


def command_mine(args: Namespace) -> None:
    from alpha_operator_framework.carpet import run_stratified_carpet_mining

    result = run_stratified_carpet_mining(
        region=args.region, universe=args.universe, datasets=_datasets(args),
        sample_per_family=int(getattr(args, "sample_per_family", 4)), batch_size=int(getattr(args, "batch_size", 5)),
        delay=int(getattr(args, "delay", 1)), decay=int(getattr(args, "decay", 12)),
        neutralization=getattr(args, "neutralization", "SUBINDUSTRY"), truncation=float(getattr(args, "truncation", 0.08)),
        execute=getattr(args, "execute", False), seed=getattr(args, "seed", None), output_report_path=getattr(args, "output", None),
    )
    print(result.summary_markdown())
