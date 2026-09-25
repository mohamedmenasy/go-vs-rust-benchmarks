"""Run harness-protocol workloads: randomized, interleaved process-level
rounds, raw record per process, plus the separate Rust allocation-profile
pass. Special categories (HTTP, startup, binary size, compilation) have their
own drivers but share the raw-results layout written here."""

from __future__ import annotations

import os
import random
import statistics
import time
from pathlib import Path

from . import builds, envinfo, runner, services
from .spec import Size, Spec, Workload
from .util import RAW_DIR, human_bytes, human_ns, log, now_iso, parse_cpuset, read_json, write_json

STEAL_FLAG = 0.05  # runs with >5% steal on their CPUs are flagged (METHODOLOGY.md)


def pin_self(spec: Spec) -> None:
    """Keep the orchestrator (and its sampler threads) off the benchmark CPUs."""
    cpus = set(parse_cpuset(spec.cores.get("harness", ""))) if spec.cores.get("harness") else set()
    avail = os.sched_getaffinity(0)
    if cpus and cpus <= avail:
        os.sched_setaffinity(0, cpus)


def harness_args(w: Workload, size: Size, lang: str, timing: dict, command: str = "run") -> list[str]:
    args = [command, w.impl_for(lang)]
    for k, v in size.params.items():
        args += ["--param", f"{k}={v}"]
    if command == "run":
        for key, flag in (
            ("warmup_iters", "--warmup-iters"),
            ("warmup_min_ms", "--warmup-min-ms"),
            ("iters", "--iters"),
            ("min_ms", "--min-ms"),
            ("max_iters", "--max-iters"),
            ("max_ms", "--max-ms"),
            ("batch_min_ms", "--batch-min-ms"),
        ):
            if key in timing:
                args += [flag, str(timing[key])]
    return args


def allocstats_flavor(flavor: str) -> str:
    return f"{flavor}-allocstats" if flavor else "allocstats"


def run_one(
    spec: Spec,
    w: Workload,
    size: Size,
    lang: str,
    timing: dict,
    *,
    flavor: str | None = None,
    command: str = "run",
    pin: bool = True,
    keep_series: bool = True,
) -> dict:
    flavor = w.flavor_for(lang) if flavor is None else flavor
    binary = builds.bin_path(lang, w.bin, flavor)
    cpus = spec.cpus(w.cores) if pin else None
    ncpus = spec.ncpus(w.cores)
    env = runner.sanitized_env({**runner.thread_env(lang, ncpus), **w.env_for(lang)})
    if not binary.exists():
        return {"ok": False, "error": f"binary not found: {binary} (run `make build`)", "result": None}
    rec = runner.run(
        runner.ProcSpec(
            argv=[str(binary), *harness_args(w, size, lang, timing, command)],
            cpus=cpus,
            env=env,
            timeout_s=w.timeout_s,
            sample_interval_s=w.sample_ms / 1000,
            keep_series=keep_series,
        )
    )
    rec["env"] = {k: v for k, v in env.items() if k not in ("PATH", "HOME", "USER", "TMPDIR")}
    rec["binary"] = str(binary)
    rec["flavor"] = flavor
    return rec


def ensure_run_metadata(run_id: str, mode: str, profile: str) -> Path:
    base = RAW_DIR / run_id
    base.mkdir(parents=True, exist_ok=True)
    if not (base / "environment.json").exists():
        write_json(base / "environment.json", envinfo.capture(mode), indent=1)
    if not (base / "build.json").exists():
        write_json(base / "build.json", builds.build_manifest(), indent=1)
    meta_path = base / "run.json"
    meta = read_json(meta_path) if meta_path.exists() else {"run_id": run_id, "mode": mode, "invocations": []}
    meta["profile"] = profile
    write_json(meta_path, meta, indent=1)
    return base


def _record_invocation(base: Path, entry: dict) -> None:
    meta_path = base / "run.json"
    meta = read_json(meta_path)
    meta.setdefault("invocations", []).append(entry)
    write_json(meta_path, meta, indent=1)


def _flags(rec: dict) -> list[str]:
    flags = []
    if not rec.get("ok"):
        flags.append("failed")
    if rec.get("steal_frac_pinned", 0) > STEAL_FLAG:
        flags.append("steal")
    return flags


def _summary_line(rec: dict) -> str:
    res = rec.get("result") or {}
    samples = res.get("samples_ns") or []
    if not rec.get("ok") or not samples:
        return f"FAILED: {rec.get('error')}"
    per = res.get("ops_per_sample", 1) or 1
    med = statistics.median(samples) / per
    cv = statistics.pstdev(samples) / statistics.mean(samples) * 100 if len(samples) > 1 else 0.0
    rss = rec.get("peak_rss_kb", -1) * 1024
    unit = "/op" if res.get("mode") == "op" else ""
    return f"median={human_ns(med)}{unit} cv={cv:.1f}% n={len(samples)} maxrss={human_bytes(rss)} steal={rec['steal_frac_pinned'] * 100:.1f}%"


