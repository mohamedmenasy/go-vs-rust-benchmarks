"""Process raw startup records into tables.

Tables:
  startup_samples     one row per measured start (ms)
  startup_comparison  Go vs Rust per (workload, metric): descriptive stats per
                      language and the median ratio with bootstrap CI.

Unit of comparison: for `cli` each hyperfine invocation (one round) is one
independent group, so the per-round medians are compared; for `ttfr` every
start is a fresh process, so individual starts are compared.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from benchctl import stats
from benchctl.util import read_json

METRICS = {"cli": ["exec_to_exit_ms"], "ttfr": ["health_ms", "first_request_ms"]}


def process(run_dir: Path) -> dict[str, pd.DataFrame]:
    rows = []
    for f in sorted((run_dir / "startup").rglob("*.json")):
        if f.name == "ttfr.json":
            continue
        rec = read_json(f)
        common = {"run_id": rec.get("run_id"), "workload": rec.get("workload"), "variant_of": rec.get("variant_of"),
                  "track": rec.get("track"), "test": rec.get("test"), "lang": rec.get("lang"),
                  "flavor": rec.get("flavor"), "rec_ok": bool(rec.get("ok"))}
        if rec.get("test") == "cli":
            for i, t in enumerate(rec.get("times_s") or []):
                rows.append({**common, "round": rec.get("round"), "i": i, "exec_to_exit_ms": t * 1e3})
        else:
            for r in rec.get("runs", []):
                rows.append({**common, "round": r.get("i"), "i": r.get("i"), "ok": r.get("ok"),
                             "health_ms": r.get("health_ms"), "first_request_ms": r.get("first_request_ms"),
                             "hwm_kb": r.get("hwm_kb"), "threads": r.get("threads")})
    samples = pd.DataFrame(rows)
    out = {"startup_samples": samples}
    if not samples.empty:
        out["startup_comparison"] = _compare(samples)
    return out


def _compare(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (wl, test), g in df.groupby(["workload", "test"], sort=False):
        if "ok" in g and test == "ttfr":
            g = g[g["ok"].fillna(False).astype(bool)]
        for metric in METRICS[test]:
            row = {"workload": wl, "test": test, "metric": metric, "variant_of": g["variant_of"].iloc[0],
                   "track": g["track"].iloc[0]}
            groups = {}
            for lang in ("go", "rust"):
                d = g[g["lang"] == lang]
                desc = stats.describe(d[metric].dropna())
                for k, v in desc.items():
                    row[f"{lang}_{k}"] = v
                if test == "cli":
                    groups[lang] = d.groupby("round")[metric].median().to_numpy()
                else:
                    groups[lang] = d[metric].dropna().to_numpy()
                if test == "ttfr":
                    row[f"{lang}_hwm_kb_median"] = float(d["hwm_kb"].median()) if len(d) else math.nan
                    row[f"{lang}_threads_median"] = float(d["threads"].median()) if len(d) else math.nan
            c = stats.compare(groups["go"], groups["rust"], lower_is_better=True)
            row.update({"unit": "round medians" if test == "cli" else "starts", "ratio_rust_over_go": c.ratio,
                        "ratio_ci_low": c.ci_low, "ratio_ci_high": c.ci_high, "p_value": c.p_value,
                        "verdict": {"a_better": "go_better", "b_better": "rust_better"}.get(c.verdict, c.verdict)})
            rows.append(row)
    return pd.DataFrame(rows)


__all__ = ["process"]
