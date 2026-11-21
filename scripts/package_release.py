#!/usr/bin/env python3
"""Build source release archives for Windows, macOS, and Linux."""
from __future__ import annotations

import argparse
import re
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PLATFORM_FILES = {
    "windows": ["app", "PLATFORMS.md", "install.ps1", "一键安装.cmd"],
    "macos": ["app", "PLATFORMS.md", "install.sh", "fsd-mitm"],
    "linux": ["app", "PLATFORMS.md", "install.sh", "fsd-mitm"],
}
WINDOWS_ONLY_SUFFIXES = {".ps1", ".cmd", ".bat"}


def _include(name: str, platform: str) -> bool:
    path = PurePosixPath(name)
    parts = path.parts
    if any(parts[index:index + 2] == ("app", "certs2") for index in range(len(parts) - 1)):
        return False
    if platform != "windows" and path.suffix.lower() in WINDOWS_ONLY_SUFFIXES:
        return False
    return True


def _write_zip(source: tarfile.TarFile, output: Path) -> None:
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for member in source:
            if not _include(member.name, "windows") or not member.isfile():
                continue
            contents = source.extractfile(member)
            if contents is None:
                continue
            info = zipfile.ZipInfo(member.name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (member.mode & 0xFFFF) << 16
            archive.writestr(info, contents.read())


def _write_tar_gz(source: tarfile.TarFile, output: Path, platform: str) -> None:
    with tarfile.open(output, "w:gz", compresslevel=9) as archive:
        for member in source:
            if not _include(member.name, platform):
                continue
            contents = source.extractfile(member) if member.isfile() else None
            archive.addfile(member, contents)


def build(platform: str, version: str, output_dir: Path) -> Path:
    archive_name = f"Tesla-drug-{platform}-{version}"
    prefix = f"{archive_name}/"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / (f"{archive_name}.zip" if platform == "windows" else f"{archive_name}.tar.gz")

    with tempfile.TemporaryDirectory() as temporary_dir:
        source_path = Path(temporary_dir) / "source.tar"
        command = ["git", "archive", "--format=tar", f"--prefix={prefix}", "HEAD", *PLATFORM_FILES[platform]]
        with source_path.open("wb") as source_file:
            subprocess.run(command, cwd=ROOT, stdout=source_file, check=True)
        with tarfile.open(source_path, "r:") as source:
            if platform == "windows":
                _write_zip(source, output)
            else:
                _write_tar_gz(source, output, platform)

    if platform == "windows":
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            modes = {item.filename: item.external_attr >> 16 for item in archive.infolist()}
    else:
        with tarfile.open(output, "r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            modes = {member.name: member.mode for member in members}

    required = ["PLATFORMS.md", "app/cli.py", "app/requirements.txt"]
    required += ["install.ps1", "一键安装.cmd"] if platform == "windows" else ["install.sh", "fsd-mitm"]
    missing = [item for item in required if not any(name.endswith(item) for name in names)]
    invalid_unix = platform != "windows" and any(Path(name).suffix.lower() in WINDOWS_ONLY_SUFFIXES for name in names)
    scripts_executable = platform == "windows" or all(
        next((mode for name, mode in modes.items() if name.endswith(script)), 0) & 0o111
        for script in ("install.sh", "fsd-mitm")
    )
    if missing or invalid_unix or not scripts_executable or any("/certs2/" in f"/{name}" for name in names):
        output.unlink(missing_ok=True)
        raise RuntimeError(f"package validation failed: {output}; missing={missing}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="release tag or snapshot label")
    parser.add_argument("--platform", choices=PLATFORM_FILES, action="append", help="default: build all platforms")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", args.version):
        parser.error("version must contain only letters, numbers, dot, underscore, plus, or hyphen")

    for platform in args.platform or PLATFORM_FILES:
        print(build(platform, args.version, args.output_dir.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
