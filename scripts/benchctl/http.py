"""HTTP category driver (METHODOLOGY.md §13.4).

Tests, for every server pair (kind = "http" workloads in bench.toml):

* **parity** (validation): identical request list to both servers; status and
  body bytes must match; header sets are recorded.
* **throughput**: closed-loop `wrk` at each connection count; fresh server per
  (connections, round, language), warmup then a measured window.
* **latency**: open-loop `wrk2` (coordinated-omission corrected) at fixed
  request rates that are fractions of the *slower* server's capacity, the same
  absolute rates for both languages.
* **sustained**: one server under constant load for minutes, measured as
  back-to-back windows; server RSS/CPU sampled throughout.

Server and load generator are pinned to disjoint cores. The load generator's
CPU use is sampled; a run whose load-generator cores were >95% busy is flagged
`loadgen_saturated` because its throughput is not the server's limit.
"""

from __future__ import annotations

import http.client
import json
import os
import random
import re
import resource
import signal
import socket
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import builds, orchestrate, procmon, runner
from .spec import Spec, Workload
from .util import ROOT, RAW_DIR, log, now_iso, parse_cpuset, read_json, which, write_json

REPORT_LUA = ROOT / "scripts" / "wrk" / "report.lua"
SATURATION = 0.95


# --------------------------------------------------------------------------- config

@dataclass
class HttpConfig:
    port: int = 18080
    timeout_s: int = 5
    rounds: int = 5
    secondary_rounds: int = 3
    warmup_s: int = 10
    duration_s: int = 30
    connections: list[int] = field(default_factory=lambda: [1, 10, 100, 500, 1000, 5000, 10000])
    secondary_connections: list[int] = field(default_factory=lambda: [10, 100, 1000])
    latency_connections: int = 100
    latency_rounds: int = 3
    latency_warmup_s: int = 10
    latency_duration_s: int = 60
    rates: list[float] = field(default_factory=lambda: [0.25, 0.5, 0.75, 0.9])
    sustained: list[dict] = field(default_factory=list)
    sample_ms: int = 250


def load_config(spec: Spec, profile: str) -> HttpConfig:
    raw = dict(spec.raw.get("http", {}))
    prof = raw.pop(profile, {})
    for p in ("quick", "standard", "full"):
        raw.pop(p, None)
    cfg = HttpConfig()
    for src in (raw, prof):
        for k, v in src.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    return cfg


def raise_nofile() -> None:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft < hard:
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))


# --------------------------------------------------------------------------- server

class Server:
    """One benchmark server process, pinned and sampled."""

    def __init__(self, spec: Spec, w: Workload, lang: str, port: int, sample_ms: int):
        self.lang = lang
        self.name = w.impl_for(lang)
        self.binary = builds.bin_path(lang, self.name, w.flavor_for(lang))
        self.cpus = spec.cpus(w.cores)
        self.port = port
        ncpus = spec.ncpus(w.cores)
        self.env = runner.sanitized_env({**runner.thread_env(lang, ncpus), **w.env_for(lang)})
        self.sample_ms = sample_ms
        self.proc: subprocess.Popen | None = None
        self.sampler: procmon.Sampler | None = None
        self.started_ns = 0
        self.ready_ms = None
        self.hwm_kb = -1
        self.stderr_tail = ""

    @property
    def addr(self) -> str:
        return f"127.0.0.1:{self.port}"

    def start(self) -> None:
        if not self.binary.exists():
            raise FileNotFoundError(f"{self.binary} missing (run `make build`)")
        cmd = ["taskset", "-c", self.cpus, str(self.binary), "--addr", self.addr]
        self.started_ns = time.monotonic_ns()
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                     env=self.env, cwd=ROOT, close_fds=True)
        self.sampler = procmon.Sampler(self.proc.pid, self.sample_ms / 1000)
        self.sampler.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"{self.name} exited early: {self.proc.stderr.read().decode(errors='replace')}")
            if health(self.port):
                self.ready_ms = (time.monotonic_ns() - self.started_ns) / 1e6
                return
            time.sleep(0.005)
        self.stop()
        raise TimeoutError(f"{self.name} did not become ready on {self.addr}")

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            with open(f"/proc/{self.proc.pid}/status") as f:
                for line in f:
                    if line.startswith("VmHWM:"):
                        self.hwm_kb = int(line.split()[1])
        except OSError:
            pass
        if self.sampler:
            self.sampler.stop()
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        if self.proc.stderr:
            self.stderr_tail = self.proc.stderr.read().decode(errors="replace")[-2000:]
            self.proc.stderr.close()
        self.proc = None


