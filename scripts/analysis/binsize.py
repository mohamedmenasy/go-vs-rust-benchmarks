"""Process binary-size records into tables.

Tables:
  binsize_binaries  one row per (lang, variant, program)
  binsize_pairs     Go vs Rust per (pair, program): bytes, stripped bytes, ratio
  binsize_deps      dependency footprint per program
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from benchctl.util import read_json


def process(run_dir: Path) -> dict[str, pd.DataFrame]:
    d = read_json(run_dir / "binsize" / "binaries.json")
    bins = pd.DataFrame(d["binaries"])
    bins["dynamic_libs"] = bins["dynamic_libs"].map(lambda x: " ".join(x))
    by = {(r.lang, r.variant, r.program): r for r in bins.itertuples()}
    pairs = []
    for p in d.get("pairs", []):
        for prog in sorted(bins["program"].unique()):
            g, r = by.get(("go", p["go"], prog)), by.get(("rust", p["rust"], prog))
            if g is None or r is None:
                continue
            pairs.append({"pair": p["label"], "program": prog, "go_variant": p["go"], "rust_variant": p["rust"],
                          "go_bytes": g.bytes, "rust_bytes": r.bytes, "ratio_rust_over_go": r.bytes / g.bytes,
                          "go_stripped_bytes": g.stripped_bytes, "rust_stripped_bytes": r.stripped_bytes,
                          "stripped_ratio_rust_over_go": r.stripped_bytes / g.stripped_bytes,
                          "go_static": g.static, "rust_static": r.static})
    deps = []
    for prog, v in read_json(run_dir / "binsize" / "deps.json").items():
        deps.append({"program": prog, "go_packages_total": v["go"]["packages_total"],
                     "go_packages_std": v["go"]["packages_std"], "go_packages_nonstd": v["go"]["packages_nonstd"],
                     "go_modules": v["go"]["modules_count"], "rust_crates": v["rust"]["crates_count"],
                     "go_module_list": " ".join(v["go"]["modules"]), "rust_crate_list": " ".join(v["rust"]["crates"])})
    return {"binsize_binaries": bins, "binsize_pairs": pd.DataFrame(pairs), "binsize_deps": pd.DataFrame(deps)}


__all__ = ["process"]
