"""Shared helpers: repository paths, size parsing, JSON I/O, logging."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = ROOT / "bin"
DATASETS_DIR = ROOT / "datasets"
RESULTS_DIR = ROOT / "results"
RAW_DIR = RESULTS_DIR / "raw"
PROCESSED_DIR = RESULTS_DIR / "processed"
CHARTS_DIR = ROOT / "charts"
SCRATCH_DIR = ROOT / "scratch"
TOOLS_DIR = ROOT / "tools"

LANGS = ("go", "rust")

_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(B|KiB|MiB|GiB|KB|MB|GB)$")
_SIZE_MULT = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30, "KB": 10**3, "MB": 10**6, "GB": 10**9}


def parse_size(value: str) -> int | None:
    """'100MiB' -> 104857600; returns None when value is not a size string."""
    m = _SIZE_RE.match(value.strip())
    if not m:
        return None
    return int(float(m.group(1)) * _SIZE_MULT[m.group(2)])


def human_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def human_ns(ns: float) -> str:
    if ns < 1e3:
        return f"{ns:.0f} ns"
    if ns < 1e6:
        return f"{ns / 1e3:.2f} µs"
    if ns < 1e9:
        return f"{ns / 1e6:.2f} ms"
    return f"{ns / 1e9:.3f} s"


def parse_cpuset(spec: str) -> list[int]:
    """'0-2,5' -> [0, 1, 2, 5]."""
    cpus: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            cpus.extend(range(int(a), int(b) + 1))
        else:
            cpus.append(int(part))
    return sorted(set(cpus))


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def new_run_id(mode: str) -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    host = re.sub(r"[^A-Za-z0-9]+", "", socket.gethostname())[:16] or "host"
    return f"{stamp}-{mode}-{host}"


def write_json(path: Path, obj: Any, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=indent, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def which(tool: str) -> str | None:
    local = TOOLS_DIR / "bin" / tool
    if local.exists() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which(tool)


_COLOR = sys.stderr.isatty()


def log(msg: str, *, level: str = "info") -> None:
    prefix = {"info": "", "warn": "WARNING: ", "error": "ERROR: "}[level]
    if _COLOR and level != "info":
        code = "33" if level == "warn" else "31"
        prefix = f"\033[{code}m{prefix}\033[0m"
    print(prefix + msg, file=sys.stderr, flush=True)


def die(msg: str, code: int = 1) -> None:
    log(msg, level="error")
    raise SystemExit(code)
