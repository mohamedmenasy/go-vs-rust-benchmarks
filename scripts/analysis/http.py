"""Process raw HTTP records into tables.

Tables:
  http_runs        one row per measured window (throughput + latency tests)
  http_comparison  Go vs Rust per (workload, test, level): medians over rounds,
                   ratio with bootstrap CI (higher is better for rps; lower for
                   latency), efficiency (requests per CPU-second), memory
  http_sustained   one row per sustained-load window (time series)
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path

import pandas as pd

from benchctl import stats
from benchctl.util import read_json

PCTS = ("50", "75", "90", "95", "99", "99.9", "99.99")


def _row(rec: dict) -> dict:
    m = rec.get("metrics") or {}
    lat = (m.get("latency_us") or {})
    pct = lat.get("percentiles") or {}
    row = {
        "run_id": rec.get("run_id"),
        "workload": rec.get("workload"),
        "tier": rec.get("tier"),
        "test": rec.get("test"),
        "level": rec.get("size"),
        "connections": rec.get("connections"),
        "rate_frac": rec.get("rate_frac"),
        "target_rps": rec.get("target_rps"),
        "lang": rec.get("lang"),
        "impl": rec.get("impl"),
        "round": rec.get("round"),
        "ok": bool(rec.get("ok")),
        "flags": ";".join(m.get("flags", [])) if m else "failed",
        "error": rec.get("error"),
        "rps": m.get("rps"),
        "requests": m.get("requests"),
        "error_count": m.get("error_count"),
        "error_rate": m.get("error_rate"),
        "lat_mean_us": lat.get("mean"),
        "lat_max_us": lat.get("max"),
        "server_cpu_util": m.get("server_cpu_util"),
        "requests_per_cpu_second": m.get("requests_per_cpu_second"),
        "server_rss_avg_kb": m.get("server_rss_avg_kb"),
        "server_rss_peak_kb": m.get("server_rss_peak_kb"),
        "server_hwm_kb": rec.get("server_hwm_kb"),
        "server_threads_max": m.get("server_threads_max"),
        "loadgen_cpu_util": m.get("loadgen_cpu_util"),
        "steal_server": m.get("steal_frac_server"),
        "server_ready_ms": rec.get("server_ready_ms"),
    }
    for p in PCTS:
        row[f"lat_p{p}_us"] = pct.get(p)
    return row


def _med(s: pd.Series) -> float:
    s = s.dropna()
    return float(s.median()) if len(s) else math.nan


def _compare(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (wl, test, level), g in df.groupby(["workload", "test", "level"], sort=False):
        good = g[g["ok"] & ~g["flags"].fillna("").str.contains("loadgen_saturated|steal|failed")]
        row = {"workload": wl, "tier": g["tier"].iloc[0], "test": test, "level": level,
               "connections": g["connections"].iloc[0], "rate_frac": g["rate_frac"].iloc[0],
               "target_rps": g["target_rps"].iloc[0], "runs": len(g), "excluded_runs": len(g) - len(good),
               "loadgen_saturated_runs": int(g["flags"].fillna("").str.contains("loadgen_saturated").sum())}
        per = {lang: good[good["lang"] == lang] for lang in ("go", "rust")}
        for lang, d in per.items():
            row[f"{lang}_n"] = len(d)
            for col in ("rps", "lat_p50_us", "lat_p90_us", "lat_p99_us", "lat_p99.9_us", "lat_max_us", "lat_mean_us",
                        "server_cpu_util", "requests_per_cpu_second", "server_rss_avg_kb", "server_rss_peak_kb",
                        "server_threads_max", "error_rate", "loadgen_cpu_util"):
                row[f"{lang}_{col}"] = _med(d[col]) if col in d else math.nan
        a, b = per["go"], per["rust"]
        if test == "throughput":
            c = stats.compare(a["rps"].dropna().to_numpy(), b["rps"].dropna().to_numpy(), lower_is_better=False)
            metric = "rps"
        else:
            c = stats.compare(a["lat_p99_us"].dropna().to_numpy(), b["lat_p99_us"].dropna().to_numpy(),
                              lower_is_better=True)
            metric = "p99 latency"
        row["compared_metric"] = metric
        row["ratio_rust_over_go"] = c.ratio
        row["ratio_ci_low"] = c.ci_low
        row["ratio_ci_high"] = c.ci_high
        row["p_value"] = c.p_value
        row["verdict"] = {"a_better": "go_better", "b_better": "rust_better"}.get(c.verdict, c.verdict)
        row["valid"] = bool(len(a) and len(b))
        rows.append(row)
    return pd.DataFrame(rows)


def process(run_dir: Path) -> dict[str, pd.DataFrame]:
    base = run_dir / "http"
    rows, sustained = [], []
    for f in sorted(base.rglob("*.json")):
        if f.name == "capacity.json":
            continue
        rec = read_json(f)
        if rec.get("test") == "sustained":
            for w in rec.get("windows", []):
                lat = (w.get("latency_us") or {}).get("percentiles") or {}
                sustained.append({
                    "run_id": rec.get("run_id"), "workload": rec.get("workload"), "level": rec.get("size"),
                    "lang": rec.get("lang"), "window": w.get("window"), "t_s": w.get("t_s"), "rps": w.get("rps"),
                    "lat_p50_us": lat.get("50"), "lat_p99_us": lat.get("99"), "lat_max_us": (w.get("latency_us") or {}).get("max"),
                    "server_cpu_util": w.get("server_cpu_util"), "server_rss_avg_kb": w.get("server_rss_avg_kb"),
                    "error_count": w.get("error_count"), "flags": ";".join(w.get("flags", [])),
                    "rss_slope_mib_per_min": rec.get("rss_slope_mib_per_min"), "server_hwm_kb": rec.get("server_hwm_kb"),
                })
            continue
        rows.append(_row(rec))
    runs = pd.DataFrame(rows)
    out = {"http_runs": runs, "http_sustained": pd.DataFrame(sustained)}
    if not runs.empty:
        out["http_comparison"] = _compare(runs)
    return out


def sustained_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per (workload, level, lang): median/min rps over windows, worst p99, RSS slope."""
    if df.empty:
        return df
    g = df.groupby(["workload", "level", "lang"])
    return pd.DataFrame({
        "windows": g["window"].count(),
        "rps_median": g["rps"].median(),
        "rps_min": g["rps"].min(),
        "rps_cv": g["rps"].std() / g["rps"].mean(),
        "p99_median_us": g["lat_p99_us"].median(),
        "p99_worst_us": g["lat_p99_us"].max(),
        "rss_slope_mib_per_min": g["rss_slope_mib_per_min"].first(),
        "server_hwm_kb": g["server_hwm_kb"].first(),
    }).reset_index()


__all__ = ["process", "sustained_summary", "statistics"]
