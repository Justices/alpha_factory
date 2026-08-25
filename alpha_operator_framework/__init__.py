"""Alpha Operator Framework public package API."""

from importlib import import_module
from typing import Any

from alpha_operator_framework._lazy_exports import EXPORTS

__version__ = "0.1.0"
__all__ = sorted(EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve and cache one public export on first access."""
    target = EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute = target
    module = import_module(module_name)
    value = module if attribute is None else getattr(module, attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include lazily advertised exports in package introspection."""
    return sorted(set(globals()) | set(__all__))
