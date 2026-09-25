"""Startup category driver (METHODOLOGY.md §13.9).

Two tests, both Go vs Rust (kind = "startup" workloads in bench.toml):

* **cli** (``test = "cli"``): exec -> exit of a minimal "print one line" CLI,
  measured by ``hyperfine -N`` (no intermediate shell). hyperfine runs one
  command to completion before the next, so interleaving comes from *rounds*:
  each round runs a batch of every language in a seeded random order.
  hyperfine itself is pinned (``taskset``) to the single-benchmark core, the
  child inherits the mask, so no ``taskset`` exec cost is inside the timing.
* **ttfr** (``test = "ttfr"``): time from ``exec`` of an HTTP server to its
  first successful ``GET /health`` response, and additionally to the first
  ``GET /users/42`` response (first real request on a cold process). A Python
  launcher on the harness core alternates the languages; the server's CPU mask
  is set between fork and exec (no ``taskset`` in the timed path) and
  readiness is polled in a tight connect loop. Time zero is when ``Popen``
  returns, i.e. just after a successful ``exec``.

Validation: the CLI's stdout must be exactly ``hello\\n`` in both languages.
"""

from __future__ import annotations

import http.client
import json
import os
import random
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import builds, orchestrate, runner
from .spec import Spec, Workload
from .util import ROOT, log, now_iso, parse_cpuset, which, write_json

EXPECTED_STDOUT = b"hello\n"


@dataclass
class StartupConfig:
    cli_runs: int = 1000  # total per language
    cli_batch: int = 200  # runs per hyperfine invocation (one round)
    cli_warmup: int = 20  # hyperfine --warmup per invocation
    ttfr_runs: int = 300  # per language
    port: int = 18090
    timeout_s: float = 10.0


def load_config(spec: Spec, profile: str) -> StartupConfig:
    raw = dict(spec.raw.get("startup", {}))
    prof = raw.pop(profile, {})
    for p in ("quick", "standard", "full"):
        raw.pop(p, None)
    cfg = StartupConfig()
    for src in (raw, prof):
        for k, v in src.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    return cfg


def _binary(w: Workload, lang: str) -> Path:
    return builds.bin_path(lang, w.impl_for(lang), w.flavor_for(lang))


def _env(spec: Spec, w: Workload, lang: str) -> dict[str, str]:
    return runner.sanitized_env({**runner.thread_env(lang, spec.ncpus(w.cores)), **w.env_for(lang)})


# --------------------------------------------------------------------------- validation

def validate(spec: Spec, profile: str) -> bool:
    ok_all = True
    for w in spec.workloads:
        if w.kind != "startup" or w.extra.get("test") != "cli":
            continue
        for lang in w.langs:
            b = _binary(w, lang)
            if not b.exists():
                log(f"{w.id} {lang}: {b} missing", level="error")
                ok_all = False
                continue
            p = subprocess.run([str(b)], capture_output=True, env=_env(spec, w, lang), timeout=10)
            ok = p.returncode == 0 and p.stdout == EXPECTED_STDOUT
            ok_all &= ok
            log(f"{w.id:<28} {lang:<4} {'OK' if ok else 'MISMATCH'} stdout={p.stdout!r} exit={p.returncode}")
    return ok_all


# --------------------------------------------------------------------------- cli (hyperfine)

def _hyperfine(spec: Spec, w: Workload, lang: str, cfg: StartupConfig, runs: int, out: Path) -> dict:
    hf = which("hyperfine")
    if not hf:
        raise FileNotFoundError("hyperfine not installed (make setup)")
    b = _binary(w, lang)
    cmd = ["taskset", "-c", spec.cpus(w.cores), hf, "-N", "--style", "none", "--warmup", str(cfg.cli_warmup),
           "--runs", str(runs), "--output", "null", "--export-json", str(out), "--", str(b)]
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, env=_env(spec, w, lang), timeout=600)
    rec = {"cmd": cmd, "exit_code": p.returncode, "stderr": p.stderr[-2000:], "wall_s": time.time() - t0}
    if p.returncode == 0 and out.exists():
        r = json.loads(out.read_text())["results"][0]
        rec["times_s"] = r["times"]
        rec["exit_codes"] = r.get("exit_codes")
        rec["user_s_mean"] = r.get("user")
        rec["system_s_mean"] = r.get("system")
        out.unlink()
    return rec


def _run_cli(spec, w, cfg, base, run_id, mode, profile, rng, rounds_override, resume) -> None:
    rounds = rounds_override or max(1, round(cfg.cli_runs / cfg.cli_batch))
    for r in range(rounds):
        order = list(w.langs)
        rng.shuffle(order)
        for pos, lang in enumerate(order):
            path = base / "startup" / w.id / f"{lang}-r{r:02d}.json"
            if resume and path.exists():
                continue
            rec = _base_rec(run_id, mode, profile, w, lang, r, pos)
            rec["binary"] = str(_binary(w, lang))
            rec["binary_bytes"] = _binary(w, lang).stat().st_size
            rec["cpus"] = spec.cpus(w.cores)
            try:
                rec.update(_hyperfine(spec, w, lang, cfg, cfg.cli_batch, path.with_suffix(".hf.json")))
                codes = rec.get("exit_codes") or []
                rec["ok"] = rec["exit_code"] == 0 and bool(rec.get("times_s")) and not any(codes)
            except Exception as e:  # noqa: BLE001 - recorded
                rec["ok"] = False
                rec["error"] = f"{type(e).__name__}: {e}"
            write_json(path, rec)
            t = sorted(rec.get("times_s") or [0])
            log(f"[startup {w.id} r{r + 1}/{rounds}] {lang:<4} n={len(rec.get('times_s') or [])} "
                f"median={t[len(t) // 2] * 1e3:.3f}ms min={t[0] * 1e3:.3f}ms {'ok' if rec['ok'] else 'FAILED'}")


