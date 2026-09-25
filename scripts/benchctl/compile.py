"""Compilation category driver (METHODOLOGY.md §13.11).

Each ``kind = "compile"`` workload names a *target* (hello, http, suite) and
a *track*:

  release  go build (the benchmarked flags)  vs  cargo build --release
  dev      go build (Go has no separate dev mode)  vs  cargo build (dev profile)
  check    cargo check only (Rust's type-check-without-codegen loop; Go has
           no equivalent command, so this track is Rust-only and informational)

Scenarios (hyperfine ``--prepare`` sets up the state before every timed run):

  clean             Go: empty GOCACHE (``go clean -cache``, so the standard
                    library is recompiled); Rust: empty target dir (std ships
                    precompiled)
  clean-std-cached  Go: GOCACHE holding only the precompiled standard library;
                    Rust: as ``clean``. Removes the std asymmetry.
  noop              rebuild with nothing changed
  edit              one constant in one source file gets a never-seen value

All builds run in a private copy of go/ and rust/ under scratch/compile/,
offline (GOPROXY=off, GOFLAGS=-mod=readonly; cargo --offline --locked), with
all cores. hyperfine is used with ``--runs`` per round and rounds alternate
the language order; ``/usr/bin/time`` wraps each build for the compiler
process tree's peak RSS (the largest single process).
"""

from __future__ import annotations

import json
import os
import random
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import orchestrate
from .spec import Spec, Workload
from .util import ROOT, SCRATCH_DIR, log, now_iso, which, write_json

WORK = SCRATCH_DIR / "compile"
TOGGLE = Path(__file__).with_name("edit_toggle.py")

TARGETS = {
    # target: (go packages, rust cargo selection, {lang: (edit file, regex)})
    "hello": ("./hello", ["-p", "bench-hello"],
              {"go": ("hello/main.go", r'(const greeting = "hello)(\d*)(")'),
               "rust": ("hello/src/main.rs", r'(const GREETING: &str = "hello)(\d*)(")')}),
    "http": ("./http", ["-p", "bench-http-axum"],
             {"go": ("internal/api/api.go", r"(const ScoreRounds = )(\d+)(\n)"),
              "rust": ("http-common/src/lib.rs", r"(pub const SCORE_ROUNDS: u32 = )(\d+)(;)")}),
    "suite": ("./...", ["--workspace"],
              {"go": ("internal/harness/harness.go", r"(const schemaVersion = )(\d+)(\n)"),
               "rust": ("common/src/harness.rs", r"(pub const SCHEMA_VERSION: u32 = )(\d+)(;)")}),
}


@dataclass
class CompileConfig:
    rounds: int = 5
    runs_per_round: int = 2


def load_config(spec: Spec, profile: str) -> CompileConfig:
    raw = dict(spec.raw.get("compile", {}))
    prof = raw.pop(profile, {})
    for p in ("quick", "standard", "full"):
        raw.pop(p, None)
    cfg = CompileConfig()
    for src in (raw, prof):
        for k, v in src.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    return cfg


# --------------------------------------------------------------------------- workspace

def prepare_tree() -> None:
    """Fresh private copy of the sources (no build outputs)."""
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "out").mkdir(parents=True)
    shutil.copytree(ROOT / "go", WORK / "go")
    shutil.copytree(ROOT / "rust", WORK / "rust", ignore=shutil.ignore_patterns("target"))


def base_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CARGO_", "RUSTFLAGS", "RUSTC_", "GO", "CGO_"))}
    env.update({
        "GOCACHE": str(WORK / "gocache"), "GOTOOLCHAIN": os.environ.get("GOTOOLCHAIN", "go1.27.1"),
        "GOPROXY": "off", "GOFLAGS": "-mod=readonly", "CGO_ENABLED": "0", "GOAMD64": "v1",
        "CARGO_TARGET_DIR": str(WORK / "target"), "CARGO_NET_OFFLINE": "true",
        "CARGO_HOME": os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")),
    })
    if "GOMODCACHE" in os.environ:
        env["GOMODCACHE"] = os.environ["GOMODCACHE"]
    return env


def build_cmd(lang: str, target: str, track: str) -> list[str]:
    go_pkgs, cargo_sel, _ = TARGETS[target]
    if lang == "go":
        out = str(WORK / "out") + "/" if target == "suite" else str(WORK / "out" / target)
        return ["go", "build", "-trimpath", "-buildvcs=false", "-o", out, go_pkgs]
    verb = "check" if track == "check" else "build"
    prof = ["--release"] if track == "release" else []
    return ["cargo", verb, "--locked", "--offline", "--quiet", *prof, *cargo_sel]


def cwd_for(lang: str) -> Path:
    return WORK / ("go" if lang == "go" else "rust")


def prepare_cmd(lang: str, target: str, scenario: str) -> str:
    if scenario in ("clean", "clean-std-cached"):
        if lang == "go":
            rm = f"rm -rf {WORK / 'gocache'}"
            return rm + (f" && cp -a {WORK / 'gocache-std'} {WORK / 'gocache'}" if scenario == "clean-std-cached" else "")
        return f"rm -rf {WORK / 'target'}"
    if scenario == "edit":
        f, rx = TARGETS[target][2][lang]
        return shlex.join([sys.executable, str(TOGGLE), str(cwd_for(lang) / f), rx])
    return "true"


