"""Locate benchmark binaries and record their provenance."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .util import BIN_DIR, sha256_file


def bin_dir(lang: str, flavor: str = "") -> Path:
    return BIN_DIR / (f"{lang}-{flavor}" if flavor else lang)


def bin_path(lang: str, name: str, flavor: str = "") -> Path:
    return bin_dir(lang, flavor) / name


def _cmd(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def describe_binary(path: Path) -> dict:
    """Size, hash, toolchain stamps (.comment section) and dynamic deps."""
    info: dict = {"path": str(path.relative_to(BIN_DIR.parent)) if path.is_relative_to(BIN_DIR.parent) else str(path)}
    if not path.exists():
        info["missing"] = True
        return info
    info["bytes"] = path.stat().st_size
    info["sha256"] = sha256_file(path)
    comment = _cmd(["readelf", "-p", ".comment", str(path)])
    info["elf_comment"] = [
        line.split("]", 1)[1].strip() for line in comment.splitlines() if "]" in line and line.strip().startswith("[")
    ]
    ldd = _cmd(["ldd", str(path)])
    info["dynamic"] = "not a dynamic executable" not in ldd and "statically linked" not in ldd
    info["ldd"] = [line.strip() for line in ldd.splitlines() if line.strip()]
    return info


def build_manifest() -> dict:
    """Describe every built binary under bin/."""
    out: dict = {}
    if not BIN_DIR.exists():
        return out
    for d in sorted(p for p in BIN_DIR.iterdir() if p.is_dir()):
        for f in sorted(p for p in d.iterdir() if p.is_file()):
            out[f"{d.name}/{f.name}"] = describe_binary(f)
    return out
