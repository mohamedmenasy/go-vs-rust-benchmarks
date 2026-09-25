"""Turn raw run records into normalized CSV/JSON.

Default: for every category, take the most recent raw run (for the given
mode) that contains it and write the combined tables to
results/processed/<mode>-latest/. With --run-id, process exactly those runs
into results/processed/<run-id>/.

Tables (harness categories):
  runs.csv        one row per process run (timed rounds)
  samples.csv     one row per timed sample
  comparison.csv  one row per (workload, size): Go vs Rust statistics
  summary.json    everything above plus provenance
Special categories (http, startup, binsize, compile) add their own tables.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from benchctl import stats
from benchctl.util import PROCESSED_DIR, RAW_DIR, log, read_json, write_json

SPECIAL = {"http", "startup", "binsize", "compile"}


# --------------------------------------------------------------------------- selection

def list_runs(mode: str) -> list[Path]:
    runs = []
    if not RAW_DIR.exists():
        return runs
    for d in sorted(RAW_DIR.iterdir()):
        meta = d / "run.json"
        if d.is_dir() and meta.exists() and read_json(meta).get("mode") == mode:
            runs.append(d)
    return runs


def _category_finished_at(run: Path, category: str) -> str:
    """When `category` last finished in this run (ISO time), from run.json."""
    meta = read_json(run / "run.json")
    times = [
        inv.get("finished_at", "")
        for inv in meta.get("invocations", [])
        if category in (inv.get("categories") or [category]) or inv.get("kind") == category
    ]
    if times:
        return max(times)
    return ""


def latest_per_category(mode: str) -> dict[str, Path]:
    """category -> the run that most recently completed it (by run.json time)."""
    best: dict[str, tuple[str, Path]] = {}
    for run in list_runs(mode):
        for cat_dir in run.iterdir():
            if not (cat_dir.is_dir() and any(cat_dir.rglob("*.json"))):
                continue
            stamp = _category_finished_at(run, cat_dir.name) or run.name
            if cat_dir.name not in best or stamp >= best[cat_dir.name][0]:
                best[cat_dir.name] = (stamp, run)
    return {cat: run for cat, (_, run) in best.items()}


# --------------------------------------------------------------------------- harness records

def _per_op(res: dict) -> list[float]:
    per = res.get("ops_per_sample", 1) or 1
    return [s / per for s in res.get("samples_ns", [])]


def run_row(rec: dict) -> dict:
    res = rec.get("result") or {}
    work = res.get("work") or {}
    samples = _per_op(res)
    rt = res.get("runtime") or {}
    ru = res.get("rusage_measure") or {}
    meas_ns = sum(res.get("samples_ns", [])) or math.nan
    cpu_ns = (ru.get("utime_ns", 0) + ru.get("stime_ns", 0)) if ru else math.nan
    desc = stats.describe(samples) if samples else {}
    per_run = float(work.get("per_run") or 0)
    ops = sum(res.get("samples_ns", []) and [res.get("ops_per_sample", 1)] * len(res.get("samples_ns", [])))
    row = {
        "run_id": rec.get("run_id"),
        "mode": rec.get("mode"),
        "category": rec.get("category"),
        "workload": rec.get("workload"),
        "track": rec.get("track"),
        "variant_of": rec.get("variant_of"),
        "size": rec.get("size"),
        "lang": rec.get("lang"),
        "round": rec.get("round"),
        "order_in_round": rec.get("order_in_round"),
        "ok": bool(rec.get("ok")),
        "flags": ";".join(rec.get("flags", [])),
        "error": rec.get("error"),
        "checksum": res.get("checksum"),
        "mode_timing": res.get("mode"),
        "unit": work.get("unit"),
        "per_run": per_run,
        "input_bytes": work.get("input_bytes"),
        "n_samples": len(samples),
        "ops_per_sample": res.get("ops_per_sample", 1),
        "median_ns": desc.get("median", math.nan),
        "mean_ns": desc.get("mean", math.nan),
        "min_ns": desc.get("min", math.nan),
        "max_ns": desc.get("max", math.nan),
        "std_ns": desc.get("std", math.nan),
        "cv": desc.get("cv", math.nan),
        "p95_ns": desc.get("p95", math.nan),
        "p99_ns": desc.get("p99", math.nan),
        "throughput_per_s": per_run / (desc["median"] / 1e9) if desc.get("median") else math.nan,
        "cpu_util_measure": cpu_ns / meas_ns if meas_ns and meas_ns == meas_ns else math.nan,
        "user_ns_per_op": ru.get("utime_ns", math.nan) / ops if ops else math.nan,
        "sys_ns_per_op": ru.get("stime_ns", math.nan) / ops if ops else math.nan,
        "cpu_ns_per_op": cpu_ns / ops if ops else math.nan,
        "peak_rss_kb": rec.get("peak_rss_kb"),
        "rss_after_setup_kb": (res.get("rss_kb") or {}).get("after_setup"),
        "rss_end_kb": (res.get("rss_kb") or {}).get("end"),
        "rss_after_teardown_kb": (res.get("rss_kb") or {}).get("after_teardown"),
        "rss_avg_measure_kb": (rec.get("sampler", {}).get("measure") or {}).get("rss_avg_kb"),
        "threads_max": (rec.get("sampler", {}).get("whole") or {}).get("threads_max"),
        "steal_frac": rec.get("steal_frac_pinned"),
        "wall_ns_process": rec.get("wall_ns"),
        "minflt": ru.get("minflt"),
        "nvcsw": ru.get("nvcsw"),
        "nivcsw": ru.get("nivcsw"),
        "alloc_bytes_per_op": (rt.get("alloc_bytes") / ops) if rt.get("alloc_bytes") is not None and ops else math.nan,
        "alloc_objects_per_op": (rt.get("alloc_objects") / ops) if rt.get("alloc_objects") is not None and ops else math.nan,
        "gc_cycles": rt.get("gc_cycles"),
        "gc_pause_total_ns": rt.get("gc_pause_total_ns"),
        "gc_pause_max_ns": rt.get("gc_pause_max_ns"),
        "gc_cpu_fraction": rt.get("gc_cpu_fraction"),
        "go_heap_sys_end": rt.get("heap_sys_end"),
    }
    hist = res.get("histogram")
    if hist:
        hp = stats.hist_percentiles(hist)
        for q in ("p50", "p90", "p95", "p99", "p99.9"):
            row[f"op_{q}_ns"] = hp.get(q)
        row["op_max_ns"] = hp.get("max")
    extra = res.get("extra") or {}
    for k, v in extra.items():
        if isinstance(v, (int, float, str, bool)) or v is None:
            row[f"x_{k}"] = v
    return row


def load_harness_category(run_dir: Path, category: str) -> tuple[list[dict], list[dict], list[dict], dict]:
    runs, samples, allocs = [], [], []
    hists: dict[tuple, list] = defaultdict(list)
    for path in sorted((run_dir / category).rglob("*.json")):
        rec = read_json(path)
        if rec.get("pass") == "allocstats":
            res = rec.get("result") or {}
            rt = res.get("runtime") or {}
            n_ops = sum([res.get("ops_per_sample", 1)] * len(res.get("samples_ns", []))) or 1
            allocs.append({
                "workload": rec.get("workload"),
                "size": rec.get("size"),
                "lang": "rust",
                "ok": rec.get("ok"),
                "alloc_objects_per_op": (rt.get("alloc_objects") or 0) / n_ops,
                "alloc_bytes_per_op": (rt.get("alloc_bytes") or 0) / n_ops,
                "peak_live_bytes": rt.get("peak_live_bytes"),
                "live_bytes_end": rt.get("live_bytes_end"),
            })
            continue
        row = run_row(rec)
        runs.append(row)
        res = rec.get("result") or {}
        for i, s in enumerate(_per_op(res)):
            samples.append({k: row[k] for k in ("run_id", "workload", "size", "lang", "round")} | {"i": i, "ns_per_op": s})
        if res.get("histogram"):
            hists[(row["workload"], row["size"], row["lang"])].append(res["histogram"])
    return runs, samples, allocs, hists


def _med(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return statistics.median(xs) if xs else math.nan


def compare_rows(runs: pd.DataFrame, allocs: pd.DataFrame, hists: dict) -> pd.DataFrame:
    out = []
    if runs.empty:
        return pd.DataFrame()
    for (wl, size), g in runs.groupby(["workload", "size"], sort=False):
        row = {"workload": wl, "size": size, "category": g["category"].iloc[0], "track": g["track"].iloc[0],
               "variant_of": g["variant_of"].iloc[0], "unit": g["unit"].iloc[0], "mode_timing": g["mode_timing"].iloc[0]}
        good = g[g["ok"] & ~g["flags"].str.contains("steal", na=False)]
        per_lang = {lang: good[good["lang"] == lang] for lang in ("go", "rust")}
        checks = set(g[g["ok"]]["checksum"].dropna())
        works = set(zip(g[g["ok"]]["unit"], g[g["ok"]]["per_run"], g[g["ok"]]["input_bytes"].fillna(-1)))
        valid = len(checks) == 1 and len(works) == 1 and all(len(v) for v in per_lang.values())
        row["valid"] = bool(valid)
        row["invalid_reason"] = "" if valid else (
            "checksum mismatch" if len(checks) > 1 else "work mismatch" if len(works) > 1 else "missing runs")
        row["excluded_runs"] = int(len(g) - len(good))
        for lang, df in per_lang.items():
            row[f"{lang}_n"] = int(len(df))
            row[f"{lang}_median_ns"] = _med(df["median_ns"])
            row[f"{lang}_mean_ns"] = float(df["mean_ns"].mean()) if len(df) else math.nan
            row[f"{lang}_min_ns"] = float(df["min_ns"].min()) if len(df) else math.nan
            row[f"{lang}_max_ns"] = float(df["max_ns"].max()) if len(df) else math.nan
            row[f"{lang}_std_between_runs_ns"] = float(df["median_ns"].std(ddof=1)) if len(df) > 1 else math.nan
            row[f"{lang}_cv_within_run"] = _med(df["cv"])
            row[f"{lang}_throughput_per_s"] = _med(df["throughput_per_s"])
            row[f"{lang}_peak_rss_kb"] = _med(df["peak_rss_kb"])
            row[f"{lang}_rss_avg_measure_kb"] = _med(df["rss_avg_measure_kb"])
            row[f"{lang}_cpu_util"] = _med(df["cpu_util_measure"])
            row[f"{lang}_cpu_ns_per_op"] = _med(df["cpu_ns_per_op"])
            row[f"{lang}_sys_ns_per_op"] = _med(df["sys_ns_per_op"])
            row[f"{lang}_threads_max"] = _med(df["threads_max"])
            key = (wl, size, lang)
            if key in hists:
                hp = stats.hist_percentiles(stats.merge_hists(hists[key]))
                for q in ("p50", "p95", "p99", "p99.9"):
                    row[f"{lang}_op_{q}_ns"] = hp.get(q)
                row[f"{lang}_op_max_ns"] = hp.get("max")
            else:
                pooled = [s for s in df["median_ns"]]
                if pooled:
                    row[f"{lang}_op_p50_ns"] = float(np.percentile(pooled, 50))
        go_alloc = per_lang["go"]
        row["go_alloc_objects_per_op"] = _med(go_alloc["alloc_objects_per_op"]) if len(go_alloc) else math.nan
        row["go_alloc_bytes_per_op"] = _med(go_alloc["alloc_bytes_per_op"]) if len(go_alloc) else math.nan
        row["go_gc_cycles"] = _med(go_alloc["gc_cycles"]) if len(go_alloc) else math.nan
        row["go_gc_cpu_fraction"] = _med(go_alloc["gc_cpu_fraction"]) if len(go_alloc) else math.nan
        row["go_gc_pause_max_ns"] = float(go_alloc["gc_pause_max_ns"].max()) if len(go_alloc) else math.nan
        ra = allocs[(allocs["workload"] == wl) & (allocs["size"] == size)] if not allocs.empty else allocs
        row["rust_alloc_objects_per_op"] = float(ra["alloc_objects_per_op"].iloc[0]) if len(ra) else math.nan
        row["rust_alloc_bytes_per_op"] = float(ra["alloc_bytes_per_op"].iloc[0]) if len(ra) else math.nan
        row["rust_peak_live_bytes"] = float(ra["peak_live_bytes"].iloc[0]) if len(ra) and ra["peak_live_bytes"].iloc[0] is not None else math.nan
        a = per_lang["go"]["median_ns"].to_numpy(dtype=float)
        b = per_lang["rust"]["median_ns"].to_numpy(dtype=float)
        cmp = stats.compare(a, b, lower_is_better=True)
        row["ratio_rust_over_go"] = cmp.ratio
        row["ratio_ci_low"] = cmp.ci_low
        row["ratio_ci_high"] = cmp.ci_high
        row["p_value"] = cmp.p_value
        row["significant"] = cmp.significant
        row["verdict"] = {"a_better": "go_faster", "b_better": "rust_faster"}.get(cmp.verdict, cmp.verdict)
        row["abs_diff_ns"] = row["rust_median_ns"] - row["go_median_ns"]
        row["pct_diff"] = stats.pct_diff(row["go_median_ns"], row["rust_median_ns"])
        row["mem_pct_diff"] = stats.pct_diff(row["go_peak_rss_kb"], row["rust_peak_rss_kb"])
        row["cpu_pct_diff"] = stats.pct_diff(row["go_cpu_ns_per_op"], row["rust_cpu_ns_per_op"])
        out.append(row)
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- driver

def process(sources: dict[str, Path], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    all_runs, all_samples, all_allocs, all_hists = [], [], [], {}
    provenance = {}
    extra_tables: dict[str, pd.DataFrame] = {}
    for category, run_dir in sorted(sources.items()):
        provenance[category] = run_dir.name
        if category in SPECIAL:
            try:
                mod = __import__(f"analysis.{category}", fromlist=["process"])
            except ImportError:
                log(f"no processor for special category {category}", level="warn")
                continue
            for name, df in mod.process(run_dir).items():
                extra_tables[name] = pd.concat([extra_tables.get(name, pd.DataFrame()), df], ignore_index=True)
            continue
        runs, samples, allocs, hists = load_harness_category(run_dir, category)
        all_runs += runs
        all_samples += samples
        all_allocs += allocs
        all_hists.update(hists)
    runs_df = pd.DataFrame(all_runs)
    samples_df = pd.DataFrame(all_samples)
    allocs_df = pd.DataFrame(all_allocs)
    cmp_df = compare_rows(runs_df, allocs_df, all_hists)
    runs_df.to_csv(out_dir / "runs.csv", index=False)
    samples_df.to_csv(out_dir / "samples.csv", index=False)
    allocs_df.to_csv(out_dir / "allocs_rust.csv", index=False)
    cmp_df.to_csv(out_dir / "comparison.csv", index=False)
    for name, df in extra_tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
    env = {}
    for category, run_dir in sources.items():
        envp = run_dir / "environment.json"
        if envp.exists():
            env[run_dir.name] = read_json(envp)
    summary = {
        "sources": provenance,
        "environments": {k: {"cpu": v.get("cpu", {}).get("Model name"), "kernel": v.get("kernel"),
                             "go": v.get("toolchains", {}).get("go_version"),
                             "rustc": (v.get("toolchains", {}).get("rustc") or "").splitlines()[0:1],
                             "mode": v.get("mode"), "captured_at": v.get("captured_at")}
                         for k, v in env.items()},
        "comparison": cmp_df.replace({np.nan: None}).to_dict(orient="records"),
        "tables": sorted(["runs", "samples", "allocs_rust", "comparison", *extra_tables]),
    }
    fingerprints = {(e.get("cpu"), e.get("kernel"), str(e.get("go")), str(e.get("rustc"))) for e in summary["environments"].values()}
    if len(fingerprints) > 1:
        log("WARNING: combined runs come from different environments; see summary.json 'environments'", level="warn")
        summary["mixed_environments"] = True
    write_json(out_dir / "summary.json", summary, indent=1)
    return summary


def main(args) -> int:
    mode = args.mode
    if args.run_id:
        for rid in args.run_id:
            run_dir = RAW_DIR / rid
            if not run_dir.exists():
                log(f"no such run {rid}", level="error")
                return 1
            sources = {d.name: run_dir for d in run_dir.iterdir() if d.is_dir()}
            s = process(sources, PROCESSED_DIR / rid)
            log(f"processed {rid}: {len(s['comparison'])} comparisons -> results/processed/{rid}")
    sources = latest_per_category(mode)
    if not sources:
        log(f"no raw runs for mode={mode}", level="warn")
        return 0
    out = PROCESSED_DIR / f"{mode}-latest"
    s = process(sources, out)
    invalid = [c for c in s["comparison"] if not c.get("valid")]
    log(f"processed latest {mode} runs ({', '.join(f'{k}:{v}' for k, v in s['sources'].items())}) "
        f"-> {out.relative_to(PROCESSED_DIR.parent.parent)}; {len(s['comparison'])} comparisons, {len(invalid)} invalid")
    for c in invalid:
        log(f"INVALID {c['workload']} {c['size']}: {c['invalid_reason']}", level="error")
    return 0
