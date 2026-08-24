from __future__ import annotations

from alpha_operator_framework.application.status_dashboard import build_status_dashboard


def test_status_dashboard_delegates_all_database_aggregation_to_repository() -> None:
    class Repository:
        def dashboard_snapshot(self):
            return {"expression_status": {"completed": 2}, "simulation": {"total": 3}, "workflow_status": {}, "submission_ready": [], "templates": []}

    assert build_status_dashboard(Repository())["simulation"]["total"] == 3
