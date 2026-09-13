import asyncio
from unittest.mock import Mock

import pytest
from textual.app import App
from textual.widgets import Checkbox, Input, Static

from rundown.export_ui import ExportScreen, write_export_file


def test_export_never_overwrites_without_explicit_choice(tmp_path):
    path = tmp_path / "show.md"
    path.write_text("original")
    with pytest.raises(FileExistsError):
        write_export_file(path, "replacement")
    assert path.read_text() == "original"
    write_export_file(path, "replacement", overwrite=True)
    assert path.read_text() == "replacement"


def test_demo_paths_and_database_are_protected(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    with pytest.raises(ValueError, match="temporary"):
        write_export_file(tmp_path / "outside.md", "content", allowed_root=root)
    database = root / "catalog.sqlite"
    database.write_text("database")
    with pytest.raises(ValueError, match="database"):
        write_export_file(database, "content", overwrite=True, protected_path=database)
    assert database.read_text() == "database"
    assert not (tmp_path / "outside.md").exists()


def test_symlink_export_does_not_change_target(tmp_path):
    target = tmp_path / "real.md"
    target.write_text("original")
    link = tmp_path / "link.md"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic"):
        write_export_file(link, "new", overwrite=True)
    assert target.read_text() == "original"


def test_export_modal_keeps_draft_on_error_and_cancel_never_submits(tmp_path):
    class ExportApp(App):
        def on_mount(self):
            self.push_screen(screen)
    submit = Mock(side_effect=FileExistsError("Choose another name"))
    screen = ExportScreen("owner/repo", tmp_path / "show.md", submit)
    async def run():
        app = ExportApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("ctrl+s")
            assert "Choose another name" in str(screen.query_one("#export-error", Static).render())
            assert screen.query_one("#export-path", Input).value.endswith("show.md")
            assert not screen.query_one(Checkbox).value
            await pilot.press("escape")
        submit.assert_called_once()
    asyncio.run(run())


def test_failed_atomic_install_preserves_original_and_cleans_temporary(tmp_path):
    from unittest.mock import patch

    path = tmp_path / "show.md"
    path.write_text("original")
    with patch("rundown.export.os.replace", side_effect=OSError("disk error")):
        with pytest.raises(OSError, match="disk error"):
            write_export_file(path, "replacement", overwrite=True)
    assert path.read_text() == "original"
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_creation_never_replaces_a_concurrent_writer(tmp_path):
    from unittest.mock import patch

    path = tmp_path / "show.md"

    def concurrent_writer(source, destination):
        destination.write_text("another writer")
        raise FileExistsError("concurrent writer")

    with patch("rundown.export.os.link", side_effect=concurrent_writer):
        with pytest.raises(FileExistsError):
            write_export_file(path, "our export")
    assert path.read_text() == "another writer"
    assert list(tmp_path.iterdir()) == [path]
