from pathlib import Path
import runpy


def test_committed_show_pack_matches_actual_demo_export():
    root = Path(__file__).resolve().parents[1]
    script = runpy.run_path(str(root / "scripts" / "export_demo.py"))
    rendered = script["render_sample"]()
    assert (root / "examples" / "show-pack.md").read_text(encoding="utf-8") == rendered
    assert "**2 repositories**" in rendered
    assert "## Textualize/textual" in rendered
    assert "## astral-sh/uv" in rendered
    assert "## jesseduffield/lazygit" not in rendered
