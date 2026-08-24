"""Legacy maintenance commands are composed outside the CLI."""

from pathlib import Path

from alpha_operator_framework.infrastructure.maintenance import storage_path


def test_storage_path_is_read_from_yaml(tmp_path: Path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text("storage:\n  driver: sqlite\n  path: state.db\n", encoding="utf-8")

    assert storage_path(config) == tmp_path / "state.db"


def test_legacy_maintenance_commands_do_not_read_database_cli_argument() -> None:
    source = (Path(__file__).parents[2] / "alpha_machine.py").read_text(encoding="utf-8")
    for name in ("command_status", "command_init_db", "command_clean_db"):
        section = source[source.index(f"def {name}"):]
        next_function = section.find("\ndef ", 1)
        body = section if next_function < 0 else section[:next_function]
        assert "args.database" not in body


def test_simulation_commands_hide_database_implementation_from_cli() -> None:
    source = (Path(__file__).parents[2] / "alpha_machine.py").read_text(encoding="utf-8")

    assert "sim.add_argument(\"--database\"" not in source
    assert "super_prepare.add_argument(\"--output\", required=True); super_prepare.add_argument(\"--database\"" not in source
    assert "from alpha_operator_framework.database import AlphaDatabase" not in source
