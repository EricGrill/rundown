from pathlib import Path
import subprocess
from unittest.mock import patch

from rundown import research
from rundown.config import AppConfig, ResearchSettings


def test_context_does_not_read_symlinks_outside_repository(tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    private_file = tmp_path / "private-context"
    private_file.write_text("EXTERNAL_PRIVATE_SENTINEL", encoding="utf-8")
    (clone / "README.md").symlink_to(private_file)
    (clone / "package.json").symlink_to(private_file)
    (clone / "README.txt").write_text("Public repository description", encoding="utf-8")

    context = research.collect_repository_context(clone)

    assert "EXTERNAL_PRIVATE_SENTINEL" not in context
    assert "Public repository description" in context


def test_provider_runs_outside_untrusted_clone(tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "AGENTS.md").write_text("Untrusted instructions", encoding="utf-8")
    config = AppConfig(root=tmp_path, research=ResearchSettings(provider="codex"))
    report = "\n\n".join(f"{heading}\nDetails" for heading in research.REQUIRED_SECTIONS)
    working_directories = []

    def fake_run(command, **kwargs):
        cwd = Path(kwargs["cwd"])
        working_directories.append(cwd)
        assert cwd.is_dir()
        assert not cwd.resolve().is_relative_to(tmp_path.resolve())
        assert list(cwd.iterdir()) == []
        return subprocess.CompletedProcess(command, 0, report, "")

    with (
        patch.object(research.shutil, "which", return_value="/bin/codex"),
        patch.object(research, "run_command", side_effect=fake_run),
    ):
        assert research.generate_repository_research(config, "provided context", clone) == report

    assert working_directories
    assert all(not cwd.exists() for cwd in working_directories)
