from pathlib import Path

from alpha_operator_framework.research.field_loader import load_real_market_fields


def test_strict_scope_does_not_inject_unverified_base_fields(tmp_path: Path) -> None:
    fields = load_real_market_fields(
        region="EUR", universe="TOP2500", delay=1,
        custom_dir=tmp_path / "EUR" / "1" / "TOP2500",
        include_base_fields=False, allow_scope_fallback=False,
    )

    assert fields == []
