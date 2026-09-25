"""Launch one benchmark process under controlled conditions and record
everything about it: the binary's own JSON result, resource usage from wait4
(what /usr/bin/time reports), a /proc sampler time series, hypervisor steal
time on the pinned CPUs, and the load average before the run."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import procmon
from .util import ROOT, parse_cpuset

# Only these variables reach benchmark processes; everything else (GOGC,
# GODEBUG, MALLOC_*, RUSTFLAGS, ...) is dropped unless a workload sets it.
_PASS_THROUGH = ("HOME", "USER", "TMPDIR")


def sanitized_env(extra: dict[str, str]) -> dict[str, str]:
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    for k in _PASS_THROUGH:
        if k in os.environ:
            env[k] = os.environ[k]
    env.update(extra)
    return env


def thread_env(lang: str, ncpus: int) -> dict[str, str]:
    """Worker-thread counts equal to the number of pinned CPUs, set explicitly
    for both runtimes (they would auto-detect the affinity mask anyway)."""
    env = {"BENCH_THREADS": str(ncpus)}
    if lang == "go":
        env["GOMAXPROCS"] = str(ncpus)
    else:
        env["TOKIO_WORKER_THREADS"] = str(ncpus)
    return env


@dataclass
class ProcSpec:
    argv: list[str]
    cpus: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 900.0
    sample_interval_s: float = 0.02
    cwd: Path = ROOT
    keep_series: bool = True


def run(spec: ProcSpec) -> dict:
    """Run a process to completion; never raises for benchmark failures."""
    cmd = (["taskset", "-c", spec.cpus] if spec.cpus else []) + spec.argv
    cpus = parse_cpuset(spec.cpus) if spec.cpus else None
    stat0 = procmon.read_proc_stat()
    load0 = os.getloadavg()
    t_start = time.monotonic_ns()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        env=spec.env,
        cwd=spec.cwd,
        close_fds=True,
    )
    sampler = procmon.Sampler(proc.pid, spec.sample_interval_s)
    sampler.start()

    out_chunks: list[bytes] = []
    err_lines: list[tuple[int, str]] = []
    phases: dict[str, int] = {}

    def read_out() -> None:
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read(65536), b""):
            out_chunks.append(chunk)

    def read_err() -> None:
        assert proc.stderr is not None
        for raw in iter(proc.stderr.readline, b""):
            ts = time.monotonic_ns()
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("@@phase "):
                phases[line.split(None, 1)[1].strip()] = ts
            else:
                err_lines.append((ts, line))
                if len(err_lines) > 400:
                    del err_lines[:200]

    readers = [threading.Thread(target=read_out, daemon=True), threading.Thread(target=read_err, daemon=True)]
    for t in readers:
        t.start()

    timed_out = threading.Event()

    def watchdog() -> None:
        timed_out.set()
        try:
            os.kill(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    timer = threading.Timer(spec.timeout_s, watchdog)
    timer.daemon = True
    timer.start()
    _, status, ru = os.wait4(proc.pid, 0)
    t_end = time.monotonic_ns()
    timer.cancel()
    proc.returncode = os.waitstatus_to_exitcode(status)  # we reaped it; keep Popen consistent
    sampler.stop()
    for t in readers:
        t.join(timeout=10)
    for pipe in (proc.stdout, proc.stderr):
        if pipe:
            pipe.close()
    stat1 = procmon.read_proc_stat()

    stdout = b"".join(out_chunks).decode("utf-8", "replace")
    result = None
    parse_error = None
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                result = json.loads(line)
            except json.JSONDecodeError as e:  # pragma: no cover - reported, not raised
                parse_error = str(e)
            break

    window = None
    if "measure_start" in phases and "measure_end" in phases:
        window = (phases["measure_start"], phases["measure_end"])
    # Peak RSS: the binary's own VmHWM when it reports one (exact), else the
    # highest VmHWM the sampler saw. wait4's ru_maxrss is kept for reference
    # only: Linux carries it across exec(), so it includes the forked
    # orchestrator's RSS and overstates small processes.
    peak_kb = -1
    if isinstance(result, dict):
        peak_kb = int((result.get("rss_kb") or {}).get("hwm_end", -1) or -1)
    if peak_kb <= 0:
        peak_kb = sampler.last_hwm_kb()
    rec = {
        "cmd": cmd,
        "cpus": spec.cpus,
        "exit_code": proc.returncode,
        "timed_out": timed_out.is_set(),
        "wall_ns": t_end - t_start,
        "loadavg_before": list(load0),
        "peak_rss_kb": peak_kb,
        "rusage": {
            "utime_s": ru.ru_utime,
            "stime_s": ru.ru_stime,
            "maxrss_kb_unreliable": ru.ru_maxrss,
            "minflt": ru.ru_minflt,
            "majflt": ru.ru_majflt,
            "nvcsw": ru.ru_nvcsw,
            "nivcsw": ru.ru_nivcsw,
            "inblock": ru.ru_inblock,
            "oublock": ru.ru_oublock,
        },
        "steal_frac_pinned": procmon.steal_fraction(stat0, stat1, cpus),
        "steal_frac_all": procmon.steal_fraction(stat0, stat1, None),
        "phases_ms": {k: round((v - t_start) / 1e6, 3) for k, v in phases.items()},
        "sampler": {
            "interval_ms": spec.sample_interval_s * 1000,
            "whole": sampler.summary(),
            "measure": sampler.summary(window) if window else {"n": 0},
        },
        "stderr_tail": [line for _, line in err_lines[-40:]],
        "result": result,
    }
    if spec.keep_series:
        rec["sampler"]["series"] = sampler.series(t_start)
    if parse_error:
        rec["parse_error"] = parse_error
    rec["ok"] = bool(
        proc.returncode == 0 and not timed_out.is_set() and isinstance(result, dict) and "error" not in result
    )
    if not rec["ok"]:
        rec["error"] = (
            (result or {}).get("error")
            or ("timeout" if timed_out.is_set() else None)
            or parse_error
            or f"exit code {proc.returncode}"
        )
    return rec
