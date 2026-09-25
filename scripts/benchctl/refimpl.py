"""Reference implementations of the cross-language primitives.

These mirror go/internal/common and rust/common exactly. They generate
spec/golden.json (the values all three test suites check) and drive the
vectorised dataset generator, so every dataset byte can be traced back to the
same SplitMix64 stream the Go and Rust programs use in-process.
"""

from __future__ import annotations

import numpy as np

MASK64 = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C15
MIX_C1 = 0xBF58476D1CE4E5B9
MIX_C2 = 0x94D049BB133111EB
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3

HIST_SUB_BITS = 6
HIST_SUB = 1 << HIST_SUB_BITS


def mix64(z: int) -> int:
    z &= MASK64
    z = ((z ^ (z >> 30)) * MIX_C1) & MASK64
    z = ((z ^ (z >> 27)) * MIX_C2) & MASK64
    return z ^ (z >> 31)


class SplitMix64:
    """Scalar SplitMix64, identical to the Go and Rust versions."""

    def __init__(self, seed: int) -> None:
        self.state = seed & MASK64

    def next(self) -> int:
        self.state = (self.state + GOLDEN) & MASK64
        return mix64(self.state)

    def below(self, n: int) -> int:
        return (self.next() * n) >> 64

    def float64(self) -> float:
        return (self.next() >> 11) * (1.0 / (1 << 53))


def fnv1a64(data: bytes, h: int = FNV_OFFSET) -> int:
    for c in data:
        h = ((h ^ c) * FNV_PRIME) & MASK64
    return h


class Digest:
    def __init__(self) -> None:
        self.h = FNV_OFFSET

    def add(self, x: int) -> None:
        self.h = mix64(self.h ^ (x & MASK64))

    def sum(self) -> int:
        return self.h


class Unordered:
    def __init__(self) -> None:
        self.total = 0
        self.n = 0

    def add(self, x: int) -> None:
        self.total = (self.total + mix64(x)) & MASK64
        self.n += 1

    def sum(self) -> int:
        return mix64(self.total ^ mix64(self.n))


def hist_bucket(v: int) -> int:
    if v < HIST_SUB:
        return v
    e = v.bit_length() - 1
    m = (v >> (e - HIST_SUB_BITS)) & (HIST_SUB - 1)
    return (e - HIST_SUB_BITS + 1) * HIST_SUB + m


def hist_bucket_bounds(i: int) -> tuple[int, int]:
    """Inclusive lower bound and exclusive upper bound of bucket i."""
    if i < HIST_SUB:
        return i, i + 1
    e = i // HIST_SUB + HIST_SUB_BITS - 1
    m = i % HIST_SUB
    width = 1 << (e - HIST_SUB_BITS)
    low = (HIST_SUB + m) << (e - HIST_SUB_BITS)
    return low, low + width


def hexu64(x: int) -> str:
    return f"{x & MASK64:016x}"


# --------------------------------------------------------------------------
# Vectorised SplitMix64 (numpy). Output k (0-based) of a generator seeded with
# `seed` is mix64(seed + (k + 1) * GOLDEN): the stream is counter based, so any
# chunk can be produced independently and still match the sequential version.
# --------------------------------------------------------------------------

_U64 = np.uint64


def mix64_np(z: np.ndarray) -> np.ndarray:
    z = (z ^ (z >> _U64(30))) * _U64(MIX_C1)
    z = (z ^ (z >> _U64(27))) * _U64(MIX_C2)
    return z ^ (z >> _U64(31))


def splitmix64_np(seed: int, start: int, count: int) -> np.ndarray:
    """Outputs start .. start+count-1 of SplitMix64(seed) as uint64."""
    with np.errstate(over="ignore"):
        k = np.arange(start + 1, start + count + 1, dtype=np.uint64)
        z = _U64(seed & MASK64) + k * _U64(GOLDEN)
        return mix64_np(z)


def below_np(z: np.ndarray, n: int) -> np.ndarray:
    """Lemire reduction floor(z * n / 2**64) for n < 2**32, exactly."""
    if not 0 < n < (1 << 32):
        raise ValueError("below_np requires 0 < n < 2**32")
    with np.errstate(over="ignore"):
        lo = z & _U64(0xFFFFFFFF)
        hi = z >> _U64(32)
        t = hi * _U64(n) + ((lo * _U64(n)) >> _U64(32))
        return t >> _U64(32)