def health(port: int, timeout: float = 0.2) -> bool:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", "/health")
        ok = conn.getresponse().status == 200
        conn.close()
        return ok
    except OSError:
        return False


# --------------------------------------------------------------------------- load generator

def run_loadgen(tool: str, port: int, cpus: str, connections: int, duration_s: int, timeout_s: int,
                rate: float | None = None, sample_ms: int = 250) -> dict:
    exe = which(tool)
    if exe is None:
        raise FileNotFoundError(f"{tool} not found (run `make setup`)")
    ncpu = len(parse_cpuset(cpus))
    threads = max(1, min(ncpu, connections))
    cmd = ["taskset", "-c", cpus, exe, f"-t{threads}", f"-c{connections}", f"-d{duration_s}s",
           f"--timeout", f"{timeout_s}s", "--latency", "-s", str(REPORT_LUA)]
    if rate is not None:
        cmd += ["-R", str(max(1, int(rate)))]
    cmd.append(f"http://127.0.0.1:{port}/")
    stat0 = procmon.read_proc_stat()
    t0 = time.monotonic_ns()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            env=runner.sanitized_env({}), cwd=ROOT, close_fds=True)
    sampler = procmon.Sampler(proc.pid, sample_ms / 1000)
    sampler.start()
    out, err = proc.communicate(timeout=duration_s + 120)
    t1 = time.monotonic_ns()
    sampler.stop()
    stat1 = procmon.read_proc_stat()
    text = out.decode(errors="replace")
    parsed = None
    for line in text.splitlines():
        if line.startswith("WRK_JSON "):
            parsed = json.loads(line[len("WRK_JSON "):])
    s = sampler.summary()
    return {
        "cmd": cmd,
        "exit_code": proc.returncode,
        "window_ns": [t0, t1],
        "stdout": text[-20000:],
        "stderr": err.decode(errors="replace")[-2000:],
        "parsed": parsed,
        "loadgen_cpu_util": s.get("cpu_util"),
        "loadgen_cpus": ncpu,
        "loadgen_cores_busy": procmon.busy_fraction(stat0, stat1, parse_cpuset(cpus)),
        "steal_frac_loadgen": procmon.steal_fraction(stat0, stat1, parse_cpuset(cpus)),
        "stat": (stat0, stat1),
    }


def _metrics(lg: dict, server: Server, server_cpus: str) -> dict:
    """Derive per-window metrics from a load-generator result + server samples."""
    p = lg.get("parsed") or {}
    lo, hi = lg["window_ns"]
    ss = server.sampler.summary((lo, hi)) if server.sampler else {"n": 0}
    stat0, stat1 = lg.pop("stat")
    dur = p.get("duration_us", 0) / 1e6
    reqs = p.get("requests", 0)
    errs = p.get("errors", {})
    n_err = sum(errs.values()) if errs else 0
    server_cpu = ss.get("cpu_util")  # cores busy
    lat = p.get("latency_us", {})
    m = {
        "requests": reqs,
        "duration_s": dur,
        "rps": reqs / dur if dur else None,
        "errors": errs,
        "error_count": n_err,
        "error_rate": n_err / (reqs + n_err) if (reqs + n_err) else None,
        "latency_us": lat,
        "server_cpu_util": server_cpu,
        "server_rss_avg_kb": ss.get("rss_avg_kb"),
        "server_rss_peak_kb": ss.get("rss_peak_kb"),
        "server_threads_max": ss.get("threads_max"),
        "requests_per_cpu_second": (reqs / (server_cpu * dur)) if server_cpu and dur else None,
        "loadgen_cpu_util": lg.get("loadgen_cpu_util"),
        "loadgen_cores_busy": lg.get("loadgen_cores_busy"),
        "steal_frac_server": procmon.steal_fraction(stat0, stat1, parse_cpuset(server_cpus)),
        "steal_frac_loadgen": lg.get("steal_frac_loadgen"),
    }
    flags = []
    if lg.get("exit_code") != 0 or not p:
        flags.append("failed")
    ncpu = lg.get("loadgen_cpus", 1)
    if (lg.get("loadgen_cpu_util") or 0) >= SATURATION * ncpu or (lg.get("loadgen_cores_busy") or 0) >= SATURATION:
        flags.append("loadgen_saturated")
    if max(m["steal_frac_server"] or 0, m["steal_frac_loadgen"] or 0) > orchestrate.STEAL_FLAG:
        flags.append("steal")
    m["flags"] = flags
    return m


