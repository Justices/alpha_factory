"""Autopilot command adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from alpha_operator_framework.application.autopilot import run_autopilot

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "alpha-factory.yaml"


def command_auto_pilot(args: object) -> None:
    config_path = Path(getattr(args, "config", DEFAULT_CONFIG_PATH))
    outcome = run_autopilot(args, config_path)
    output = getattr(args, "output", None)
    if output:
        report = Path(output)
    else:
        report = Path("runs") / "reports" / f"autopilot_summary_{datetime.now():%Y%m%d_%H%M%S}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    approved = outcome["approved"]
    lines = ["# Alpha Factory Auto-Pilot Summary", "", outcome["research"], "", f"approved={len(approved)}"]
    lines.extend(f"- {row['alpha_id']}: Sharpe={row['sharpe']:.2f}, Fitness={row['fitness']:.2f}" for row in approved)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"approved={len(approved)} report={report}")
