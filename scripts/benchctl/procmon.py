"""/proc sampling: per-process RSS / CPU / thread time series (what `pidstat`
reports) and system-wide CPU accounting including hypervisor steal time."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024


def read_proc_stat() -> dict[str, list[int]]:
    """cpu lines of /proc/stat: name -> [user, nice, system, idle, iowait, irq, softirq, steal, ...]."""
    out: dict[str, list[int]] = {}
    with open("/proc/stat") as f:
        for line in f:
            if not line.startswith("cpu"):
                break
            parts = line.split()
            out[parts[0]] = [int(x) for x in parts[1:]]
    return out


def steal_fraction(before: dict[str, list[int]], after: dict[str, list[int]], cpus: list[int] | None) -> float:
    """Fraction of CPU time stolen by the hypervisor on the given CPUs (all CPUs when None)."""
    names = [f"cpu{c}" for c in cpus] if cpus else ["cpu"]
    steal = total = 0
    for n in names:
        if n not in before or n not in after:
            continue
        a, b = before[n], after[n]
        # Exclude guest/guest_nice (already counted in user/nice).
        da = [y - x for x, y in zip(a[:8], b[:8])]
        total += sum(da)
        steal += da[7] if len(da) > 7 else 0
    return steal / total if total > 0 else 0.0


def busy_fraction(before: dict[str, list[int]], after: dict[str, list[int]], cpus: list[int]) -> float:
    """Average non-idle fraction of the given CPUs over the interval."""
    busy = total = 0
    for c in cpus:
        n = f"cpu{c}"
        if n not in before or n not in after:
            continue
        da = [y - x for x, y in zip(before[n][:8], after[n][:8])]
        t = sum(da)
        idle = da[3] + da[4]
        total += t
        busy += t - idle
    return busy / total if total > 0 else 0.0


def read_pid_sample(pid: int) -> tuple[int, int, int, int] | None:
    """(rss_kb, threads, cpu_ticks, hwm_kb) for pid, or None if it is gone.

    VmHWM is the kernel's exact per-address-space RSS high-water mark. It is
    used instead of wait4's ru_maxrss, which on Linux carries over across
    exec() and therefore includes the memory of the forked orchestrator.
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            stat = f.read()
        # comm may contain spaces/parentheses: split after the last ')'.
        rest = stat[stat.rindex(b")") + 2 :].split()
        utime, stime = int(rest[11]), int(rest[12])
        threads = int(rest[17])
        rss_pages = int(rest[21])
        hwm = -1
        with open(f"/proc/{pid}/status", "rb") as f:
            for line in f:
                if line.startswith(b"VmHWM:"):
                    hwm = int(line.split()[1])
                    break
        return rss_pages * PAGE_KB, threads, utime + stime, hwm
    except (FileNotFoundError, ProcessLookupError, ValueError, IndexError):
        return None


@dataclass
class Sampler:
    """Background sampler for one pid. Samples are (t_ns, rss_kb, threads, cpu_ticks, hwm_kb)."""

    pid: int
    interval_s: float = 0.02
    samples: list[tuple[int, int, int, int, int]] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name=f"sampler-{self.pid}", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        nxt = time.monotonic()
        while not self._stop.is_set():
            s = read_pid_sample(self.pid)
            if s is None:
                break
            self.samples.append((time.monotonic_ns(), *s))
            nxt += self.interval_s
            delay = nxt - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            else:
                nxt = time.monotonic()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def summary(self, window: tuple[int, int] | None = None) -> dict:
        """Peak / time-weighted average RSS and CPU over the whole run or a window."""
        pts = self.samples
        if window:
            lo, hi = window
            pts = [p for p in pts if lo <= p[0] <= hi]
        if not pts:
            return {"n": 0}
        rss = [p[1] for p in pts]
        if len(pts) >= 2:
            # time-weighted mean (trapezoid)
            area = 0.0
            for a, b in zip(pts, pts[1:]):
                area += (a[1] + b[1]) / 2 * (b[0] - a[0])
            dur = pts[-1][0] - pts[0][0]
            avg = area / dur if dur > 0 else float(rss[0])
            cpu = (pts[-1][3] - pts[0][3]) / CLK_TCK / (dur / 1e9) if dur > 0 else 0.0
        else:
            avg, cpu = float(rss[0]), 0.0
        return {
            "n": len(pts),
            "rss_peak_kb": max(rss),
            "rss_avg_kb": avg,
            "hwm_kb": max(p[4] for p in pts),
            "threads_max": max(p[2] for p in pts),
            "cpu_util": cpu,  # CPUs busy (1.0 = one full core), 10 ms tick resolution
        }

    def last_hwm_kb(self) -> int:
        return max((p[4] for p in self.samples), default=-1)

    def series(self, t0: int, max_points: int = 2000) -> list[list[float]]:
        """Downsampled series [[t_ms, rss_kb, threads, cpu_ticks], ...] relative to t0."""
        pts = self.samples
        step = max(1, len(pts) // max_points)
        return [[round((p[0] - t0) / 1e6, 3), p[1], p[2], p[3]] for p in pts[::step]]
