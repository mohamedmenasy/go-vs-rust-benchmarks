"""Charts from results/processed/<id>/ (PNG, matplotlib).

Conventions (kept identical across charts):
  * Go = categorical slot 1 (blue), Rust = slot 2 (orange); the pair was
    checked with the dataviz palette validator (CVD dE 24.7, contrast >= 3:1).
    Identity is never color-only: every two-series chart has a legend.
  * One y-scale per chart; ratios on a log axis centred on 1.0.
  * Recessive grid, no top/right spines, thin marks with surface gaps.

usage: python -m analysis.charts [PROCESSED_DIR] [--out charts/<id>]
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from benchctl.util import ROOT, log  # noqa: E402

COLORS = {"go": "#2a78d6", "rust": "#eb6834"}
LABELS = {"go": "Go", "rust": "Rust"}
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "axes.titlecolor": INK, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "xtick.color": INK2, "ytick.color": INK2, "font.size": 9, "legend.frameon": False,
    "legend.labelcolor": INK2, "figure.dpi": 110,
})


PLAIN = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}")


def _save(fig, out: Path, name: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{name}.png", bbox_inches="tight")
    plt.close(fig)
    log(f"chart {name}.png")


def _read(proc: Path, name: str) -> pd.DataFrame:
    f = proc / f"{name}.csv"
    return pd.read_csv(f) if f.exists() and f.stat().st_size > 1 else pd.DataFrame()


def _footer(fig, text: str) -> None:
    fig.text(0.01, -0.01, text, fontsize=7.5, color=MUTED, ha="left", va="top")


# --------------------------------------------------------------------------- forest (harness categories)

def forest(cmp: pd.DataFrame, category: str, out: Path) -> None:
    d = cmp[(cmp["category"] == category) & cmp["ratio_rust_over_go"].notna()].copy()
    if d.empty:
        return
    d["label"] = d["workload"].str.split(".", n=1).str[1] + "  [" + d["size"].astype(str) + "]"
    d.loc[d["track"] != "baseline", "label"] += "  (" + d["track"] + ")"
    d = d.iloc[::-1]
    y = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(8, 0.28 * len(d) + 1.4))
    sig = d["verdict"].isin(["go_faster", "rust_faster"]).to_numpy()
    lo = (d["ratio_rust_over_go"] - d["ratio_ci_low"]).clip(lower=0).fillna(0)
    hi = (d["ratio_ci_high"] - d["ratio_rust_over_go"]).clip(lower=0).fillna(0)
    for mask, col, lab in ((sig, INK, "difference detected"), (~sig, MUTED, "no measurable difference / insufficient")):
        if mask.any():
            ax.errorbar(d["ratio_rust_over_go"][mask], y[mask], xerr=[lo[mask], hi[mask]], fmt="o", ms=5,
                        color=col, ecolor=col, elinewidth=1.2, capsize=0, label=lab)
    ax.axvline(1.0, color=INK2, lw=1)
    ax.set_xscale("log")
    ax.set_yticks(y, d["label"])
    ax.grid(axis="y", visible=False)
    lim = max(2.0, float(np.nanmax(d[["ratio_ci_high", "ratio_rust_over_go"]].to_numpy())) * 1.1,
              1 / max(1e-9, float(np.nanmin(d[["ratio_ci_low", "ratio_rust_over_go"]].to_numpy()))) * 1.1)
    ax.set_xlim(1 / lim, lim)
    ticks = [t for t in (0.05, 0.1, 0.2, 0.5, 0.8, 1, 1.25, 2, 5, 10, 20) if 1 / lim <= t <= lim]
    ax.set_xticks(ticks)
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}×"))
    ax.set_xlabel("Rust / Go median time  (← Rust faster · Go faster →)\nCI over per-process medians; flagged runs excluded")
    ax.set_title(f"{category}: time ratio with 95% bootstrap CI")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32 if len(d) < 8 else -0.2), ncol=2, fontsize=8)
    _save(fig, out, f"{category}_ratio")


def paired_bars(d: pd.DataFrame, labels, go_vals, rust_vals, title, xlabel, out, name, log_x=False, fmt="{:.3g}"):
    y = np.arange(len(d))
    h = 0.38
    fig, ax = plt.subplots(figsize=(8, 0.34 * len(d) + 1.4))
    # y is inverted below, so the negative offset draws Go above Rust (legend order).
    for off, vals, lang in ((-h / 2, go_vals, "go"), (h / 2, rust_vals, "rust")):
        ax.barh(y + off, vals, height=h - 0.06, color=COLORS[lang], label=LABELS[lang], edgecolor=SURFACE, linewidth=1)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    if log_x:
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(PLAIN)
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    ax.legend(loc="lower right", fontsize=8)
    _save(fig, out, name)


def memory(cmp: pd.DataFrame, category: str, out: Path) -> None:
    d = cmp[(cmp["category"] == category) & (cmp["track"] == "baseline")].dropna(subset=["go_peak_rss_kb", "rust_peak_rss_kb"])
    if d.empty:
        return
    labels = d["workload"].str.split(".", n=1).str[1] + " [" + d["size"].astype(str) + "]"
    paired_bars(d, labels, d["go_peak_rss_kb"] / 1024, d["rust_peak_rss_kb"] / 1024,
                f"{category}: peak RSS (median over runs, baseline track)", "MiB (log)", out, f"{category}_peak_rss",
                log_x=True)


# --------------------------------------------------------------------------- special categories

def http_charts(proc: Path, out: Path) -> None:
    runs = _read(proc, "http_runs")
    if runs.empty:
        return
    ok = runs[runs["ok"] & ~runs["flags"].fillna("").str.contains("failed")]
    for wl, g in ok[ok["test"] == "throughput"].groupby("workload"):
        fig, ax = plt.subplots(figsize=(7, 3.8))
        for lang in ("go", "rust"):
            s = g[g["lang"] == lang].groupby("connections")["rps"].agg(["median", "min", "max"])
            ax.fill_between(s.index, s["min"], s["max"], color=COLORS[lang], alpha=0.15, lw=0)
            ax.plot(s.index, s["median"], marker="o", ms=5, lw=2, color=COLORS[lang], label=LABELS[lang])
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(PLAIN)
        ax.set_xlabel("concurrent connections (wrk, closed loop)")
        ax.set_ylabel("requests / s")
        ax.set_title(f"{wl}: throughput by concurrency (median, band = min–max)")
        ax.legend()
        _save(fig, out, f"http_{wl.split('.', 1)[1]}_throughput")
        fig, ax = plt.subplots(figsize=(7, 3.8))
        for lang in ("go", "rust"):
            s = g[g["lang"] == lang].groupby("connections")["lat_p99_us"].median() / 1000
            ax.plot(s.index, s.values, marker="o", ms=5, lw=2, color=COLORS[lang], label=LABELS[lang])
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.xaxis.set_major_formatter(PLAIN)
        ax.yaxis.set_major_formatter(PLAIN)
        ax.set_xlabel("concurrent connections")
        ax.set_ylabel("p99 latency, ms (log)")
        ax.set_title(f"{wl}: closed-loop p99 latency by concurrency")
        ax.legend()
        _save(fig, out, f"http_{wl.split('.', 1)[1]}_p99_closed")
    lat = ok[ok["test"] == "latency"]
    pcts = ["50", "75", "90", "95", "99", "99.9", "99.99"]
    for (wl, lvl), g in lat.groupby(["workload", "level"]):
        fig, ax = plt.subplots(figsize=(7, 3.8))
        x = np.arange(len(pcts))
        for lang in ("go", "rust"):
            v = [g[g["lang"] == lang][f"lat_p{p}_us"].median() / 1000 for p in pcts]
            ax.plot(x, v, marker="o", ms=5, lw=2, color=COLORS[lang], label=LABELS[lang])
        ax.set_xticks(x, [f"p{p}" for p in pcts])
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(PLAIN)
        ax.set_ylabel("latency, ms (log)")
        rate = g["target_rps"].iloc[0]
        ax.set_title(f"{wl}: open-loop latency at {rate:,.0f} req/s ({lvl[1:]}% of the slower server's capacity)")
        ax.legend()
        _footer(fig, "wrk2, coordinated-omission corrected; same absolute rate for both servers.")
        _save(fig, out, f"http_{wl.split('.', 1)[1]}_latency_{lvl}")
    sus = _read(proc, "http_sustained")
    for (wl, lvl), g in (sus.groupby(["workload", "level"]) if not sus.empty else []):
        fig, axes = plt.subplots(2, 1, figsize=(7, 5), sharex=True)
        for lang in ("go", "rust"):
            s = g[g["lang"] == lang].sort_values("t_s")
            axes[0].plot(s["t_s"], s["rps"], lw=2, color=COLORS[lang], label=LABELS[lang])
            axes[1].plot(s["t_s"], s["server_rss_avg_kb"] / 1024, lw=2, color=COLORS[lang], label=LABELS[lang])
        axes[0].set_ylabel("requests / s")
        axes[1].set_ylabel("server RSS, MiB")
        axes[1].set_xlabel("seconds under load")
        axes[0].set_title(f"{wl}: sustained load {lvl} (10 s windows)")
        axes[0].legend()
        _save(fig, out, f"http_{wl.split('.', 1)[1]}_sustained_{lvl}")


def startup_charts(proc: Path, out: Path) -> None:
    s = _read(proc, "startup_samples")
    if s.empty:
        return
    for (wl, test), g in s.groupby(["workload", "test"]):
        metric = "exec_to_exit_ms" if test == "cli" else "health_ms"
        fig, ax = plt.subplots(figsize=(7, 3.6))
        for lang in ("go", "rust"):
            v = np.sort(g[g["lang"] == lang][metric].dropna().to_numpy())
            if len(v):
                ax.step(v, np.arange(1, len(v) + 1) / len(v), where="post", lw=2, color=COLORS[lang],
                        label=f"{LABELS[lang]}  (median {np.median(v):.2f} ms)")
        ax.set_xlabel("exec → exit, ms" if test == "cli" else "exec → first 200 from /health, ms")
        ax.set_ylabel("fraction of starts")
        ax.set_title(f"{wl}: startup time distribution (ECDF)")
        ax.legend(loc="lower right")
        _save(fig, out, f"startup_{wl.split('.', 1)[1]}")


def binsize_charts(proc: Path, out: Path) -> None:
    p = _read(proc, "binsize_pairs")
    if p.empty:
        return
    for pair, g in p.groupby("pair", sort=False):
        paired_bars(g, g["program"], g["go_bytes"] / 2**20, g["rust_bytes"] / 2**20,
                    f"Binary size: {pair} (Go {g['go_variant'].iloc[0]} vs Rust {g['rust_variant'].iloc[0]})",
                    "MiB on disk", out, "binsize_" + pair.replace(" ", "_").replace(",", ""))


def compile_charts(proc: Path, out: Path) -> None:
    c = _read(proc, "compile_comparison")
    if c.empty:
        return
    c = c[c["build_track"] != "check"]
    labels = c["workload"].str.split(".", n=1).str[1] + " · " + c["scenario"]
    paired_bars(c, labels, c["go_time_median"], c["rust_time_median"], "Build time (median)", "seconds (log)",
                out, "compile_time", log_x=True)
    paired_bars(c, labels, c["go_peak_rss_kb_median"] / 1024, c["rust_peak_rss_kb_median"] / 1024,
                "Peak compiler process RSS (median)", "MiB", out, "compile_peak_rss")


def main(args=None) -> int:
    """Called by `bench charts` (namespace with mode/run_id) or standalone."""
    if args is None or isinstance(args, list):
        ap = argparse.ArgumentParser()
        ap.add_argument("processed", nargs="?", help="results/processed/<dir> (default: <mode>-latest)")
        ap.add_argument("--mode", default="native")
        ap.add_argument("--out")
        a = ap.parse_args(args)
    else:
        a = argparse.Namespace(processed=None, out=None, mode=args.mode)
        if getattr(args, "run_id", None):
            a.processed = str(ROOT / "results" / "processed" / args.run_id[0])
    proc = Path(a.processed) if a.processed else ROOT / "results" / "processed" / f"{a.mode}-latest"
    if not (proc / "summary.json").exists():
        log(f"{proc}: no processed results (run `make process`)", level="error")
        return 1
    out = Path(a.out) if a.out else ROOT / "charts" / proc.name
    cmp = _read(proc, "comparison")
    if not cmp.empty:
        for cat in cmp["category"].dropna().unique():
            forest(cmp, cat, out)
            memory(cmp, cat, out)
    http_charts(proc, out)
    startup_charts(proc, out)
    binsize_charts(proc, out)
    compile_charts(proc, out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
