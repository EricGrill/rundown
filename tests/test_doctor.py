import sqlite3
import subprocess
from pathlib import Path

from rundown import db
from rundown.doctor import run_doctor


def _write_config(tmp_path: Path, database: str = "./data/rundown.sqlite") -> Path:
    path = tmp_path / "config" / "rundown.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f'[paths]\ndatabase = "{database}"\n', encoding="utf-8")
    return path


def test_doctor_reports_healthy_tools_config_and_database(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    database = tmp_path / "data" / "rundown.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)

    monkeypatch.setattr(
        "rundown.doctor.shutil.which",
        lambda name: f"/tools/{name}",
    )

    def run(command, **_kwargs):
        if command[-2:] == ["auth", "status"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, f"{Path(command[0]).name} 1.0\n", "")

    monkeypatch.setattr("rundown.doctor.subprocess.run", run)

    report = run_doctor(config_path)

    assert report.healthy
    assert report.exit_code == 0
    assert {check.name for check in report.checks} == {
        "Python",
        "git",
        "gh",
        "GitHub authentication",
        "Configuration",
        "Research provider",
        "Database",
    }
    assert next(check for check in report.checks if check.name == "Database").status == "ok"
    provider = next(check for check in report.checks if check.name == "Research provider")
    assert "Authentication was not probed" in provider.message


def test_doctor_missing_config_has_failure_exit_without_provider_calls(tmp_path, monkeypatch):
    monkeypatch.setattr("rundown.doctor.shutil.which", lambda _name: None)

    report = run_doctor(tmp_path / "missing.toml")

    assert not report.healthy
    assert report.exit_code == 1
    config = next(check for check in report.checks if check.name == "Configuration")
    assert config.status == "error"
    assert "does not exist" in config.message


def test_doctor_reports_invalid_config_and_does_not_expose_contents(tmp_path, monkeypatch):
    config_path = tmp_path / "bad.toml"
    config_path.write_text('[research]\nprovider = "secret-value"\nbroken = [', encoding="utf-8")
    monkeypatch.setattr("rundown.doctor.shutil.which", lambda _name: None)

    report = run_doctor(config_path)

    check = next(item for item in report.checks if item.name == "Configuration")
    assert check.status == "error"
    assert "secret-value" not in check.message


def test_doctor_reports_corrupt_database(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    database = tmp_path / "data" / "rundown.sqlite"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"not a sqlite database")
    monkeypatch.setattr("rundown.doctor.shutil.which", lambda _name: None)

    report = run_doctor(config_path)

    check = next(item for item in report.checks if item.name == "Database")
    assert check.status == "error"
    assert "SQLite could not read" in check.message
    assert report.exit_code == 1


def test_doctor_does_not_create_a_missing_database(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    database = tmp_path / "data" / "rundown.sqlite"
    monkeypatch.setattr("rundown.doctor.shutil.which", lambda _name: None)

    report = run_doctor(config_path)

    assert not database.exists()
    check = next(item for item in report.checks if item.name == "Database")
    assert check.status == "warning"


def test_read_only_integrity_check_does_not_modify_database(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    database = tmp_path / "data" / "rundown.sqlite"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE sample (value TEXT)")
    before = database.stat().st_mtime_ns
    monkeypatch.setattr("rundown.doctor.shutil.which", lambda _name: None)

    run_doctor(config_path)

    assert database.stat().st_mtime_ns == before
