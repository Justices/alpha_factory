"""Autopilot use case, isolated from the command-line adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_autopilot(args: Any, config_path: Path) -> dict[str, Any]:
    """Run research, evidence review and optional storage maintenance."""
    from alpha_operator_framework.domain.evidence import EvidenceLevel, SubmissionApprovalEngine
    from alpha_operator_framework.infrastructure.maintenance import clean_storage, initialize_storage, open_alpha_database, storage_path, verify_storage

    if not verify_storage(config_path):
        initialize_storage(config_path, reset=False)
    if getattr(args, "paper", None):
        from alpha_operator_framework.research import run_literature_research_pipeline
        result = run_literature_research_pipeline(literature_source=args.paper, region=args.region, universe=args.universe, neutralization=args.neutralization, delay=args.delay, decay=args.decay, datasets=[item.strip() for item in args.datasets.split(",") if item.strip()] if getattr(args, "datasets", None) else None, execute_on_platform=args.execute, database_path=storage_path(config_path), save_to_db=True, output_report_path=None)
    else:
        from alpha_operator_framework.carpet_mining import run_stratified_carpet_mining
        result = run_stratified_carpet_mining(region=args.region, universe=args.universe, datasets=[item.strip() for item in args.datasets.split(",") if item.strip()] if getattr(args, "datasets", None) else None, sample_per_family=args.sample_per_family, batch_size=args.batch_size, delay=args.delay, decay=args.decay, neutralization=args.neutralization, truncation=args.truncation, execute=args.execute, seed=getattr(args, "seed", None), output_report_path=None)
    database = open_alpha_database(config_path)
    approved: list[dict[str, Any]] = []
    try:
        for row in database.get_top_performing_alphas(min_sharpe=args.min_sharpe, min_fitness=args.min_fitness):
            checks = [{"name": check.check_name, "result": check.result, "value": check.value} for check in database.get_alpha_checks(row["alpha_id"])]
            review = SubmissionApprovalEngine.evaluate(alpha_id=row["alpha_id"], evidence_level=EvidenceLevel.PLATFORM_IS, is_metrics={key: row[key] for key in ("sharpe", "fitness", "turnover", "margin")}, checks=checks, sc_value=row["sc_value"], pc_value=row["pc_value"], judge_verdict="READY")
            database.update_wf_stage(row["alpha_id"], "submission_ready" if review.approved else "needs_optimization")
            if review.approved: approved.append(row)
    finally:
        database.close()
    if args.execute and not getattr(args, "no_clean", False):
        clean_storage(config_path, mode="stale", dry_run=False, vacuum=True)
    return {"research": result.summary_markdown(), "approved": approved}
