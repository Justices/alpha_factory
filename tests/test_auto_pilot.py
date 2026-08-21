"""Test Auto-Pilot End-to-End Pipeline."""

import argparse
from pathlib import Path
from alpha_machine import command_auto_pilot
from alpha_operator_framework.database.init_db import init_database


def test_auto_pilot_dry_run(tmp_path):
    """Test auto-pilot dry-run execution and report generation."""
    db_file = tmp_path / "test_research.db"
    report_file = tmp_path / "summary.md"
    init_database(db_path=db_file)

    args = argparse.Namespace(
        region="GBR",
        universe="TOP700",
        delay=1,
        datasets="analyst7",
        paper=None,
        sample_per_family=1,
        batch_size=2,
        decay=12,
        neutralization="SUBINDUSTRY",
        truncation=0.08,
        min_sharpe=1.25,
        min_fitness=1.0,
        execute=False,
        no_clean=True,
        database=str(db_file),
        output=str(report_file),
    )

    command_auto_pilot(args)

    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "Alpha Factory 无人值守投研报告" in content


def test_auto_pilot_does_not_convert_non_ready_grade_to_ready_verdict():
    """IS rows only receive a READY verdict when the stored review grade is READY."""
    from alpha_machine import judge_verdict_from_grade

    assert judge_verdict_from_grade("READY") == "READY"
    assert judge_verdict_from_grade("REJECTED") is None
    assert judge_verdict_from_grade(None) is None
