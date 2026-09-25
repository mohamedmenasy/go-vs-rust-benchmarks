"""Process compilation records into tables.

Tables:
  compile_samples     one row per timed build
  compile_comparison  Go vs Rust per (workload, scenario): descriptive stats
                      of build time, peak compiler RSS, CPU time, and the
                      median ratio with bootstrap CI over per-round medians.
                      Rust-only workloads (cargo check) get Rust stats only.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from benchctl import stats
from benchctl.util import read_json


def process(run_dir: Path) -> dict[str, pd.DataFrame]:
    rows = []
    for f in sorted((run_dir / "compile").rglob("*.json")):
        rec = read_json(f)
        ts = rec.get("times_s") or []
        rss = rec.get("peak_rss_kb") or []
        us, ss = rec.get("user_s") or [], rec.get("system_s") or []
        for i, t in enumerate(ts):
            rows.append({"run_id": rec.get("run_id"), "workload": rec.get("workload"), "target": rec.get("target"),
                         "build_track": rec.get("build_track"), "scenario": rec.get("scenario"),
                         "lang": rec.get("lang"), "round": rec.get("round"), "i": i, "ok": bool(rec.get("ok")),
                         "time_s": t, "peak_rss_kb": rss[i] if i < len(rss) else math.nan,
                         "cpu_s": (us[i] + ss[i]) if i < len(us) and i < len(ss) else math.nan})
    samples = pd.DataFrame(rows)
    out = {"compile_samples": samples}
    if not samples.empty:
        out["compile_comparison"] = _compare(samples[samples["ok"]])
    return out


def _compare(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (wl, scen), g in df.groupby(["workload", "scenario"], sort=False):
        row = {"workload": wl, "target": g["target"].iloc[0], "build_track": g["build_track"].iloc[0],
               "scenario": scen}
        groups = {}
        for lang in ("go", "rust"):
            d = g[g["lang"] == lang]
            for k, v in stats.describe(d["time_s"]).items():
                row[f"{lang}_time_{k}"] = v
            row[f"{lang}_peak_rss_kb_median"] = float(d["peak_rss_kb"].median()) if len(d) else math.nan
            row[f"{lang}_cpu_s_median"] = float(d["cpu_s"].median()) if len(d) else math.nan
            groups[lang] = d.groupby("round")["time_s"].median().to_numpy()
        if len(groups["go"]) and len(groups["rust"]):
            c = stats.compare(groups["go"], groups["rust"], lower_is_better=True)
            row.update({"ratio_rust_over_go": c.ratio, "ratio_ci_low": c.ci_low, "ratio_ci_high": c.ci_high,
                        "p_value": c.p_value,
                        "verdict": {"a_better": "go_better", "b_better": "rust_better"}.get(c.verdict, c.verdict)})
        else:
            row["verdict"] = "single_language"
        rows.append(row)
    return pd.DataFrame(rows)


__all__ = ["process"]
