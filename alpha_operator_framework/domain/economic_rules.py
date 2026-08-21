"""Conservative economic admissibility rules for generic first-order signals."""

from __future__ import annotations

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.domain.operators import basic_ops, ts_ops


def infer_economic_type(field: FieldSpec) -> str:
    """Infer only high-confidence field classes; unknown preserves full exploration."""
    if field.economic_type:
        return field.economic_type.lower()
    text = f"{field.id} {field.name} {field.description}".lower()
    if "return" in text:
        return "return"
    if any(token in text for token in ("volume", "turnover", "traded value")):
        return "volume"
    if any(token in text for token in ("revenue", "sales", "earnings", "income", "cash flow")):
        return "fundamental_flow"
    if any(token in text for token in ("asset", "liabilit", "book value", "market cap")):
        return "fundamental_stock"
    return ""


def allowed_first_order_ops(field: FieldSpec) -> list[str]:
    """Return economically admissible generic operators for one field.

    Unknown metadata deliberately returns the current complete operator set.
    """
    economic_type = infer_economic_type(field)
    if not economic_type:
        return basic_ops + ts_ops

    signedness = (field.signedness or "").lower()
    scale = (field.scale or "").lower()
    allowed = list(basic_ops + ts_ops)
    if signedness not in ("positive",) or scale in ("ratio", "bounded") or economic_type == "return":
        allowed.remove("inverse")
    return allowed
