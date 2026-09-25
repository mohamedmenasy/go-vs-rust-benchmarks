"""The statistics must behave correctly on synthetic data with a known answer."""

import unittest

import numpy as np

from benchctl import refimpl, stats


class CompareTests(unittest.TestCase):
    def test_identical_distributions_are_not_different(self):
        rng = np.random.default_rng(1)
        a = rng.normal(100.0, 2.0, 10)
        b = rng.normal(100.0, 2.0, 10)
        c = stats.compare(a, b)
        self.assertFalse(c.significant)
        self.assertEqual(c.verdict, "no_measurable_difference")

    def test_false_positive_rate_is_bounded(self):
        # Identical distributions with realistic noise (CV 5%): the combined
        # rule (CI + p-value + 2% band) must call a difference rarely.
        false_calls = 0
        trials = 200
        for seed in range(trials):
            rng = np.random.default_rng(1000 + seed)
            a = rng.normal(100.0, 5.0, 10)
            b = rng.normal(100.0, 5.0, 10)
            false_calls += stats.compare(a, b).significant
        self.assertLessEqual(false_calls / trials, 0.05)

    def test_ten_percent_shift_is_detected_with_correct_ci(self):
        rng = np.random.default_rng(2)
        a = rng.normal(100.0, 1.0, 10)
        b = rng.normal(110.0, 1.0, 10)
        c = stats.compare(a, b, lower_is_better=True)
        self.assertTrue(c.significant)
        self.assertEqual(c.verdict, "a_better")  # b (Rust) is 10% slower
        self.assertLess(c.ci_low, 1.10)
        self.assertGreater(c.ci_high, 1.08)
        self.assertLess(c.p_value, 0.01)

    def test_higher_is_better_inverts_verdict(self):
        a = np.linspace(100, 101, 10)
        b = np.linspace(120, 121, 10)
        self.assertEqual(stats.compare(a, b, lower_is_better=False).verdict, "b_better")

    def test_within_equivalence_band_is_not_called(self):
        a = np.linspace(100.0, 100.1, 10)
        b = a * 1.01  # 1% apart, very low noise: CI excludes 1 but within +-2% band
        c = stats.compare(a, b)
        self.assertFalse(c.significant)

    def test_too_few_rounds(self):
        c = stats.compare([1.0, 1.1, 1.2], [2.0, 2.1, 2.2])
        self.assertEqual(c.verdict, "insufficient_rounds")
        self.assertFalse(c.significant)

    def test_describe(self):
        d = stats.describe([1, 2, 3, 4, 100])
        self.assertEqual(d["median"], 3)
        self.assertEqual(d["min"], 1)
        self.assertEqual(d["max"], 100)
        self.assertEqual(d["n"], 5)


class HistogramTests(unittest.TestCase):
    def test_percentiles_from_loglin_histogram(self):
        values = list(range(1, 10001))  # 1..10000 ns
        buckets = {}
        for v in values:
            i = refimpl.hist_bucket(v)
            buckets[i] = buckets.get(i, 0) + 1
        hist = {"buckets": [[i, c] for i, c in buckets.items()], "min_ns": 1, "max_ns": 10000, "sum_ns": sum(values)}
        p = stats.hist_percentiles(hist)
        self.assertAlmostEqual(p["p50"], 5000, delta=5000 / 64)
        self.assertAlmostEqual(p["p99"], 9900, delta=9900 / 64)
        self.assertEqual(p["count"], 10000)

    def test_bucket_bounds_contain_value(self):
        rng = np.random.default_rng(3)
        for v in rng.integers(0, 2**62, 5000).tolist() + [0, 1, 63, 64, 127, 128, 2**63]:
            lo, hi = refimpl.hist_bucket_bounds(refimpl.hist_bucket(v))
            self.assertTrue(lo <= v < hi, (v, lo, hi))


class GoldenTests(unittest.TestCase):
    def test_golden_file_is_current(self):
        from benchctl import golden
        from benchctl.util import ROOT

        self.assertTrue(golden.check(ROOT), "spec/golden.json is stale: run `scripts/bench golden`")

    def test_vectorised_splitmix_matches_scalar(self):
        g = refimpl.SplitMix64(12345)
        scalar = [g.next() for _ in range(100)]
        vec = refimpl.splitmix64_np(12345, 0, 100).tolist()
        self.assertEqual(scalar, vec)
        g = refimpl.SplitMix64(99)
        below = [g.below(1_000_003) for _ in range(100)]
        self.assertEqual(below, refimpl.below_np(refimpl.splitmix64_np(99, 0, 100), 1_000_003).tolist())


if __name__ == "__main__":
    unittest.main()
