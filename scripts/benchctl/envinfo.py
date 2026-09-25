"""Capture the benchmark environment (hardware, OS, kernel settings,
toolchains, tools) so every result set documents the conditions it was
measured under."""

from __future__ import annotations

import json
import os
import platform
import resource
import subprocess
import sys
from pathlib import Path

from . import procmon
from .util import ROOT, now_iso, which


def _run(argv: list[str], cwd: Path | None = None, env: dict | None = None) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=cwd, env=env)
        return (p.stdout or p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return f"unavailable: {e.__class__.__name__}"


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _meminfo() -> dict:
    out = {}
    txt = _read("/proc/meminfo") or ""
    for line in txt.splitlines():
        k, _, v = line.partition(":")
        if k in ("MemTotal", "MemAvailable", "SwapTotal", "Hugepagesize"):
            out[k] = v.strip()
    return out


def _os_release() -> dict:
    out = {}
    for line in (_read("/etc/os-release") or "").splitlines():
        k, _, v = line.partition("=")
        if k in ("PRETTY_NAME", "ID", "VERSION_ID"):
            out[k] = v.strip('"')
    return out


def _lscpu() -> dict:
    raw = _run(["lscpu", "-J"])
    try:
        entries = json.loads(raw)["lscpu"]
    except (ValueError, KeyError):
        return {"raw": raw}
    keep = {
        "Architecture:", "Model name:", "CPU(s):", "Thread(s) per core:", "Core(s) per socket:",
        "Socket(s):", "NUMA node(s):", "Hypervisor vendor:", "Virtualization type:", "L1d cache:",
        "L2 cache:", "L3 cache:", "CPU max MHz:", "CPU min MHz:", "BogoMIPS:", "Flags:",
    }
    out = {}
    for e in entries:
        if e.get("field") in keep:
            out[e["field"].rstrip(":")] = e.get("data")
    return out


def _cpufreq() -> dict:
    base = Path("/sys/devices/system/cpu/cpu0/cpufreq")
    if not base.exists():
        return {"available": False}
    return {
        "available": True,
        "governor": _read(str(base / "scaling_governor")),
        "driver": _read(str(base / "scaling_driver")),
        "no_turbo": _read("/sys/devices/system/cpu/intel_pstate/no_turbo"),
        "boost": _read("/sys/devices/system/cpu/cpufreq/boost"),
    }


def _cgroup_limits() -> dict:
    out = {"cgroup": _read("/proc/self/cgroup")}
    for f in ("/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/memory.max"):
        v = _read(f)
        if v is not None:
            out[f] = v
    return out


def _perf() -> dict:
    perf = which("perf")
    info: dict = {"binary": perf, "paranoid": _read("/proc/sys/kernel/perf_event_paranoid")}
    devices = sorted(p.name for p in Path("/sys/bus/event_source/devices").glob("*")) if Path(
        "/sys/bus/event_source/devices"
    ).exists() else []
    info["event_sources"] = devices
    info["hardware_counters"] = "cpu" in devices or any(d.startswith("cpu_") for d in devices)
    return info


def _go_env() -> dict:
    env = dict(os.environ)
    env.setdefault("GOTOOLCHAIN", "go1.27.1")
    raw = _run(["go", "env", "-json"], cwd=ROOT / "go", env=env)
    try:
        data = json.loads(raw)
    except ValueError:
        return {"raw": raw}
    keys = ("GOVERSION", "GOOS", "GOARCH", "GOAMD64", "CGO_ENABLED", "GOFLAGS", "GOTOOLCHAIN", "GOEXPERIMENT", "CC")
    return {k: data.get(k) for k in keys}


def _tool_versions() -> dict:
    def first_line(s: str) -> str:
        return s.splitlines()[0] if s else s

    tools = {}
    for name, argv in {
        "hyperfine": ["hyperfine", "--version"],
        "wrk": ["wrk", "-v"],
        "wrk2": ["wrk2", "-v"],
        "oha": ["oha", "--version"],
        "nginx": ["nginx", "-v"],
        "taskset": ["taskset", "--version"],
        "gnu_time": ["/usr/bin/time", "--version"],
        "readelf": ["readelf", "--version"],
    }.items():
        path = which(argv[0]) if not argv[0].startswith("/") else (argv[0] if Path(argv[0]).exists() else None)
        tools[name] = first_line(_run([path, *argv[1:]])) if path else None
    return tools


def _python_packages() -> dict:
    out = {"python": sys.version.split()[0]}
    for mod in ("numpy", "pandas", "matplotlib", "scipy"):
        try:
            out[mod] = __import__(mod).__version__
        except ImportError:
            out[mod] = None
    return out


def _docker() -> dict:
    if not which("docker"):
        return {"available": False}
    return {
        "client": _run(["docker", "version", "--format", "{{.Client.Version}}"]),
        "server": _run(["docker", "version", "--format", "{{.Server.Version}}"]),
    }


def _git() -> dict:
    return {
        "commit": _run(["git", "rev-parse", "HEAD"], cwd=ROOT),
        "dirty": bool(_run(["git", "status", "--porcelain"], cwd=ROOT)),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT),
    }