def warm_std_cache(env: dict) -> None:
    std = WORK / "gocache-std"
    if std.exists():
        return
    e = dict(env, GOCACHE=str(std))
    subprocess.run(["go", "build", "-trimpath", "-buildvcs=false", "std"], cwd=WORK / "go", env=e, check=True,
                   capture_output=True)


# --------------------------------------------------------------------------- measure

def _hyperfine(lang, target, track, scenario, runs, env, cpus, tmp: Path) -> dict:
    hf = which("hyperfine")
    if not hf:
        raise FileNotFoundError("hyperfine not installed (make setup)")
    rss = tmp / "rss.txt"
    rss.unlink(missing_ok=True)
    js = tmp / "hf.json"
    cmd = shlex.join(["/usr/bin/time", "-f", "%M %e %U %S", "-a", "-o", str(rss), *build_cmd(lang, target, track)])
    argv = ["taskset", "-c", cpus, hf, "--style", "none", "--runs", str(runs), "--prepare",
            prepare_cmd(lang, target, scenario), "--export-json", str(js), "--", cmd]
    # The state every scenario starts from: a completed build (noop, edit) or
    # anything (clean*, whose prepare step removes it).
    subprocess.run(build_cmd(lang, target, track), cwd=cwd_for(lang), env=env, capture_output=True)
    p = subprocess.run(argv, cwd=cwd_for(lang), env=env, capture_output=True, text=True, timeout=7200)
    rec = {"cmd": build_cmd(lang, target, track), "prepare": prepare_cmd(lang, target, scenario),
           "hyperfine_argv": argv, "exit_code": p.returncode, "stderr": p.stderr[-3000:]}
    if p.returncode == 0:
        r = json.loads(js.read_text())["results"][0]
        rec["times_s"] = r["times"]
        rec["exit_codes"] = r.get("exit_codes")
        lines = rss.read_text().split("\n") if rss.exists() else []
        vals = [ln.split() for ln in lines if ln.strip() and ln.split()[0].isdigit()][-runs:]
        rec["peak_rss_kb"] = [int(v[0]) for v in vals]
        rec["user_s"] = [float(v[2]) for v in vals]
        rec["system_s"] = [float(v[3]) for v in vals]
    return rec


def _check_edit_rebuilds(env: dict) -> None:
    """Guard against the scenario silently measuring a cache hit: after an edit
    the Go build must report the edited package as rebuilt (go build -x)."""
    f, rx = TARGETS["hello"][2]["go"]
    subprocess.run([sys.executable, str(TOGGLE), str(cwd_for("go") / f), rx], check=True)
    p = subprocess.run([*build_cmd("go", "hello", "release")[:-1], "-x", "./hello"], cwd=cwd_for("go"), env=env,
                       capture_output=True, text=True)
    if "compile" not in p.stderr:
        raise RuntimeError("edit scenario did not trigger a Go recompilation")


def run(spec: Spec, profile: str, run_id: str, mode: str, ids=None, rounds_override=None, resume=False) -> Path:
    cfg = load_config(spec, profile)
    items = [w for w in spec.workloads if w.kind == "compile" and (not ids or w.id in ids)
             and any(profile in s.profiles for s in w.sizes)]
    base = orchestrate.ensure_run_metadata(run_id, mode, profile)
    started = now_iso()
    prepare_tree()
    env = base_env()
    warm_std_cache(env)
    subprocess.run(build_cmd("go", "hello", "release"), cwd=cwd_for("go"), env=env, check=True, capture_output=True)
    _check_edit_rebuilds(env)
    rng = random.Random(spec.seed)
    tmp = WORK / "tmp"
    tmp.mkdir(exist_ok=True)
    for w in items:
        target, track = w.extra["target"], w.extra.get("build_track", "release")
        scenarios = w.extra.get("scenarios", ["clean", "clean-std-cached", "noop", "edit"])
        cpus = spec.cpus(w.cores)
        rounds = rounds_override or cfg.rounds
        for scenario in scenarios:
            for r in range(rounds):
                order = list(w.langs)
                rng.shuffle(order)
                for pos, lang in enumerate(order):
                    path = base / "compile" / w.id / scenario / f"{lang}-r{r:02d}.json"
                    if resume and path.exists():
                        continue
                    rec = {"run_id": run_id, "mode": mode, "profile": profile, "category": "compile",
                           "workload": w.id, "target": target, "build_track": track, "scenario": scenario,
                           "lang": lang, "round": r, "order_in_round": pos, "cpus": cpus}
                    t0 = time.time()
                    try:
                        rec.update(_hyperfine(lang, target, track, scenario, cfg.runs_per_round, env, cpus, tmp))
                        rec["ok"] = rec["exit_code"] == 0 and not any(rec.get("exit_codes") or [])
                    except Exception as e:  # noqa: BLE001 - recorded
                        rec["ok"] = False
                        rec["error"] = f"{type(e).__name__}: {e}"
                    rec["wall_s"] = time.time() - t0
                    write_json(path, rec)
                    ts = rec.get("times_s") or []
                    log(f"[compile {w.id} {scenario} r{r + 1}/{rounds}] {lang:<4} "
                        f"times={' '.join(f'{t:.2f}s' for t in ts)} "
                        f"rss={max(rec.get('peak_rss_kb') or [0]) / 1024:.0f}MiB {'ok' if rec['ok'] else 'FAILED'}")
    orchestrate._record_invocation(base, {"kind": "compile", "categories": ["compile"], "profile": profile,
                                          "ids": ids, "started_at": started, "finished_at": now_iso()})
    return base
