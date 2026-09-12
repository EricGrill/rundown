#!/usr/bin/env python3
"""Verify release filenames, metadata, and bundled demo assets."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

import tomllib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path)
    args = parser.parse_args()
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    wheel = args.dist / f"rundown-{version}-py3-none-any.whl"
    source = args.dist / f"rundown-{version}.tar.gz"
    if not wheel.is_file() or not source.is_file():
        raise SystemExit(f"Expected {wheel.name} and {source.name}")

    fixture_suffix = "rundown/demo_data/repositories.json"
    with zipfile.ZipFile(wheel) as archive:
        wheel_files = set(archive.namelist())
        metadata_name = next(name for name in wheel_files if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
        package_init = archive.read("rundown/__init__.py").decode("utf-8")
    if fixture_suffix not in wheel_files:
        raise SystemExit(f"Wheel is missing {fixture_suffix}")
    if f"Version: {version}\n" not in metadata or f'__version__ = "{version}"' not in package_init:
        raise SystemExit("Wheel metadata and package version must match pyproject.toml")

    with tarfile.open(source, "r:gz") as archive:
        source_files = {member.name for member in archive.getmembers()}
    if not any(name.endswith(fixture_suffix) for name in source_files):
        raise SystemExit(f"Source distribution is missing {fixture_suffix}")


if __name__ == "__main__":
    main()