def capture(mode: str) -> dict:
    stat = procmon.read_proc_stat()
    nofile = resource.getrlimit(resource.RLIMIT_NOFILE)
    return {
        "captured_at": now_iso(),
        "mode": mode,
        "container": Path("/.dockerenv").exists(),
        "hostname": platform.node(),
        "cpu": _lscpu(),
        "nproc_online": os.cpu_count(),
        "affinity": sorted(os.sched_getaffinity(0)),
        "memory": _meminfo(),
        "os": _os_release(),
        "kernel": platform.release(),
        "uname": " ".join(platform.uname()),
        "kernel_cmdline": _read("/proc/cmdline"),
        "cpufreq": _cpufreq(),
        "kernel_settings": {
            "transparent_hugepage": _read("/sys/kernel/mm/transparent_hugepage/enabled"),
            "thp_defrag": _read("/sys/kernel/mm/transparent_hugepage/defrag"),
            "randomize_va_space": _read("/proc/sys/kernel/randomize_va_space"),
            "somaxconn": _read("/proc/sys/net/core/somaxconn"),
            "ip_local_port_range": _read("/proc/sys/net/ipv4/ip_local_port_range"),
            "tcp_tw_reuse": _read("/proc/sys/net/ipv4/tcp_tw_reuse"),
            "tcp_max_syn_backlog": _read("/proc/sys/net/ipv4/tcp_max_syn_backlog"),
            "file_max": _read("/proc/sys/fs/file-max"),
            "swappiness": _read("/proc/sys/vm/swappiness"),
        },
        "limits": {"nofile_soft": nofile[0], "nofile_hard": nofile[1]},
        "cgroup": _cgroup_limits(),
        "loadavg": list(os.getloadavg()),
        "proc_stat_cpu": stat.get("cpu"),
        "perf": _perf(),
        "toolchains": {
            "go_version": _run(["go", "version"], cwd=ROOT / "go", env={**os.environ, "GOTOOLCHAIN": os.environ.get("GOTOOLCHAIN", "go1.27.1")}),
            "go_env": _go_env(),
            "rustc": _run(["rustc", "-vV"], cwd=ROOT / "rust"),
            "cargo": _run(["cargo", "-V"], cwd=ROOT / "rust"),
            "rust_toolchain_file": _read(str(ROOT / "rust" / "rust-toolchain.toml")),
            "cc": _run(["cc", "--version"]).splitlines()[0] if which("cc") else None,
        },
        "build_flags": {
            "go": "CGO_ENABLED=0 GOAMD64=v1 go build -trimpath -buildvcs=false",
            "rust": "cargo build --release --locked (profile.release in rust/Cargo.toml)",
            "rust_tuned": "cargo build --profile release-tuned --locked (fat LTO, codegen-units=1, panic=abort)",
        },
        "tools": _tool_versions(),
        "python": _python_packages(),
        "docker": _docker(),
        "git": _git(),
    }
