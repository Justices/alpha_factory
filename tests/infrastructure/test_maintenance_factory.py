"""Legacy maintenance commands are composed outside the CLI."""

from pathlib import Path

from alpha_operator_framework.database.init_db import init_database
from alpha_operator_framework.infrastructure.maintenance import storage_path


def test_storage_path_is_read_from_yaml(tmp_path: Path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text("storage:\n  driver: sqlite\n  path: state.db\n", encoding="utf-8")

    assert storage_path(config) == tmp_path / "state.db"


def test_storage_path_is_not_exposed_for_url_backed_storage(tmp_path: Path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text("storage:\n  database_type: mysql\n  driver: pymysql\n  connection_type: url\n  url: mysql+pymysql://user:pass@db/mps_ai\n", encoding="utf-8")

    assert storage_path(config) is None


def test_initialization_reports_a_sanitized_result(tmp_path: Path, capsys) -> None:
    success, _ = init_database(tmp_path / "state.db")

    assert success is True
    assert "initialized sqlite" in capsys.readouterr().out


def test_legacy_maintenance_commands_do_not_read_database_cli_argument() -> None:
    source = (Path(__file__).parents[2] / "alpha_operator_framework" / "cli" / "maintenance.py").read_text(encoding="utf-8")
    for name in ("command_init_db", "command_clean_db"):
        section = source[source.index(f"def {name}"):]
        next_function = section.find("\ndef ", 1)
        body = section if next_function < 0 else section[:next_function]
        assert "args.database" not in body


def test_simulation_commands_hide_database_implementation_from_cli() -> None:
    source = (Path(__file__).parents[2] / "alpha_operator_framework" / "cli" / "maintenance.py").read_text(encoding="utf-8")

    assert "sim.add_argument(\"--database\"" not in source
    assert "super_prepare.add_argument(\"--output\", required=True); super_prepare.add_argument(\"--database\"" not in source
    assert "from alpha_operator_framework.database import AlphaDatabase" not in source


def test_status_uses_storage_verification_instead_of_assuming_a_database_file() -> None:
    source = (Path(__file__).parents[2] / "alpha_operator_framework" / "cli" / "status.py").read_text(encoding="utf-8")

    assert "verify_storage(config_path)" in source
    assert "database_file is not None and not database_file.exists()" in source
    assert ".execute(" not in source


def test_recovery_drill_writes_the_standard_storage_shape() -> None:
    source = (Path(__file__).parents[2] / "alpha_operator_framework" / "cli" / "recovery.py").read_text(encoding="utf-8")

    assert "connection_type: file" in source
