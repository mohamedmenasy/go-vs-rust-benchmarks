"""Statistics used for every comparison (METHODOLOGY.md, "Statistics").

* Descriptive statistics over all samples: mean, median, min, max, standard
  deviation, coefficient of variation, p50/p95/p99.
* The unit of replication is the process run (a fresh process per round), so
  the comparison statistic is the ratio of medians of per-process medians,
  with a seeded percentile bootstrap 95% confidence interval.
* A two-sided Mann-Whitney U test on the per-process medians is reported
  alongside.
* Verdict: "no measurable difference" when the CI contains 1.0 or the
  point estimate is within the practical-equivalence band (+-2%).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

EQUIVALENCE_BAND = 0.02
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20240917


def describe(values) -> dict:
    x = np.asarray(values, dtype=float)
    if x.size == 0:
        return {"n": 0}
    mean = float(x.mean())
    std = float(x.std(ddof=1)) if x.size > 1 else 0.0
    return {
        "n": int(x.size),
        "mean": mean,
        "median": float(np.median(x)),
        "min": float(x.min()),
        "max": float(x.max()),
        "std": std,
        "cv": std / mean if mean else math.nan,
        "p50": float(np.percentile(x, 50)),
        "p95": float(np.percentile(x, 95)),
        "p99": float(np.percentile(x, 99)),
    }


@dataclass
class Comparison:
    ratio: float  # b / a (e.g. rust / go) of the chosen statistic
    ci_low: float
    ci_high: float
    p_value: float
    n_a: int
    n_b: int
    verdict: str  # "a_better" | "b_better" | "no_measurable_difference" | "insufficient_data"
    significant: bool

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def bootstrap_ratio(a, b, *, stat=np.median, resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED):
    """Percentile-bootstrap CI for stat(b) / stat(a), resampling each group independently."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    rng = np.random.default_rng(seed)
    ia = rng.integers(0, a.size, size=(resamples, a.size))
    ib = rng.integers(0, b.size, size=(resamples, b.size))
    sa = stat(a[ia], axis=1)
    sb = stat(b[ib], axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = sb / sa
    ratios = ratios[np.isfinite(ratios)]
    point = float(stat(b) / stat(a)) if stat(a) != 0 else math.nan
    if ratios.size == 0:
        return point, math.nan, math.nan
    lo, hi = np.percentile(ratios, [2.5, 97.5])
    return point, float(lo), float(hi)


def mann_whitney(a, b) -> float:
    try:
        from scipy.stats import mannwhitneyu
    except ImportError:  # pragma: no cover
        return math.nan
    if len(a) < 2 or len(b) < 2:
        return math.nan
    if np.allclose(a, a[0]) and np.allclose(b, b[0]) and a[0] == b[0]:
        return 1.0
    return float(mannwhitneyu(a, b, alternative="two-sided").pvalue)


MIN_ROUNDS = 5
ALPHA = 0.05


def compare(a, b, *, lower_is_better: bool = True, band: float = EQUIVALENCE_BAND,
            min_rounds: int = MIN_ROUNDS) -> Comparison:
    """Compare per-process statistics of group a (Go) and group b (Rust).

    A difference is called only when all of these hold: at least `min_rounds`
    independent process runs per side, the bootstrap 95% CI of the ratio
    excludes 1.0, the Mann-Whitney p-value is below ALPHA, and the point
    estimate lies outside the +-band practical-equivalence zone.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 2 or b.size < 2:
        ratio = float(np.median(b) / np.median(a)) if a.size and b.size and np.median(a) else math.nan
        return Comparison(ratio, math.nan, math.nan, math.nan, int(a.size), int(b.size), "insufficient_data", False)
    ratio, lo, hi = bootstrap_ratio(a, b)
    p = mann_whitney(a, b)
    ci_excludes_one = not (lo <= 1.0 <= hi)
    outside_band = abs(ratio - 1.0) > band
    p_ok = (p < ALPHA) if not math.isnan(p) else False
    significant = bool(ci_excludes_one and outside_band and p_ok)
    if a.size < min_rounds or b.size < min_rounds:
        return Comparison(ratio, lo, hi, p, int(a.size), int(b.size), "insufficient_rounds", False)
    if not significant:
        verdict = "no_measurable_difference"
    else:
        b_smaller = ratio < 1.0
        b_better = b_smaller if lower_is_better else not b_smaller
        verdict = "b_better" if b_better else "a_better"
    return Comparison(ratio, lo, hi, p, int(a.size), int(b.size), verdict, significant)


def pct_diff(a: float, b: float) -> float:
    """(b - a) / a in percent."""
    return (b - a) / a * 100.0 if a else math.nan


# ---- log-linear histogram (loglin6) decoding --------------------------------

def hist_percentiles(hist: dict, qs=(50, 90, 95, 99, 99.9)) -> dict:
    """Percentiles from a loglin6 histogram exported by either harness."""
    from .refimpl import hist_bucket_bounds

    buckets = sorted((int(i), int(c)) for i, c in hist.get("buckets", []))
    total = sum(c for _, c in buckets)
    out: dict = {"count": total}
    if not total:
        return out
    for q in qs:
        target = q / 100 * total
        acc = 0
        for i, c in buckets:
            acc += c
            if acc >= target:
                lo, hi = hist_bucket_bounds(i)
                out[f"p{q:g}"] = (lo + hi - 1) / 2
                break
    out["min"] = hist.get("min_ns")
    out["max"] = hist.get("max_ns")
    out["mean"] = hist.get("sum_ns", 0) / total
    return out


def merge_hists(hists: list[dict]) -> dict:
    acc: dict[int, int] = {}
    mins, maxs, sums = [], [], 0
    for h in hists:
        for i, c in h.get("buckets", []):
            acc[int(i)] = acc.get(int(i), 0) + int(c)
        if h.get("count"):
            mins.append(h["min_ns"])
            maxs.append(h["max_ns"])
            sums += h.get("sum_ns", 0)
    return {
        "scheme": "loglin6",
        "buckets": sorted([i, c] for i, c in acc.items()),
        "count": sum(acc.values()),
        "min_ns": min(mins) if mins else 0,
        "max_ns": max(maxs) if maxs else 0,
        "sum_ns": sums,
    }
