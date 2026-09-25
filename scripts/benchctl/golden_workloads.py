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


# ----------------------------------------------------------------------------- memory

def _u64_sum(v: np.ndarray) -> int:
    return int(v.sum(dtype=np.uint64)) & R.MASK64


def mem_bytes(words: int, seed: int) -> int:
    return int(np.bitwise_xor.reduce(R.splitmix64_np(seed, 0, words)))


def mem_objects(n: int, seed: int) -> int:
    z = R.splitmix64_np(seed, 0, n)
    with np.errstate(over="ignore"):
        return _u64_sum(z ^ (z + np.uint64(7)))


def mem_trees(max_depth: int, min_depth: int = 4) -> int:
    nodes = lambda d: (1 << (d + 1)) - 1  # noqa: E731 - check() of a full tree of depth d
    d = R.Digest()
    d.add(nodes(max_depth + 1))
    for depth in range(min_depth, max_depth + 1, 2):
        iters = 1 << (max_depth - depth + min_depth)
        d.add(iters)
        d.add(depth)
        d.add(iters * nodes(depth))
    d.add(nodes(max_depth))
    return d.sum()


def mem_churn(n: int, k: int, seed: int) -> tuple[int, int]:
    g = R.SplitMix64(seed)
    acc = 0
    for _ in range(k):
        i = g.below(n)
        acc = (acc + (i ^ (i + 7))) & R.MASK64
    check = sum(i ^ (i + 7) for i in range(n)) & R.MASK64
    return acc, check


def memory_section() -> dict:
    h = R.hexu64
    churn_run, churn_check = mem_churn(1000, 1000, 7)
    return {
        "bytes": {"words": 1000, "seed": 5, "run": h(mem_bytes(1000, 5))},
        "objects": {"n": 1000, "seed": 6, "run": h(mem_objects(1000, 6))},
        "binarytrees": [{"depth": d, "run": h(mem_trees(d))} for d in (4, 6, 10)],
        "churn": {"n": 1000, "replace": 1000, "seed": 7, "run": h(churn_run), "check": h(churn_check)},
    }


# ----------------------------------------------------------------------------- JSON

def _dstr(d: R.Digest, s: str) -> None:
    b = s.encode()
    d.add(R.fnv1a64(b))
    d.add(len(b))


def _dbool(d: R.Digest, v: bool) -> None:
    d.add(1 if v else 0)


def _dopt(d: R.Digest, s) -> None:
    if s is None:
        d.add(0)
    else:
        d.add(1)
        _dstr(d, s)


def _dtags(d: R.Digest, tags) -> None:
    d.add(len(tags))
    for t in tags:
        _dstr(d, t)


def json_typed_digest_object(doc: dict) -> int:
    d = R.Digest()
    _dstr(d, doc["request_id"]); _dstr(d, doc["status"])
    d.add(doc["page"]); d.add(doc["per_page"]); d.add(doc["total"])
    _dstr(d, doc["generated_at"])
    d.add(len(doc["items"]))
    for it in doc["items"]:
        d.add(it["id"]); _dstr(d, it["sku"]); _dstr(d, it["name"]); _dstr(d, it["description"])
        d.add(f64bits(it["price"])); d.add(it["quantity"]); _dbool(d, it["in_stock"]); d.add(f64bits(it["rating"]))
        _dtags(d, it["tags"])
        dim = it["dimensions"]
        d.add(f64bits(dim["width"])); d.add(f64bits(dim["height"])); d.add(f64bits(dim["depth"]))
        _dopt(d, it["supplier"])
    m = doc["meta"]
    _dstr(d, m["region"]); _dbool(d, m["cache_hit"]); d.add(f64bits(m["latency_ms"])); _dtags(d, m["tags"])
    return d.sum()


def json_typed_digest_array(users: list) -> int:
    d = R.Digest()
    d.add(len(users))
    for u in users:
        d.add(u["id"]); _dstr(d, u["username"]); _dstr(d, u["email"]); d.add(u["age"])
        d.add(f64bits(u["score"])); _dbool(d, u["active"]); _dtags(d, u["roles"])
        a = u["address"]
        _dstr(d, a["street"]); _dstr(d, a["city"]); _dstr(d, a["zip"])
        d.add(f64bits(a["geo"]["lat"])); d.add(f64bits(a["geo"]["lng"]))
        _dstr(d, u["created_at"]); _dopt(d, u["bio"])
    return d.sum()


# Order-independent structural digest of a dynamically decoded document
# (Go map iteration order is random; serde_json::Value maps are sorted).
TAG_OBJ, TAG_ARR, TAG_KEY, TAG_STR, TAG_NUM, TAG_TRUE, TAG_FALSE, TAG_NULL = (k << 56 for k in range(1, 9))