# --------------------------------------------------------------------------- parity (validation)

PARITY_PATHS = [f"/users/{i}" for i in (1, 2, 3, 42, 99, 1000, 9999, 10000, 123456789)] + [
    "/users/0", "/users/007", "/users/18446744073709551615", "/users/18446744073709551616",
    "/users/-1", "/users/abc", "/users/1.5", "/users/%31%32",
]
# Inputs where the two standard libraries legitimately disagree; reported, not
# failed. Rust's u64::from_str accepts a leading '+', Go's strconv.ParseUint
# rejects it. The benchmark's request stream never contains such ids.
KNOWN_DIFFERENCES = ["/users/+5"]


def fetch_raw(port: int, path: str) -> tuple[int, dict, bytes, int]:
    """One keep-alive-less request with a raw socket: (status, headers, body, header_bytes)."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        headers[k.strip().lower()] = v.strip()
    if headers.get("transfer-encoding", "").lower() == "chunked":
        raw, body = body, b""
        while raw:
            size_s, _, rest = raw.partition(b"\r\n")
            size = int(size_s, 16)
            if size == 0:
                break
            body += rest[:size]
            raw = rest[size + 2:]
    return status, headers, body, len(head) + 4


def validate_parity(spec: Spec, profile: str) -> bool:
    raise_nofile()
    cfg = load_config(spec, profile)
    ok_all = True
    for w in [w for w in spec.workloads if w.kind == "http"]:
        results: dict[str, list] = {}
        for lang in w.langs:
            srv = Server(spec, w, lang, cfg.port, cfg.sample_ms)
            try:
                srv.start()
                results[lang] = [fetch_raw(cfg.port, p) for p in PARITY_PATHS]
                known = [(p, fetch_raw(cfg.port, p)[0]) for p in KNOWN_DIFFERENCES]
                log(f"         {w.id} {lang}: informational {', '.join(f'{p} -> {s}' for p, s in known)}")
            except (OSError, RuntimeError, TimeoutError) as e:
                log(f"INVALID  {w.id}: {lang} server failed: {e}", level="error")
                ok_all = False
            finally:
                srv.stop()
        if len(results) != len(w.langs):
            continue
        problems = []
        a, b = results[w.langs[0]], results[w.langs[1]]
        for path, ra, rb in zip(PARITY_PATHS, a, b):
            if ra[0] != rb[0] or ra[2] != rb[2]:
                problems.append(f"{path}: {w.langs[0]}={ra[0]} {ra[2][:60]!r} vs {w.langs[1]}={rb[0]} {rb[2][:60]!r}")
        ct = {lang: results[lang][0][1].get("content-type") for lang in w.langs}
        hdr = {lang: results[lang][0][3] for lang in w.langs}
        status = "OK" if not problems else "INVALID"
        ok_all &= not problems
        log(f"{status:<8} {w.id:<32} parity over {len(PARITY_PATHS)} requests; content-type {ct}; header bytes {hdr}"
            + ("" if not problems else "\n  " + "\n  ".join(problems)), level="info" if not problems else "error")
    return ok_all


# --------------------------------------------------------------------------- tests

def _save(path: Path, rec: dict) -> None:
    write_json(path, rec)


def _base_rec(run_id, mode, profile, w, lang, test, label, rnd, pos) -> dict:
    return {"run_id": run_id, "mode": mode, "profile": profile, "category": "http", "workload": w.id,
            "track": w.track, "tier": w.extra.get("tier", "primary"), "server": w.impl_for(w.langs[0]) + "/" + w.impl_for(w.langs[1]),
            "impl": w.impl_for(lang), "lang": lang, "test": test, "size": label, "round": rnd, "order_in_round": pos}


def _one_window(spec, w, lang, cfg, tool, connections, warmup_s, duration_s, rate=None) -> dict:
    srv = Server(spec, w, lang, cfg.port, cfg.sample_ms)
    loadgen = spec.cpus("http_loadgen")
    rec: dict = {"server_binary": str(srv.binary), "server_cpus": srv.cpus, "loadgen_cpus": loadgen,
                 "env": {k: v for k, v in srv.env.items() if k not in ("PATH", "HOME", "USER", "TMPDIR")}}
    try:
        srv.start()
        rec["server_ready_ms"] = srv.ready_ms
        if warmup_s:
            wu = run_loadgen(tool, cfg.port, loadgen, connections, warmup_s, cfg.timeout_s, rate, cfg.sample_ms)
            wu.pop("stat", None)
            rec["warmup"] = {k: wu[k] for k in ("cmd", "exit_code", "parsed")}
        lg = run_loadgen(tool, cfg.port, loadgen, connections, duration_s, cfg.timeout_s, rate, cfg.sample_ms)
        rec["metrics"] = _metrics(lg, srv, srv.cpus)
        rec["loadgen"] = {k: lg[k] for k in ("cmd", "exit_code", "stdout", "stderr", "parsed")}
        rec["ok"] = "failed" not in rec["metrics"]["flags"]
    except Exception as e:  # noqa: BLE001 - recorded, never silently dropped
        rec["ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"
    finally:
        srv.stop()
        rec["server_hwm_kb"] = srv.hwm_kb
        rec["server_stderr_tail"] = srv.stderr_tail
        if srv.sampler:
            rec["server_series"] = srv.sampler.series(srv.started_ns, max_points=1500)
    return rec


def _fmt(rec: dict) -> str:
    if not rec.get("ok"):
        return f"FAILED: {rec.get('error') or rec.get('metrics', {}).get('flags')}"
    m = rec["metrics"]
    lat = m.get("latency_us", {}).get("percentiles", {})
    return (f"rps={m['rps']:.0f} p50={lat.get('50', 0) / 1000:.2f}ms p99={lat.get('99', 0) / 1000:.2f}ms "
            f"err={m['error_count']} srv_cpu={m['server_cpu_util'] or 0:.2f} lg_cpu={m['loadgen_cpu_util'] or 0:.2f} "
            f"rss={(m['server_rss_peak_kb'] or 0) / 1024:.1f}MiB {' '.join(m['flags'])}")


def run(spec: Spec, profile: str, run_id: str, mode: str, ids=None, rounds_override=None, resume=False) -> Path:
    raise_nofile()
    cfg = load_config(spec, profile)
    items = [w for w in spec.workloads if w.kind == "http" and (not ids or w.id in ids)
             and any(profile in s.profiles for s in w.sizes)]
    base = orchestrate.ensure_run_metadata(run_id, mode, profile)
    orchestrate.pin_self(spec)
    started = now_iso()
    rng = random.Random(spec.seed)
    for w in items:
        tier = w.extra.get("tier", "primary")
        rounds = rounds_override or (cfg.rounds if tier == "primary" else cfg.secondary_rounds)
        conns = cfg.connections if tier == "primary" else cfg.secondary_connections
        # --- throughput sweep (closed loop, wrk)
        for r in range(rounds):
            for c in conns:
                order = list(w.langs)
                rng.shuffle(order)
                for pos, lang in enumerate(order):
                    path = base / "http" / w.id / "throughput" / f"c{c}" / f"{lang}-r{r:02d}.json"
                    if resume and path.exists():
                        continue
                    rec = _base_rec(run_id, mode, profile, w, lang, "throughput", f"c{c}", r, pos)
                    rec["connections"] = c
                    rec.update(_one_window(spec, w, lang, cfg, "wrk", c, cfg.warmup_s, cfg.duration_s))
                    _save(path, rec)
                    log(f"[http {w.id} throughput c={c} r{r + 1}/{rounds}] {lang:<4} {_fmt(rec)}")
        if tier != "primary":
            continue
        # --- open-loop latency at fixed fractions of the slower server's capacity (wrk2)
        cap = _capacity(base, w, cfg.latency_connections)
        if cap is None:
            log(f"{w.id}: no throughput result at c={cfg.latency_connections}; skipping latency tests", level="warn")
        else:
            write_json(base / "http" / w.id / "latency" / "capacity.json", cap, indent=1)
            for r in range(rounds_override or cfg.latency_rounds):
                for frac in cfg.rates:
                    rate = frac * cap["base_rps"]
                    order = list(w.langs)
                    rng.shuffle(order)
                    for pos, lang in enumerate(order):
                        label = f"r{int(frac * 100):02d}"
                        path = base / "http" / w.id / "latency" / label / f"{lang}-r{r:02d}.json"
                        if resume and path.exists():
                            continue
                        rec = _base_rec(run_id, mode, profile, w, lang, "latency", label, r, pos)
                        rec.update({"connections": cfg.latency_connections, "rate_frac": frac, "target_rps": rate})
                        rec.update(_one_window(spec, w, lang, cfg, "wrk2", cfg.latency_connections,
                                               cfg.latency_warmup_s, cfg.latency_duration_s, rate))
                        _save(path, rec)
                        log(f"[http {w.id} latency {frac:.0%} of {cap['base_rps']:.0f} r{r + 1}] {lang:<4} {_fmt(rec)}")
        # --- sustained load
        for sus in cfg.sustained:
            order = list(w.langs)
            rng.shuffle(order)
            label = f"c{sus['connections']}-{sus['duration_s']}s"
            for pos, lang in enumerate(order):
                path = base / "http" / w.id / "sustained" / label / f"{lang}.json"
                if resume and path.exists():
                    continue
                rec = _base_rec(run_id, mode, profile, w, lang, "sustained", label, 0, pos)
                rec.update(_sustained(spec, w, lang, cfg, sus))
                _save(path, rec)
                wins = rec.get("windows", [])
                rps = [x["rps"] for x in wins if x.get("rps")]
                log(f"[http {w.id} sustained {label}] {lang:<4} windows={len(wins)} "
                    f"rps median={statistics.median(rps) if rps else 0:.0f} rss_slope={rec.get('rss_slope_mib_per_min')}")
    orchestrate._record_invocation(base, {"kind": "http", "categories": ["http"], "profile": profile,
                                          "ids": ids, "started_at": started, "finished_at": now_iso()})
    return base


def _capacity(base: Path, w: Workload, connections: int) -> dict | None:
    d = base / "http" / w.id / "throughput" / f"c{connections}"
    per_lang: dict[str, list[float]] = {}
    for f in sorted(d.glob("*-r*.json")) if d.exists() else []:
        rec = read_json(f)
        m = rec.get("metrics") or {}
        if rec.get("ok") and m.get("rps") and "loadgen_saturated" not in m.get("flags", []):
            per_lang.setdefault(rec["lang"], []).append(m["rps"])
    if len(per_lang) < 2:
        return None
    med = {lang: statistics.median(v) for lang, v in per_lang.items()}
    return {"connections": connections, "median_rps": med, "base_rps": min(med.values()),
            "rule": "rates are fractions of the slower server's median closed-loop throughput"}


def _sustained(spec, w, lang, cfg, sus) -> dict:
    srv = Server(spec, w, lang, cfg.port, max(cfg.sample_ms, 250))
    loadgen = spec.cpus("http_loadgen")
    out: dict = {"connections": sus["connections"], "duration_s": sus["duration_s"], "window_s": sus.get("window_s", 10),
                 "windows": []}
    try:
        srv.start()
        wu = run_loadgen("wrk", cfg.port, loadgen, sus["connections"], cfg.warmup_s, cfg.timeout_s)
        wu.pop("stat", None)
        t_start = time.monotonic_ns()
        n_windows = max(1, sus["duration_s"] // out["window_s"])
        for i in range(n_windows):
            lg = run_loadgen("wrk", cfg.port, loadgen, sus["connections"], out["window_s"], cfg.timeout_s)
            m = _metrics(lg, srv, srv.cpus)
            m["t_s"] = (lg["window_ns"][0] - t_start) / 1e9
            m["window"] = i
            out["windows"].append(m)
        series = srv.sampler.series(t_start, max_points=4000)
        out["server_series"] = series
        pts = [(p[0] / 60000, p[1] / 1024) for p in series if p[0] >= 0]
        if len(pts) > 2:
            xs, ys = zip(*pts)
            mx, my = statistics.mean(xs), statistics.mean(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            out["rss_slope_mib_per_min"] = sum((x - mx) * (y - my) for x, y in pts) / sxx if sxx else 0.0
        out["ok"] = all("failed" not in m["flags"] for m in out["windows"])
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        srv.stop()
        out["server_hwm_kb"] = srv.hwm_kb
    return out
