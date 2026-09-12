#!/usr/bin/env python3
"""Check deterministic TUI snapshots and regenerate README images."""

from __future__ import annotations

import argparse
import asyncio
import difflib
import os
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

# Keep golden colors independent of an operator's shell preferences.
os.environ.pop("NO_COLOR", None)

from textual.command import CommandList
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Input, Static, TextArea

from rundown.demo import demo_environment
from rundown.tui import RundownApp
from rundown.startup import WelcomeApp

ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = ROOT / "tests" / "snapshots" / "tui"
README_IMAGES = {
    "catalog": "tui-catalog.png",
    "search": "tui-search.png",
    "menu": "tui-menu.png",
    "host": "tui-host-brief.png",
    "research": "tui-research-card.png",
    "prepare": "tui-prepare.png",
    "export": "tui-export.png",
    "template-modal": "tui-template.png",
    "welcome": "tui-welcome.png",
}
CASES: tuple[tuple[str, tuple[int, int], tuple[str, ...]], ...] = (
    ("prepare", (140, 36), ("e",)),
    ("compact-prepare", (80, 24), ("e",)),
    ("export", (140, 36), ("x",)),
    ("compact-export", (80, 24), ("x",)),
    ("catalog", (140, 30), ()),
    ("search", (140, 30), ("/", "python")),
    ("menu", (140, 30), ("ctrl+p",)),
    ("host", (160, 46), ()),
    ("research", (160, 46), ("v",)),
    ("compact-reader", (80, 30), ("enter",)),
    ("template-modal", (140, 36), ("t",)),
    ("catalog-modal", (140, 36), ("g",)),
    ("jobs-modal", (140, 36), ("j",)),
    ("compact-template-modal", (80, 30), ("t",)),
    ("compact-catalog-modal", (80, 30), ("g",)),
    ("compact-jobs-modal", (80, 30), ("j",)),
)


def normalize_svg(svg: str) -> str:
    """Remove exporter identifiers while retaining every rendered cell."""

    svg = re.sub(r"terminal-\d+", "terminal-SNAPSHOT", svg)
    return "\n".join(line.rstrip() for line in svg.splitlines()).rstrip() + "\n"


def _svg_diff_lines(svg: str) -> list[str]:
    """Split rendered SVG into tags so snapshot failures remain readable in CI."""

    return re.sub(r">\s*<", ">\n<", svg).splitlines(keepends=True)


async def _wait_for_palette(app: RundownApp, pilot) -> None:
    for _ in range(100):
        await asyncio.sleep(0.01)
        await pilot.pause()
        lists = app.screen.query(CommandList)
        if lists and lists.first().option_count:
            return
    raise AssertionError("command palette did not populate")


async def _capture_case(size: tuple[int, int], keys: tuple[str, ...]) -> str:
    with demo_environment() as environment:
        app = RundownApp(
            environment.config,
            fetch_starred=environment.fetch_starred,
            demo_mode=True,
        )
        async with app.run_test(size=size) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            # The app refreshes this label on a wall-clock timer. Set the same
            # state explicitly so capture speed can't change the screenshot.
            app.update_job_summary()
            await pilot.pause()
            table = app.query_one("#repos", DataTable)
            reader = app.query_one("#reader", VerticalScroll)
            status = app.query_one("#status", Static)
            assert table.row_count == 3
            if size[0] >= 100:
                assert table.region.right <= reader.region.x
            assert reader.region.bottom <= status.region.y

            for key in keys:
                if len(key) > 1 and key not in {"ctrl+p", "enter"}:
                    await pilot.press(*key)
                else:
                    await pilot.press(key)
                if key == "ctrl+p":
                    await _wait_for_palette(app, pilot)
                await pilot.pause()

            if app.screen.query("#export-path"):
                app.screen.query_one("#export-path", Input).value = "/tmp/rundown-demo/exports/rundown-export.md"
            # Input cursor blink is wall-clock driven, so freeze it for captures.
            for screen in app.screen_stack:
                for field in screen.query(Input):
                    field.cursor_blink = False
                for editor in screen.query(TextArea):
                    editor.cursor_blink = False
            await pilot.pause()

            for selector in ("#template-dialog", "#catalog-dialog", "#jobs-dialog", "#card-edit-dialog", "#export-dialog"):
                dialogs = app.screen.query(selector)
                if dialogs:
                    dialog = dialogs.first()
                    assert dialog.region.x >= 0 and dialog.region.y >= 0
                    assert dialog.region.right <= app.size.width
                    assert dialog.region.bottom <= app.size.height

            return normalize_svg(app.export_screenshot())


async def capture_all() -> dict[str, str]:
    captures: dict[str, str] = {}
    for name, size, keys in CASES:
        captures[name] = await _capture_case(size, keys)
    welcome = WelcomeApp()
    async with welcome.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        captures["welcome"] = normalize_svg(welcome.export_screenshot())
    return captures


def _compare(captures: dict[str, str], baseline_dir: Path) -> None:
    failures: list[str] = []
    for name, actual in captures.items():
        path = baseline_dir / f"{name}.svg"
        if not path.is_file():
            failures.append(f"missing baseline: {path}")
            continue
        expected = path.read_text(encoding="utf-8")
        if expected != actual:
            diff = "".join(
                difflib.unified_diff(
                    _svg_diff_lines(expected),
                    _svg_diff_lines(actual),
                    fromfile=str(path),
                    tofile=f"current:{name}",
                    n=2,
                )
            )
            failures.append(diff[:4000])
    if failures:
        raise SystemExit(
            "TUI snapshots changed. Review the UI, then run "
            "`python scripts/capture_tui.py --update-baselines --png`.\n\n"
            + "\n\n".join(failures)
        )


def _write_svgs(captures: dict[str, str], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, svg in captures.items():
        (directory / f"{name}.svg").write_text(svg, encoding="utf-8")


def _write_pngs(captures: dict[str, str]) -> None:
    converter = shutil.which("rsvg-convert")
    if converter is None:
        raise SystemExit("--png requires rsvg-convert (provided by librsvg)")
    image_dir = ROOT / "docs" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="rundown-screenshots-") as directory:
        temporary = Path(directory)
        for case, filename in README_IMAGES.items():
            source = temporary / f"{case}.svg"
            source.write_text(captures[case], encoding="utf-8")
            subprocess.run(
                [converter, str(source), "--output", str(image_dir / filename)],
                check=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=BASELINE_DIR,
        help="Golden SVG directory (default: tests/snapshots/tui).",
    )
    parser.add_argument(
        "--update-baselines",
        action="store_true",
        help="Accept the current reviewed UI as the new golden snapshots.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Also write the current normalized SVG captures here.",
    )
    parser.add_argument(
        "--png",
        action="store_true",
        help="Regenerate the five README PNGs (requires rsvg-convert).",
    )
    args = parser.parse_args()
    captures = asyncio.run(capture_all())
    if args.output_dir is not None:
        # Preserve the actual render even when comparison exits with a failure.
        _write_svgs(captures, args.output_dir)
    if args.update_baselines:
        _write_svgs(captures, args.baseline_dir)
    else:
        _compare(captures, args.baseline_dir)
    if args.png:
        _write_pngs(captures)
    print(f"Verified {len(captures)} deterministic TUI snapshots.")


if __name__ == "__main__":
    main()
