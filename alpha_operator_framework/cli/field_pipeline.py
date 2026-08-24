"""Field discovery, task preparation, filtering and second-order CLI commands."""

# Temporary delegation while platform adapters are extracted from the former
# command module.  Router imports this module, so callers no longer target the
# former monolith directly.
from alpha_operator_framework.cli.legacy_machine import (
    command_discover,
    command_filter,
    command_prepare,
    command_second_order,
)

__all__ = ["command_discover", "command_prepare", "command_filter", "command_second_order"]