def json_dynamic_digest(v) -> int:
    u = R.Unordered()

    def walk(x) -> None:
        if isinstance(x, dict):
            u.add(TAG_OBJ ^ len(x))
            for k, val in x.items():
                u.add(TAG_KEY ^ R.fnv1a64(k.encode()))
                walk(val)
        elif isinstance(x, list):
            u.add(TAG_ARR ^ len(x))
            for val in x:
                walk(val)
        elif isinstance(x, str):
            u.add(TAG_STR ^ R.fnv1a64(x.encode()))
        elif x is True:
            u.add(TAG_TRUE)
        elif x is False:
            u.add(TAG_FALSE)
        elif x is None:
            u.add(TAG_NULL)
        else:  # number: compared as float64 (Go decodes all numbers to float64)
            u.add(TAG_NUM ^ f64bits(float(x)))

    walk(v)
    return u.sum()


def json_section() -> dict:
    import json as _json

    from . import datasets_json

    FIXTURES.mkdir(parents=True, exist_ok=True)
    obj_path = FIXTURES / "json-object-2KiB.json"
    arr_path = FIXTURES / "json-array-20.json"
    obj_bytes = datasets_json.make_object(2048)
    arr_bytes = datasets_json.make_array(20)
    for path, data in ((obj_path, obj_bytes), (arr_path, arr_bytes)):
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    obj = _json.loads(obj_bytes)
    arr = _json.loads(arr_bytes)
    h = R.hexu64
    return {
        "object": {"fixture": "spec/fixtures/json-object-2KiB.json", "bytes": len(obj_bytes),
                   "fnv1a64": h(R.fnv1a64(obj_bytes)), "items": len(obj["items"]),
                   "typed_digest": h(json_typed_digest_object(obj)), "dynamic_digest": h(json_dynamic_digest(obj))},
        "array": {"fixture": "spec/fixtures/json-array-20.json", "bytes": len(arr_bytes),
                  "fnv1a64": h(R.fnv1a64(arr_bytes)), "users": len(arr),
                  "typed_digest": h(json_typed_digest_array(arr)), "dynamic_digest": h(json_dynamic_digest(arr))},
    }


# ----------------------------------------------------------------------------- concurrency

def spin(seed: int, rounds: int) -> int:
    x = seed
    for _ in range(rounds):
        x = R.mix64(x)
    return x


def conc_cpu_split(n: int, total: int) -> int:
    base, rem = divmod(total, n)
    return sum(spin(i, base + (1 if i < rem else 0)) for i in range(n)) & R.MASK64


def concurrency_section() -> dict:
    h = R.hexu64
    return {
        "spawn_join": [{"tasks": n, "run": h(sum(R.mix64(i) for i in range(n)) & R.MASK64)} for n in (1, 10, 1000)],
        "cpu_split": [{"tasks": n, "rounds": 1000, "run": h(conc_cpu_split(n, 1000))} for n in (1, 7, 100)],
        "pingpong": [{"msgs": m, "run": h(m * (m + 1) // 2)} for m in (1, 1000)],
        "prodcons": [{"msgs": m, "run": h(m * (m - 1) // 2)} for m in (10, 100_000)],
        "fanout": [{"jobs": j, "run": h(sum(spin(k, 100) for k in range(j)) & R.MASK64)} for j in (1, 1000)],
    }


# ----------------------------------------------------------------------------- file I/O

def page_sample_digest(data: bytes) -> int:
    acc = 0
    for p in range(0, len(data), 4096):
        acc = (acc + data[p] * (p // 4096 + 1)) & R.MASK64
    d = R.Digest()
    d.add(len(data))
    d.add(acc)
    return d.sum()


def lines_digest(text: str) -> int:
    lines = size_sum = n5xx = 0
    for line in text.split("\n")[1:]:
        if not line:
            continue
        f = line.split(",")
        status, size = int(f[3]), int(f[5])
        lines += 1
        size_sum += size
        n5xx += status >= 500
    d = R.Digest()
    d.add(lines)
    d.add(size_sum)
    d.add(n5xx)
    return d.sum()


def io_section() -> dict:
    h = R.hexu64
    read_data = random_bytes(9, 300_000)
    block = random_bytes(8, 1 << 20)
    total = 3 * (1 << 20) + 12_345
    stream = (block * 4)[:total]
    return {
        "read": {"seed": 9, "n": 300_000, "digest": h(page_sample_digest(read_data))},
        "write": {"seed": 8, "bytes": total, "digest": h(page_sample_digest(stream))},
        "lines": {"fixture": "spec/fixtures/requests-16KiB.csv",
                  "digest": h(lines_digest((FIXTURES / "requests-16KiB.csv").read_text()))},
    }


def sections() -> dict:
    return {"cpu": cpu_section(), "memory": memory_section(), "json": json_section(),
            "concurrency": concurrency_section(), "io": io_section()}
