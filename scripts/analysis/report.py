"""Refresh the generated tables in REPORT.md from results/processed/<mode>-latest.

Only text between ``<!-- BEGIN generated:NAME -->`` and ``<!-- END generated:NAME -->``
is replaced; everything else (the written analysis) is left untouched. A
missing REPORT.md is created from a skeleton containing every marker.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import pandas as pd

from benchctl.util import ROOT, log

REPORT = ROOT / "REPORT.md"
HARNESS = ["cpu", "memory", "json", "concurrency", "io", "strings", "collections"]
VERDICT = {"go_faster": "**Go faster**", "rust_faster": "**Rust faster**", "go_better": "**Go better**",
           "rust_better": "**Rust better**", "no_measurable_difference": "no measurable difference",
           "insufficient_rounds": "insufficient rounds", "insufficient_data": "insufficient data",
           "single_language": "Rust only"}


# --------------------------------------------------------------------------- formatting

def _nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def t(ns) -> str:
    if _nan(ns):
        return "–"
    for unit, f in (("s", 1e9), ("ms", 1e6), ("µs", 1e3)):
        if abs(ns) >= f:
            return f"{ns / f:.3g} {unit}"
    return f"{ns:.3g} ns"


def secs(s) -> str:
    return "–" if _nan(s) else (f"{s:.3g} s" if s >= 1 else f"{s * 1e3:.3g} ms")


def mib(kb) -> str:
    return "–" if _nan(kb) else f"{kb / 1024:.3g} MiB"


def pct(v) -> str:
    return "–" if _nan(v) else f"{v:+.1f}%"


def ratio_ci(r, lo, hi) -> str:
    if _nan(r):
        return "–"
    pc = (r - 1) * 100
    if _nan(lo):
        return f"{pc:+.1f}%"
    return f"{pc:+.1f}% [{(lo - 1) * 100:+.1f}, {(hi - 1) * 100:+.1f}]"


def table(header: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_No results in the processed data set._"
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
    return "\n".join(out)


def _read(proc: Path, name: str) -> pd.DataFrame:
    f = proc / f"{name}.csv"
    return pd.read_csv(f) if f.exists() and f.stat().st_size > 1 else pd.DataFrame()


# --------------------------------------------------------------------------- sections

def harness_table(cmp: pd.DataFrame, cat: str) -> str:
    d = cmp[cmp["category"] == cat] if not cmp.empty else cmp
    rows = []
    for r in d.itertuples():
        notes = []
        if not r.valid:
            notes.append(f"INVALID: {r.invalid_reason}")
        if r.excluded_runs:
            notes.append(f"{r.excluded_runs} runs excluded")
        if r.track != "baseline":
            notes.append(r.track)
        name = r.workload.split(".", 1)[1]
        rows.append([f"`{name}` {r.size}", t(r.go_median_ns), t(r.rust_median_ns), t(r.abs_diff_ns),
                     ratio_ci(r.ratio_rust_over_go, r.ratio_ci_low, r.ratio_ci_high), pct(r.mem_pct_diff),
                     pct(r.cpu_pct_diff), VERDICT.get(r.verdict, r.verdict), "; ".join(notes)])
    return table(["Workload", "Go (median)", "Rust (median)", "Abs diff", "% diff Rust vs Go (95% CI)",
                  "Peak RSS diff", "CPU/op diff", "Verdict", "Notes"], rows)


def http_table(proc: Path) -> str:
    c = _read(proc, "http_comparison")
    rows = []
    for r in c.itertuples() if not c.empty else []:
        if r.test == "throughput":
            go, ru = f"{r.go_rps:,.0f} rps", f"{r.rust_rps:,.0f} rps"
        else:
            go, ru = f"p99 {r.go_lat_p99_us / 1000:.3g} ms", f"p99 {r.rust_lat_p99_us / 1000:.3g} ms"
        eff = f"{r.go_requests_per_cpu_second:,.0f} / {r.rust_requests_per_cpu_second:,.0f}"
        notes = []
        if r.excluded_runs:
            notes.append(f"{r.excluded_runs} runs excluded ({r.loadgen_saturated_runs} load-generator saturated)")
        rows.append([r.workload.split(".", 1)[1], r.test, r.level, go, ru,
                     ratio_ci(r.ratio_rust_over_go, r.ratio_ci_low, r.ratio_ci_high),
                     f"{mib(r.go_server_rss_peak_kb)} / {mib(r.rust_server_rss_peak_kb)}", eff,
                     VERDICT.get(r.verdict, r.verdict), "; ".join(notes)])
    return table(["Server pair", "Test", "Level", "Go", "Rust", "% diff (95% CI)", "Peak RSS Go / Rust",
                  "Req per CPU-s Go / Rust", "Verdict", "Notes"], rows)


def sustained_table(proc: Path) -> str:
    from analysis.http import sustained_summary

    s = sustained_summary(_read(proc, "http_sustained"))
    rows = [[r.workload.split(".", 1)[1], r.level, r.lang, r.windows, f"{r.rps_median:,.0f}", f"{r.rps_min:,.0f}",
             f"{r.rps_cv * 100:.1f}%", f"{r.p99_median_us / 1000:.3g} ms", f"{r.p99_worst_us / 1000:.3g} ms",
             "–" if _nan(r.rss_slope_mib_per_min) else f"{r.rss_slope_mib_per_min:+.2f}", mib(r.server_hwm_kb)]
            for r in s.itertuples()] if not s.empty else []
    return table(["Server pair", "Load", "Lang", "Windows", "RPS median", "RPS min", "RPS CV", "p99 median",
                  "p99 worst", "RSS slope MiB/min", "Peak RSS"], rows)


def startup_table(proc: Path) -> str:
    c = _read(proc, "startup_comparison")
    rows = []
    for r in c.itertuples() if not c.empty else []:
        rows.append([r.workload.split(".", 1)[1], r.metric,
                     f"{r.go_median:.3g} ms (p95 {r.go_p95:.3g})", f"{r.rust_median:.3g} ms (p95 {r.rust_p95:.3g})",
                     f"{r.go_std:.2g} / {r.rust_std:.2g}", ratio_ci(r.ratio_rust_over_go, r.ratio_ci_low, r.ratio_ci_high),
                     VERDICT.get(r.verdict, r.verdict), r.track])
    return table(["Workload", "Metric", "Go median", "Rust median", "Std Go / Rust (ms)", "% diff (95% CI)",
                  "Verdict", "Track"], rows)


def binsize_table(proc: Path) -> str:
    p = _read(proc, "binsize_pairs")
    rows = [[r.pair, r.program, mib(r.go_bytes / 1024), mib(r.rust_bytes / 1024), f"{r.ratio_rust_over_go:.2f}×",
             f"{mib(r.go_stripped_bytes / 1024)} / {mib(r.rust_stripped_bytes / 1024)}",
             f"{'static' if r.go_static else 'dynamic'} / {'static' if r.rust_static else 'dynamic'}"]
            for r in p.itertuples()] if not p.empty else []
    return table(["Recipe pair", "Program", "Go", "Rust", "Rust / Go", "After GNU strip Go / Rust",
                  "Linking Go / Rust"], rows)


def deps_table(proc: Path) -> str:
    d = _read(proc, "binsize_deps")
    rows = [[r.program, r.go_packages_std, r.go_packages_nonstd, r.go_modules, r.rust_crates]
            for r in d.itertuples()] if not d.empty else []
    return table(["Program", "Go std packages", "Go non-std packages", "Go external modules",
                  "Rust external crates"], rows)


def compile_table(proc: Path) -> str:
    c = _read(proc, "compile_comparison")
    rows = []
    for r in c.itertuples() if not c.empty else []:
        rows.append([r.workload.split(".", 1)[1], r.build_track, r.scenario, secs(r.go_time_median),
                     secs(r.rust_time_median), ratio_ci(getattr(r, "ratio_rust_over_go", math.nan),
                                                        getattr(r, "ratio_ci_low", math.nan),
                                                        getattr(r, "ratio_ci_high", math.nan)),
                     f"{mib(r.go_peak_rss_kb_median)} / {mib(r.rust_peak_rss_kb_median)}",
                     f"{secs(r.go_cpu_s_median)} / {secs(r.rust_cpu_s_median)}", VERDICT.get(r.verdict, r.verdict)])
    return table(["Target", "Track", "Scenario", "Go", "Rust", "% diff (95% CI)", "Peak compiler RSS Go / Rust",
                  "CPU time Go / Rust", "Verdict"], rows)


def provenance(proc: Path) -> str:
    s = json.loads((proc / "summary.json").read_text())
    rows = [[cat, f"`{rid}`"] for cat, rid in sorted(s.get("sources", {}).items())]
    envs = []
    for rid, e in s.get("environments", {}).items():
        rustc = e.get("rustc")
        envs.append(f"- `{rid}`: {e.get('cpu')}, kernel {e.get('kernel')}, {e.get('go')}, "
                    f"{rustc[0] if isinstance(rustc, list) and rustc else rustc}, mode {e.get('mode')}, "
                    f"captured {e.get('captured_at')}")
    warn = "\n\n**Warning: the combined runs come from different environments.**" if s.get("mixed_environments") else ""
    return table(["Category", "Raw run"], rows) + "\n\n" + "\n".join(sorted(set(envs))) + warn


def sections(proc: Path) -> dict[str, str]:
    cmp = _read(proc, "comparison")
    out = {"provenance": provenance(proc)}
    for cat in HARNESS:
        out[cat] = harness_table(cmp, cat)
    out.update({"http": http_table(proc), "http-sustained": sustained_table(proc), "startup": startup_table(proc),
                "binsize": binsize_table(proc), "binsize-deps": deps_table(proc), "compile": compile_table(proc)})
    return out


def skeleton(names) -> str:
    parts = ["# Go vs Rust: benchmark report\n"]
    for n in names:
        parts.append(f"## {n}\n\n<!-- BEGIN generated:{n} -->\n<!-- END generated:{n} -->\n")
    return "\n".join(parts)


def render(text: str, secs_: dict[str, str]) -> tuple[str, list[str]]:
    missing = []
    for name, body in secs_.items():
        pat = re.compile(rf"(<!-- BEGIN generated:{re.escape(name)} -->\n).*?(<!-- END generated:{re.escape(name)} -->)",
                         re.S)
        if not pat.search(text):
            missing.append(name)
            continue
        text = pat.sub(lambda m: m[1] + body.rstrip() + "\n" + m[2], text)
    return text, missing


def main(args=None) -> int:
    mode = getattr(args, "mode", "native") if args is not None else "native"
    proc = ROOT / "results" / "processed" / f"{mode}-latest"
    if getattr(args, "run_id", None):
        proc = ROOT / "results" / "processed" / args.run_id[0]
    if not (proc / "summary.json").exists():
        log(f"{proc}: no processed results (run `make process`)", level="error")
        return 1
    secs_ = sections(proc)
    text = REPORT.read_text() if REPORT.exists() else skeleton(secs_)
    text, missing = render(text, secs_)
    REPORT.write_text(text)
    for m in missing:
        log(f"REPORT.md has no marker for '{m}'", level="warn")
    log(f"REPORT.md tables refreshed from {proc.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="native")
    raise SystemExit(main(ap.parse_args()))