# --------------------------------------------------------------------------- ttfr (python launcher)

def _get(port: int, path: str, timeout: float) -> int | None:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", path)
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status
    except (OSError, http.client.HTTPException):
        return None


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _one_ttfr(spec: Spec, w: Workload, lang: str, cfg: StartupConfig) -> dict:
    b = _binary(w, lang)
    cpus = set(parse_cpuset(spec.cpus(w.cores)))
    deadline = time.monotonic() + 5
    while not _port_free(cfg.port) and time.monotonic() < deadline:
        time.sleep(0.01)
    argv = [str(b), "--addr", f"127.0.0.1:{cfg.port}"]
    t0 = time.monotonic_ns()
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            env=_env(spec, w, lang), cwd=ROOT, close_fds=True,
                            preexec_fn=lambda: os.sched_setaffinity(0, cpus))
    # With preexec_fn, Popen forks and returns only once exec succeeded (it
    # waits on the exec-error pipe), so t_exec ~ exec time; the launcher's own
    # fork cost (tens of ms for a big Python process) is kept out.
    t_exec = time.monotonic_ns()
    rec: dict = {"ok": False, "attempts": 0, "spawn_ms": (t_exec - t0) / 1e6}
    t0 = t_exec
    try:
        end = time.monotonic() + cfg.timeout_s
        while time.monotonic() < end:
            rec["attempts"] += 1
            if _get(cfg.port, "/health", 1.0) == 200:
                rec["health_ms"] = (time.monotonic_ns() - t0) / 1e6
                break
            if proc.poll() is not None:
                rec["error"] = f"exited early with {proc.returncode}"
                return rec
        else:
            rec["error"] = "timeout"
            return rec
        st = _get(cfg.port, "/users/42", 2.0)
        rec["first_request_ms"] = (time.monotonic_ns() - t0) / 1e6
        rec["first_request_status"] = st
        rec["ok"] = st == 200
        try:
            with open(f"/proc/{proc.pid}/status") as f:
                for line in f:
                    if line.startswith(("VmHWM:", "Threads:")):
                        k, v = line.split(":", 1)
                        rec["hwm_kb" if k == "VmHWM" else "threads"] = int(v.split()[0])
        except OSError:
            pass
        return rec
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _run_ttfr(spec, w, cfg, base, run_id, mode, profile, rng, rounds_override, resume) -> None:
    n = rounds_override or cfg.ttfr_runs
    path = base / "startup" / w.id / "ttfr.json"
    if resume and path.exists():
        return
    runs: dict[str, list[dict]] = {lang: [] for lang in w.langs}
    for i in range(n):
        order = list(w.langs)
        rng.shuffle(order)
        for lang in order:
            r = _one_ttfr(spec, w, lang, cfg)
            r["i"] = i
            runs[lang].append(r)
        if (i + 1) % max(1, n // 5) == 0:
            msg = []
            for lang in w.langs:
                h = sorted(x["health_ms"] for x in runs[lang] if x.get("ok"))
                msg.append(f"{lang} median={h[len(h) // 2] if h else float('nan'):.2f}ms")
            log(f"[startup {w.id} {i + 1}/{n}] " + " ".join(msg))
    for lang in w.langs:
        rec = _base_rec(run_id, mode, profile, w, lang, 0, 0)
        rec.update({"binary": str(_binary(w, lang)), "cpus": spec.cpus(w.cores), "runs": runs[lang],
                    "ok": all(r.get("ok") for r in runs[lang]) and bool(runs[lang])})
        write_json(base / "startup" / w.id / f"{lang}-ttfr.json", rec)
    write_json(path, {"done": True, "n": n})


# --------------------------------------------------------------------------- entry

def _base_rec(run_id, mode, profile, w, lang, rnd, pos) -> dict:
    return {"run_id": run_id, "mode": mode, "profile": profile, "category": "startup", "workload": w.id,
            "track": w.track, "variant_of": w.variant_of, "test": w.extra.get("test"), "impl": w.impl_for(lang),
            "flavor": w.flavor_for(lang), "lang": lang, "round": rnd, "order_in_round": pos}


def run(spec: Spec, profile: str, run_id: str, mode: str, ids=None, rounds_override=None, resume=False) -> Path:
    cfg = load_config(spec, profile)
    items = [w for w in spec.workloads if w.kind == "startup" and (not ids or w.id in ids)
             and any(profile in s.profiles for s in w.sizes)]
    if not validate(spec, profile):
        raise SystemExit("startup validation failed")
    base = orchestrate.ensure_run_metadata(run_id, mode, profile)
    orchestrate.pin_self(spec)
    started = now_iso()
    rng = random.Random(spec.seed)
    for w in items:
        fn = _run_cli if w.extra.get("test") == "cli" else _run_ttfr
        fn(spec, w, cfg, base, run_id, mode, profile, rng, rounds_override, resume)
    orchestrate._record_invocation(base, {"kind": "startup", "categories": ["startup"], "profile": profile,
                                          "ids": ids, "started_at": started, "finished_at": now_iso()})
    return base
