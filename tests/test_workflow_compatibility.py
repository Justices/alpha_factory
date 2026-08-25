from __future__ import annotations

import asyncio
from pathlib import Path


def test_legacy_and_new_workflow_exports_are_identical() -> None:
    import alpha_operator_framework as package
    import alpha_operator_framework.ai_workflow as legacy
    import alpha_operator_framework.workflow as workflow

    names = (
        "OptimizeConfig",
        "SurveyConfig",
        "DeepenConfig",
        "SignalBranchConfig",
        "WorkflowResult",
        "build_signal_branches",
        "run_signal_branches",
        "run_survey_with_fields",
        "run_full_workflow",
    )
    for name in names:
        assert getattr(legacy, name) is getattr(workflow, name)
        assert getattr(package, name) is getattr(workflow, name)


def test_legacy_survey_monkeypatch_is_seen_by_full_workflow(monkeypatch) -> None:
    import alpha_operator_framework.ai_workflow as legacy
    from alpha_operator_framework.domain.fields import FieldSpec

    expected = legacy.WorkflowResult(success=True, stage="survey", message="offline")
    calls: list[tuple[object, object, bool]] = []

    async def fake_survey(field_specs, config, output_dir=Path("runs"), execute=False, database=None):
        calls.append((field_specs, config, execute))
        return expected

    monkeypatch.setattr(legacy, "run_survey_with_fields", fake_survey)
    specs = [FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=1.0)]
    result = asyncio.run(
        legacy.run_full_workflow(
            region="USA",
            universe="TOP3000",
            field_specs=specs,
            execute=False,
        )
    )

    assert result == {"survey": expected}
    assert len(calls) == 1
    assert calls[0][0] is specs
    assert calls[0][2] is False


def test_workflow_modules_have_single_responsibilities() -> None:
    from alpha_operator_framework.workflow import branches, full, models, survey

    assert models.SurveyConfig.__module__ == "alpha_operator_framework.workflow.models"
    assert branches.build_signal_branches.__module__ == "alpha_operator_framework.workflow.branches"
    assert survey.run_survey_with_fields.__module__ == "alpha_operator_framework.workflow.survey"
    assert full.run_full_workflow.__module__ == "alpha_operator_framework.workflow.full"
