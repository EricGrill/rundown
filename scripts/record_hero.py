#!/usr/bin/env python3
"""Record the README hero GIF from the offline demo, without network or providers.

Drives `rd demo` with Textual's test pilot, captures one SVG per storyboard step,
then renders PNG frames with rsvg-convert and stitches a looping GIF with ffmpeg.

    python scripts/record_hero.py            # writes docs/images/tui-hero.gif
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.widgets import Input, TextArea

from rundown.demo import demo_environment
from rundown.tui import RundownApp

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "images" / "tui-hero.gif"
SIZE = (120, 34)
WIDTH = 1200

# (keys to press, seconds to hold the resulting frame, caption for maintainers)
STORYBOARD: tuple[tuple[tuple[str, ...], float, str], ...] = (
    ((), 2.5, "catalog with the first repository's host brief"),
    (("down",), 1.2, "move through the catalog"),
    (("down",), 1.2, ""),
    (("slash",), 0.8, "open the filter"),
    (("u",), 0.35, "type a query"),
    (("v",), 1.8, ""),
    (("enter",), 3.0, "read the uv host brief"),
    (("v",), 3.5, "switch to the research card"),
    (("v",), 0.8, "back to the host brief"),
    (("e",), 3.5, "prepare the card"),
    (("escape",), 0.8, ""),
    (("ctrl+p",), 2.5, "action menu"),
    (("escape",), 0.8, ""),
    (("x",), 3.0, "export to Markdown"),
    (("escape",), 1.5, "back to the catalog"),
)


def _freeze_cursors(app: RundownApp) -> None:
    for screen in app.screen_stack:
        for field in screen.query(Input):
            field.cursor_blink = False
        for editor in screen.query(TextArea):
            editor.cursor_blink = False


async def capture_frames() -> list[tuple[str, float]]:
    frames: list[tuple[str, float]] = []
    with patch("rundown.db.now_utc", return_value="2026-09-12T12:00:00+00:00"), demo_environment() as environment:
        app = RundownApp(environment.config, fetch_starred=environment.fetch_starred, demo_mode=True)
        async with app.run_test(size=SIZE) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.update_job_summary()
            for keys, hold, _caption in STORYBOARD:
                for key in keys:
                    await pilot.press(key)
                    await pilot.pause(0.2)
                if app.screen.query("#export-path"):
                    app.screen.query_one("#export-path", Input).value = "exports/rundown-export.md"
                _freeze_cursors(app)
                await pilot.pause(0.3)
                frames.append((app.export_screenshot(), hold))
    return frames


def render(frames: list[tuple[str, float]], output: Path) -> None:
    converter, ffmpeg = shutil.which("rsvg-convert"), shutil.which("ffmpeg")
    if converter is None or ffmpeg is None:
        raise SystemExit("record_hero.py requires rsvg-convert (librsvg) and ffmpeg")
    with TemporaryDirectory(prefix="rundown-hero-") as directory:
        temporary = Path(directory)
        concat = []
        for index, (svg, hold) in enumerate(frames):
            source, png = temporary / f"{index:03}.svg", temporary / f"{index:03}.png"
            source.write_text(svg, encoding="utf-8")
            subprocess.run([converter, "--width", str(WIDTH), str(source), "--output", str(png)], check=True)
            concat += [f"file '{png}'", f"duration {hold}"]
        # The concat demuxer ignores the final duration unless the last file repeats.
        concat.append(f"file '{temporary / f'{len(frames) - 1:03}.png'}'")
        listing = temporary / "frames.txt"
        listing.write_text("\n".join(concat) + "\n", encoding="utf-8")
        palette = temporary / "palette.png"
        base = [ffmpeg, "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]
        subprocess.run([*base, "-vf", "palettegen=max_colors=128:stats_mode=diff", str(palette)], check=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Variable frame timing stores each storyboard frame once instead of resampling.
        subprocess.run([*base, "-i", str(palette), "-lavfi", "paletteuse=dither=none:diff_mode=rectangle",
                        "-fps_mode", "vfr", "-loop", "0", str(output)], check=True)


def main() -> None:
    frames = asyncio.run(capture_frames())
    render(frames, OUTPUT)
    total = sum(hold for _svg, hold in frames)
    print(f"Wrote {OUTPUT.relative_to(ROOT)}: {len(frames)} frames, {total:.1f}s, {OUTPUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
