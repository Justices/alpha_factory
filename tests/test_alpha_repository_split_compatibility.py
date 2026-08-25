"""Golden compatibility checks for the split AlphaRepository facade."""

from alpha_operator_framework.database import AlphaRepository as DatabaseAlphaRepository
from alpha_operator_framework.database.repositories import AlphaRepository as PackageAlphaRepository
from alpha_operator_framework.database.repositories.alpha import AlphaRepository
from alpha_operator_framework.database.repositories.alpha_analytics import AlphaAnalyticsMixin
from alpha_operator_framework.database.repositories.alpha_checks import AlphaChecksMixin
from alpha_operator_framework.database.repositories.alpha_query import AlphaQueryMixin
from alpha_operator_framework.database.repositories.alpha_write import AlphaWriteMixin


EXPECTED_METHOD_ALLOCATION = {
    AlphaWriteMixin: (
        "compute_sha",
        "compute_alpha_sha",
        "insert_expression",
        "upsert_expression_record",
        "catalog_expression",
        "catalog_tasks",
        "mark_expressions_pruned",
        "insert_alpha_detail",
        "update_alpha_status",
        "update_wf_stage",
        "mark_alpha_submitted",
        "mark_alpha_failed",
        "_upsert_detail",
    ),
    AlphaQueryMixin: (
        "get_expression_by_sha",
        "query_expressions",
        "sample_expressions_stratified",
        "_sample_by_batches_and_fields",
        "sample_catalog_expressions",
        "_sample_from_groups",
        "_pick_with_isomorphic_dedup",
    ),
    AlphaChecksMixin: (
        "check_array_to_rows",
        "_write_checks",
        "upsert_checks",
        "get_checks",
        "get_alpha_checks",
        "save_result_with_checks",
    ),
    AlphaAnalyticsMixin: (
        "query_alphas",
        "_row_to_detail",
        "get_candidates_for_super_alpha",
        "get_top_performing_alphas",
        "dashboard_snapshot",
        "get_total_alpha_details_count",
    ),
}


def test_alpha_repository_keeps_canonical_exports():
    assert DatabaseAlphaRepository is AlphaRepository
    assert PackageAlphaRepository is AlphaRepository


def test_alpha_repository_method_allocation_matches_golden():
    for owner, method_names in EXPECTED_METHOD_ALLOCATION.items():
        assert owner in AlphaRepository.__mro__
        for method_name in method_names:
            assert method_name in owner.__dict__
            assert method_name not in AlphaRepository.__dict__