def run_harness(
    spec: Spec,
    profile: str,
    run_id: str,
    mode: str,
    categories: list[str] | None = None,
    ids: list[str] | None = None,
    tracks: list[str] | None = None,
    rounds_override: int | None = None,
    resume: bool = False,
    alloc_pass: bool = True,
) -> Path:
    items = spec.select(profile, categories, ids, tracks, kinds={"harness"})
    if not items:
        log(f"no harness workloads selected (profile={profile}, categories={categories}, ids={ids})", level="warn")
    base = ensure_run_metadata(run_id, mode, profile)
    started = now_iso()
    pin_self(spec)
    rng = random.Random(spec.seed)
    checksums: dict[tuple[str, str], set[str]] = {}
    total_rounds = {id(w): rounds_override or spec.rounds_for(profile, w) for w, _ in items}
    max_rounds = max(total_rounds.values(), default=0)
    n_total = sum(total_rounds[id(w)] * len(w.langs) for w, _ in items)
    t0 = time.monotonic()
    with services.for_workloads(spec, [w for w, _ in items]):
        _rounds_and_alloc_pass(spec, profile, run_id, mode, items, total_rounds, max_rounds, base, rng, checksums,
                               n_total, t0, resume, alloc_pass)
    _record_invocation(
        base,
        {
            "kind": "harness",
            "profile": profile,
            "categories": categories,
            "ids": ids,
            "started_at": started,
            "finished_at": now_iso(),
        },
    )
    return base


def _rounds_and_alloc_pass(spec, profile, run_id, mode, items, total_rounds, max_rounds, base, rng, checksums,
                           n_total, t0, resume, alloc_pass) -> None:
    n_done = 0
    for r in range(max_rounds):
        for w, size in items:
            if r >= total_rounds[id(w)]:
                continue
            order = list(w.langs)
            rng.shuffle(order)
            timing = spec.timing_for(profile, w)
            for pos, lang in enumerate(order):
                n_done += 1
                path = base / w.category / w.id / size.label / f"{lang}-r{r:02d}.json"
                if resume and path.exists():
                    continue
                rec = run_one(spec, w, size, lang, timing)
                rec.update(
                    {
                        "run_id": run_id,
                        "mode": mode,
                        "profile": profile,
                        "category": w.category,
                        "workload": w.id,
                        "track": w.track,
                        "variant_of": w.variant_of,
                        "impl": w.impl_for(lang),
                        "size": size.label,
                        "params": size.params,
                        "lang": lang,
                        "round": r,
                        "order_in_round": pos,
                        "timing": timing,
                        "flags": [],
                    }
                )
                rec["flags"] = _flags(rec)
                write_json(path, rec)
                res = rec.get("result") or {}
                if rec.get("ok"):
                    cs = checksums.setdefault((w.id, size.label), set())
                    cs.add(res.get("checksum", ""))
                    if len(cs) > 1:
                        log(f"{w.id} {size.label}: CHECKSUM MISMATCH across runs/languages: {sorted(cs)}", level="error")
                eta = (time.monotonic() - t0) / n_done * (n_total - n_done)
                log(
                    f"[{n_done}/{n_total} r{r + 1}/{total_rounds[id(w)]} eta {eta / 60:.0f}m] "
                    f"{w.id} {size.label} {lang:<4} {_summary_line(rec)}"
                )
    if alloc_pass:
        for w, size in items:
            if not w.alloc_pass or "rust" not in w.langs:
                continue
            # Allocation counts come from the stock build only: flavoured builds
            # (LTO, mimalloc) allocate the same objects, and a counting global
            # allocator cannot wrap mimalloc anyway.
            if w.flavor_for("rust"):
                continue
            path = base / w.category / w.id / size.label / "rust-allocstats.json"
            if resume and path.exists():
                continue
            flavor = allocstats_flavor(w.flavor_for("rust"))
            timing = spec.timing_for(profile, w)
            rec = run_one(spec, w, size, "rust", timing, flavor=flavor, keep_series=False)
            rec.update(
                {
                    "run_id": run_id,
                    "mode": mode,
                    "profile": profile,
                    "category": w.category,
                    "workload": w.id,
                    "size": size.label,
                    "lang": "rust",
                    "pass": "allocstats",
                    "flags": _flags(rec),
                }
            )
            write_json(path, rec)
            log(f"[alloc-profile] {w.id} {size.label} rust {_summary_line(rec)}")
