"""Regenerate or verify the public show pack without network or personal data."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

from rundown import db
from rundown.demo import demo_environment
from rundown.export import build_export, iter_export_rows

OUTPUT = Path(__file__).resolve().parents[1] / "examples" / "show-pack.md"
INTRO = """# Rundown Sample Show Pack

This is actual exporter output from the bundled offline demo, not live research.
The default selection includes repositories marked present or shortlist: Textual
and uv. Saved views are preserved: Textual uses Host Brief and uv uses Research
Card. Lazygit is not selected because its demo entry has no export decision.
Repository metrics and findings are illustrative fixtures, not current verified
facts. Only the generated timestamp is normalized below for reproducibility.

Regenerate from a development checkout with `python scripts/export_demo.py`.
Verify it with `python scripts/export_demo.py --check`. Neither command contacts
GitHub or an AI provider, or reads your personal catalog.

---

"""


def render_sample() -> str:
    with demo_environment() as environment:
        with db.session(environment.config.database_path) as conn:
            rows = list(iter_export_rows(conn))
            content = build_export(conn, rows, config=environment.config)
    content = re.sub(r"\*Generated [^\n]*\*", "*Generated from offline demo fixtures; timestamp omitted.*", content, count=1)
    return INTRO + content


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed example differs.")
    args = parser.parse_args()
    content = render_sample()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit("Show pack differs; run python scripts/export_demo.py")
        print("Verified show pack against the real exporter and demo fixtures.")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(content, encoding="utf-8")
        print(f"Generated {OUTPUT}")


if __name__ == "__main__":
    main()
