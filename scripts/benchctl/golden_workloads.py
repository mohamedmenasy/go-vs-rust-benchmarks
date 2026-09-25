"""Golden answers for individual benchmark workloads, computed independently
in Python (a third implementation next to Go and Rust). Each category adds a
section; the Go and Rust unit tests check their workloads against it."""

from __future__ import annotations

import hashlib
import math
import struct

import numpy as np

from . import refimpl as R
from .util import ROOT

FIXTURES = ROOT / "spec" / "fixtures"


def f64bits(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def random_bytes(seed: int, n: int) -> bytes:
    """SplitMix64 words as little-endian bytes, truncated to n (common.RandomBytes)."""
    words = (n + 7) // 8
    return R.splitmix64_np(seed, 0, words).astype("<u8").tobytes()[:n]


# ----------------------------------------------------------------------------- CPU

def fib(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def sieve_digest(n: int) -> tuple[int, int, int]:
    comp = np.zeros(n + 1, dtype=bool)
    comp[:2] = True
    for i in range(2, math.isqrt(n) + 1):
        if not comp[i]:
            comp[i * i :: i] = True
    primes = np.nonzero(~comp)[0]
    count, total = int(primes.size), int(primes.sum())
    d = R.Digest()
    d.add(count)
    d.add(total)
    return count, total, d.sum()


def sha256_first8(data: bytes) -> int:
    return int.from_bytes(hashlib.sha256(data).digest()[:8], "big")


def sort_u64(n: int, seed: int) -> tuple[int, int]:
    g = R.SplitMix64(seed)
    a = sorted(g.next() for _ in range(n))
    run = a[0] ^ a[n // 2] ^ a[n - 1]
    d = R.Digest()
    for x in a:
        d.add(x)
    return run, d.sum()


def sort_stable(n: int, seed: int) -> tuple[int, int]:
    g = R.SplitMix64(seed)
    kmax = max(n // 4, 1)
    recs = [(g.below(kmax), i) for i in range(n)]
    recs.sort(key=lambda r: r[0])  # Python's sort is stable
    run = recs[0][0] ^ recs[n // 2][1] ^ recs[n - 1][0]
    d = R.Digest()
    for k, v in recs:
        d.add(k)
        d.add(v)
    return run, d.sum()


def matmul(n: int, seed: int) -> tuple[int, int]:
    g = R.SplitMix64(seed)
    a = [g.float64() for _ in range(n * n)]
    b = [g.float64() for _ in range(n * n)]
    c = [0.0] * (n * n)
    for i in range(n):
        for k in range(n):
            aik = a[i * n + k]
            for j in range(n):
                c[i * n + j] += aik * b[k * n + j]
    run = f64bits(c[0]) ^ f64bits(c[n * n - 1])
    d = R.Digest()
    for x in c:
        d.add(f64bits(x))
    return run, d.sum()


def _nbody_initial() -> list[list[float]]:
    pi = math.pi
    solar_mass = 4.0 * pi * pi
    dpy = 365.24
    bodies = [
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, solar_mass],
        [4.84143144246472090e+00, -1.16032004402742839e+00, -1.03622044471123109e-01,
         1.66007664274403694e-03 * dpy, 7.69901118419740425e-03 * dpy, -6.90460016972063023e-05 * dpy,
         9.54791938424326609e-04 * solar_mass],
        [8.34336671824457987e+00, 4.12479856412430479e+00, -4.03523417114321381e-01,
         -2.76742510726862411e-03 * dpy, 4.99852801234917238e-03 * dpy, 2.30417297573763929e-05 * dpy,
         2.85885980666130812e-04 * solar_mass],
        [1.28943695621391310e+01, -1.51111514016986312e+01, -2.23307578892655734e-01,
         2.96460137564761618e-03 * dpy, 2.37847173959480950e-03 * dpy, -2.96589568540237556e-05 * dpy,
         4.36624404335156298e-05 * solar_mass],
        [1.53796971148509165e+01, -2.59193146099879641e+01, 1.79258772950371181e-01,
         2.68067772490389322e-03 * dpy, 1.62824170038242295e-03 * dpy, -9.51592254519715870e-05 * dpy,
         5.15138902046611451e-05 * solar_mass],
    ]
    px = py = pz = 0.0
    for b in bodies:
        px += b[3] * b[6]
        py += b[4] * b[6]
        pz += b[5] * b[6]
    bodies[0][3] = -px / solar_mass
    bodies[0][4] = -py / solar_mass
    bodies[0][5] = -pz / solar_mass
    return bodies


def _nbody_energy(bs) -> float:
    e = 0.0
    for i, b in enumerate(bs):
        e += 0.5 * b[6] * (b[3] * b[3] + b[4] * b[4] + b[5] * b[5])
        for j in range(i + 1, len(bs)):
            b2 = bs[j]
            dx = b[0] - b2[0]
            dy = b[1] - b2[1]
            dz = b[2] - b2[2]
            e -= (b[6] * b2[6]) / math.sqrt(dx * dx + dy * dy + dz * dz)
    return e


def nbody(steps: int) -> tuple[float, float, int]:
    bs = _nbody_initial()
    e0 = _nbody_energy(bs)
    dt = 0.01
    for _ in range(steps):
        for i in range(5):
            bi = bs[i]
            for j in range(i + 1, 5):
                bj = bs[j]
                dx = bi[0] - bj[0]
                dy = bi[1] - bj[1]
                dz = bi[2] - bj[2]
                dsq = dx * dx + dy * dy + dz * dz
                dist = math.sqrt(dsq)
                mag = dt / (dsq * dist)
                bi[3] -= dx * bj[6] * mag
                bi[4] -= dy * bj[6] * mag
                bi[5] -= dz * bj[6] * mag
                bj[3] += dx * bi[6] * mag
                bj[4] += dy * bi[6] * mag
                bj[5] += dz * bi[6] * mag
        for b in bs:
            b[0] += dt * b[3]
            b[1] += dt * b[4]
            b[2] += dt * b[5]
    e1 = _nbody_energy(bs)
    d = R.Digest()
    d.add(f64bits(e0))
    d.add(f64bits(e1))
    return e0, e1, d.sum()


def mandelbrot(w: int, max_iter: int = 50) -> tuple[int, int]:
    h = w
    row_bytes = (w + 7) // 8
    bitmap = bytearray(row_bytes * h)
    count = 0
    for y in range(h):
        ci = 2.0 * y / h - 1.0
        for xb in range(row_bytes):
            bits = 0
            for bit in range(8):
                x = xb * 8 + bit
                inside = False
                if x < w:
                    cr = 2.0 * x / w - 1.5
                    zr = zi = tr = ti = 0.0
                    i = 0
                    while i < max_iter and tr + ti <= 4.0:
                        zi = 2.0 * zr * zi + ci
                        zr = tr - ti + cr
                        tr = zr * zr
                        ti = zi * zi
                        i += 1
                    inside = tr + ti <= 4.0
                bits = (bits << 1) & 0xFF
                if inside:
                    bits |= 1
                    count += 1
            bitmap[y * row_bytes + xb] = bits
    return count, R.fnv1a64(bytes(bitmap))


def csv_aggregate(text: str) -> tuple[int, int]:
    """Per-endpoint aggregation of the requests CSV (header skipped)."""
    aggs: dict[str, list] = {}
    rows = 0
    for line in text.split("\n")[1:]:
        if not line:
            continue
        ts, user, ep, status, lat, size = line.split(",")
        int(ts), int(user)
        status_i, lat_f, size_i = int(status), float(lat), int(size)
        a = aggs.get(ep)
        if a is None:
            a = aggs[ep] = [0, 0.0, 0.0, 0, 0, 0]  # count, lat_sum, lat_max, bytes, n4xx, n5xx
        a[0] += 1
        a[1] += lat_f
        if lat_f > a[2]:
            a[2] = lat_f
        a[3] += size_i
        if 400 <= status_i < 500:
            a[4] += 1
        elif status_i >= 500:
            a[5] += 1
        rows += 1
    d = R.Digest()
    for ep in sorted(aggs):  # byte-wise order == code-point order for ASCII
        a = aggs[ep]
        d.add(R.fnv1a64(ep.encode()))
        d.add(len(ep.encode()))
        d.add(a[0])
        d.add(f64bits(a[1]))
        d.add(f64bits(a[2]))
        d.add(a[3])
        d.add(a[4])
        d.add(a[5])
    d.add(rows)
    return rows, d.sum()


def ensure_fixtures() -> None:
    from . import datasets

    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / "requests-16KiB.csv"
    data = b"".join(datasets._gen_csv_requests(16 * 1024))
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def cpu_section() -> dict:
    ensure_fixtures()
    h = R.hexu64
    rb = random_bytes(4, 1000)
    sort_run, sort_check = sort_u64(1000, 1)
    st_run, st_check = sort_stable(1000, 2)
    mm_run, mm_check = matmul(16, 3)
    e0, e1, nb = nbody(1000)
    mcount, mfnv = mandelbrot(64)
    rows, csvd = csv_aggregate((FIXTURES / "requests-16KiB.csv").read_text())
    return {
        "random_bytes": {"seed": 4, "n": 1000, "fnv1a64": h(R.fnv1a64(rb)), "first16_hex": rb[:16].hex()},
        "fib": [{"n": n, "value": fib(n)} for n in (0, 1, 2, 10, 25, 30)],
        "sieve": [
            {"n": n, "count": c, "sum": s, "digest": h(d)}
            for n in (10, 1000, 1_000_000)
            for c, s, d in [sieve_digest(n)]
        ],
        "sha256": [
            {"input": s, "hex": hashlib.sha256(s.encode()).hexdigest(), "first8": h(sha256_first8(s.encode()))}
            for s in ("", "abc", "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
                      "a" * 55, "a" * 56, "a" * 63, "a" * 64, "a" * 65)
        ] + [{"random_seed": 4, "n": 1000, "hex": hashlib.sha256(rb).hexdigest(), "first8": h(sha256_first8(rb))}],
        "sort_u64": {"n": 1000, "seed": 1, "run": h(sort_run), "check": h(sort_check)},
        "sort_stable": {"n": 1000, "seed": 2, "run": h(st_run), "check": h(st_check)},
        "matmul": {"n": 16, "seed": 3, "run": h(mm_run), "check": h(mm_check)},
        "nbody": {"steps": 1000, "e0": e0, "e1": e1, "e0_bits": h(f64bits(e0)), "e1_bits": h(f64bits(e1)), "digest": h(nb)},
        "mandelbrot": {"w": 64, "count": mcount, "fnv1a64": h(mfnv)},
        "csvparse": {"fixture": "spec/fixtures/requests-16KiB.csv", "rows": rows, "digest": h(csvd)},
    }


def sections() -> dict:
    return {"cpu": cpu_section()}
