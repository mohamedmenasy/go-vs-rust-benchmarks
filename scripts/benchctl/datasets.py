"""Deterministic shared datasets.

Every file is derived from a SplitMix64 stream (the same generator the Go and
Rust programs use in-process) seeded with the FNV-1a hash of the dataset
family name. Sizes of one family are prefixes of the same stream. The SHA-256
of every generated file is pinned in datasets/manifest.json; a machine that
produces different bytes is refused, so every comparison on every machine
reads exactly the same input.

Families (`<family>-<size>.<ext>` under datasets/):

* ``bin/random``    little-endian u64 words straight from the stream
* ``csv/requests``  request-log CSV: ts,user_id,endpoint,status,latency_ms,bytes
* ``text/corpus``   space/newline separated words, ~10% non-ASCII, with planted
                    e-mails, dates, integers, decimals and keyword tokens
* ``json/object``   one nested API-response object of roughly the target size
* ``json/array``    a top-level array of N user objects
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from . import refimpl as R
from .util import DATASETS_DIR, human_bytes, log, parse_size, read_json, sha256_file, write_json

GENERATOR_VERSION = 1
MANIFEST = DATASETS_DIR / "manifest.json"
_NAME_RE = re.compile(r"^(?P<family>[a-z]+/[a-z]+)-(?P<size>[0-9]+(?:KiB|MiB|GiB|k|K)?)\.(?P<ext>bin|csv|txt|json)$")


def family_seed(family: str) -> int:
    return R.fnv1a64(family.encode())


# ---------------------------------------------------------------------------
# Shared vocabulary (also used by JSON generation)
# ---------------------------------------------------------------------------

_SYLLABLES = [
    "ka", "lo", "mi", "ne", "ru", "sta", "ber", "chi", "dan", "fel", "gor", "hal", "ist", "jun", "kor",
    "lem", "mon", "nar", "ost", "pel", "qui", "ras", "sen", "tor", "ul", "ven", "wil", "xen", "yor", "zam",
    "an", "el", "in", "or", "us", "ta", "re", "co", "de", "pa",
]

COMMON_WORDS = [
    "the", "of", "and", "to", "in", "is", "that", "for", "it", "with", "as", "was", "on", "be", "at",
    "by", "this", "from", "or", "have", "benchmark", "rust", "golang", "memory", "latency", "throughput",
    "error", "warning", "server", "request",
]

# Non-ASCII words. Characters with Unicode SpecialCasing mappings (ß, İ, ŉ,
# ǰ, ΐ, ΰ, ligatures, iota-subscript Greek, ...) are deliberately excluded:
# Rust's to_uppercase applies them and Go's strings.ToUpper does not, which
# would make the two programs do different work.
UNICODE_WORDS = [
    "café", "naïve", "façade", "résumé", "jalapeño", "piñata", "über", "Ångström", "crème", "brûlée",
    "São", "Kraków", "Łódź", "Dvořák", "Øresund", "Ærøskøbing", "smörgåsbord", "déjà", "coöperate", "señor",
    "λόγος", "αλήθεια", "Αθήνα", "καλημέρα", "φως", "ταχύτητα", "μνήμη",
    "привет", "мир", "данные", "скорость", "память", "Москва", "сервер",
    "東京", "日本語", "中文", "数据", "速度", "内存", "한국어", "서울", "메모리",
    "مرحبا", "بيانات", "שלום", "זיכרון", "नमस्ते", "गति",
    "🚀", "✨", "🦀", "🐹", "👍🏽", "🔥", "⚡",
]

_DOMAINS = ["example.com", "mail.test", "corp.example.org", "bench.dev"]
_KEYWORDS = ["foo", "bar", "baz", "qux"]


def ascii_vocabulary(n: int = 2000) -> list[str]:
    """Deterministic pronounceable pseudo-words (unique)."""
    g = R.SplitMix64(family_seed("vocab/ascii"))
    words: list[str] = []
    seen: set[str] = set(COMMON_WORDS)
    while len(words) < n:
        k = 2 + g.below(3)
        w = "".join(_SYLLABLES[g.below(len(_SYLLABLES))] for _ in range(k))
        if w not in seen:
            seen.add(w)
            words.append(w)
    return words


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

def _gen_random_bin(target: int) -> Iterator[bytes]:
    seed = family_seed("bin/random")
    words = target // 8
    chunk = 1 << 23
    for start in range(0, words, chunk):
        n = min(chunk, words - start)
        yield R.splitmix64_np(seed, start, n).astype("<u8").tobytes()
    rem = target - words * 8
    if rem:
        yield R.splitmix64_np(seed, words, 1).astype("<u8").tobytes()[:rem]


ENDPOINTS = [
    "/api/v1/users", "/api/v1/users/{id}", "/api/v1/orders", "/api/v1/orders/{id}", "/api/v1/products",
    "/api/v1/products/{id}", "/api/v1/cart", "/api/v1/checkout", "/api/v1/search", "/api/v1/login",
    "/api/v1/logout", "/api/v1/session", "/api/v2/recommendations", "/api/v2/inventory", "/api/v2/reviews",
    "/static/app.js", "/static/app.css", "/healthz", "/metrics", "/",
]
_STATUS_CUM = [(780, 200), (830, 201), (850, 204), (860, 301), (900, 304), (930, 400), (945, 401),
               (955, 403), (985, 404), (995, 500), (998, 502), (1000, 503)]


def _status_table() -> np.ndarray:
    table = np.empty(1000, dtype=np.int64)
    lo = 0
    for hi, code in _STATUS_CUM:
        table[lo:hi] = code
        lo = hi
    return table


CSV_HEADER = "ts,user_id,endpoint,status,latency_ms,bytes\n"


def _gen_csv_requests(target: int) -> Iterator[bytes]:
    seed = family_seed("csv/requests")
    status_tab = _status_table()
    header = CSV_HEADER.encode()
    yield header
    written = len(header)
    row = 0
    rows_per_chunk = 1 << 18
    while written < target:
        z = R.splitmix64_np(seed, row * 5, rows_per_chunk * 5).reshape(-1, 5)
        ts = (1_700_000_000 + np.arange(row, row + rows_per_chunk, dtype=np.int64)).tolist()
        user = R.below_np(z[:, 0], 1_000_000).tolist()
        ep = R.below_np(z[:, 1], len(ENDPOINTS)).tolist()
        st = status_tab[R.below_np(z[:, 2], 1000).astype(np.int64)].tolist()
        lat = R.below_np(z[:, 3], 5_000_000).tolist()
        size = R.below_np(z[:, 4], 2_000_000).tolist()
        lines = [
            f"{t},{u},{ENDPOINTS[e]},{s},{la // 1000}.{la % 1000:03d},{b}\n"
            for t, u, e, s, la, b in zip(ts, user, ep, st, lat, size)
        ]
        data = "".join(lines).encode()
        if written + len(data) > target:
            cut = data.rfind(b"\n", 0, target - written)
            data = data[: cut + 1] if cut >= 0 else b""
            yield data
            return
        yield data
        written += len(data)
        row += rows_per_chunk


def _corpus_tables() -> dict:
    vocab = ascii_vocabulary()
    return {"vocab": vocab, "vocab_arr": np.array(vocab, dtype=object), "uni_arr": np.array(UNICODE_WORDS, dtype=object),
            "common_arr": np.array(COMMON_WORDS, dtype=object)}


def corpus_tokens(start: int, count: int, tables: dict | None = None) -> tuple[list[str], np.ndarray]:
    """Tokens start..start+count-1 of the corpus stream and their line-break flags."""
    t = tables or _corpus_tables()
    seed = family_seed("text/corpus")
    z = R.splitmix64_np(seed, start * 2, count * 2)
    z1, z2 = z[0::2], z[1::2]
    cat = R.below_np(z1, 1000)
    tokens = np.empty(count, dtype=object)
    # 83.5%: ASCII words, 30% of which are common words, 5% capitalised
    m_ascii = cat >= 165
    pick_common = R.below_np(z2, 100) < 30
    idx_common = (z2 >> np.uint64(8)) % np.uint64(len(COMMON_WORDS))
    idx_vocab = (z2 >> np.uint64(8)) % np.uint64(len(t["vocab"]))
    words = np.where(pick_common, t["common_arr"][idx_common.astype(np.int64)], t["vocab_arr"][idx_vocab.astype(np.int64)])
    cap = ((z2 >> np.uint64(40)) % np.uint64(100)) < 5
    words = np.where(cap, np.char.capitalize(words.astype(str)).astype(object), words)
    tokens[m_ascii] = words[m_ascii]
    m_uni = cat < 100
    tokens[m_uni] = t["uni_arr"][((z2[m_uni] >> np.uint64(8)) % np.uint64(len(UNICODE_WORDS))).astype(np.int64)]
    # Variable tokens (6.5%): build individually.
    for i in np.nonzero((cat >= 100) & (cat < 165))[0].tolist():
        c = int(cat[i])
        v = int(z2[i])
        if c < 105:  # e-mail
            tokens[i] = f"{t['vocab'][v % len(t['vocab'])]}{(v >> 20) % 1000}@{_DOMAINS[(v >> 40) % len(_DOMAINS)]}"
        elif c < 110:  # ISO date
            tokens[i] = f"{2000 + v % 30:04d}-{1 + (v >> 8) % 12:02d}-{1 + (v >> 16) % 28:02d}"
        elif c < 140:  # integer, sometimes negative
            n = (v >> 4) % (10 ** (1 + (v % 7)))
            tokens[i] = f"-{n}" if (v >> 60) % 8 == 0 else str(n)
        elif c < 160:  # decimal with 1-4 fraction digits
            frac_digits = 1 + (v % 4)
            ip = (v >> 8) % 100_000
            fp = (v >> 32) % (10**frac_digits)
            tokens[i] = f"{ip}.{fp:0{frac_digits}d}"
        else:  # keyword token for alternation regexes
            tokens[i] = f"{_KEYWORDS[v % len(_KEYWORDS)]}{(v >> 8) % 1000}"
    breaks = ((z1 >> np.uint64(32)) % np.uint64(12)) == 0
    return tokens.tolist(), breaks


def _gen_text_corpus(target: int) -> Iterator[bytes]:
    tables = _corpus_tables()
    written = 0
    start = 0
    chunk = 1 << 19
    while written < target:
        toks, breaks = corpus_tokens(start, chunk, tables)
        seps = np.where(breaks, "\n", " ").tolist()
        data = "".join(f"{t}{s}" for t, s in zip(toks, seps)).encode()
        if written + len(data) > target:
            cut = data.rfind(b"\n", 0, target - written)
            data = data[: cut + 1] if cut >= 0 else b""
            yield data
            return
        yield data
        written += len(data)
        start += chunk


# JSON families are implemented in datasets_json.py (added with the JSON category).
GENERATORS: dict[str, tuple[str, Callable[[int], Iterator[bytes]]]] = {
    "bin/random": ("bin", _gen_random_bin),
    "csv/requests": ("csv", _gen_csv_requests),
    "text/corpus": ("txt", _gen_text_corpus),
}


def _register_json() -> None:
    try:
        from . import datasets_json  # noqa: PLC0415
    except ImportError:
        return
    GENERATORS.update(datasets_json.GENERATORS)


def _target(size: str) -> int:
    b = parse_size(size)
    if b is not None:
        return b
    m = re.match(r"^(\d+)([kK]?)$", size)
    if m:
        return int(m.group(1)) * (1000 if m.group(2) else 1)
    raise ValueError(f"bad dataset size {size!r}")


def generate(rel: str) -> Path:
    _register_json()
    m = _NAME_RE.match(rel)
    if not m or m.group("family") not in GENERATORS:
        raise ValueError(f"unknown dataset {rel!r}")
    ext, gen = GENERATORS[m.group("family")]
    if m.group("ext") != ext:
        raise ValueError(f"dataset {rel!r} must have extension .{ext}")
    path = DATASETS_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    with open(tmp, "wb") as f:
        for chunk in gen(_target(m.group("size"))):
            f.write(chunk)
    tmp.replace(path)
    return path


def load_manifest() -> dict:
    if MANIFEST.exists():
        return read_json(MANIFEST)
    return {"generator_version": GENERATOR_VERSION, "files": {}}


def ensure(rels: list[str], *, update_manifest: bool = False, verify_existing: bool = True) -> bool:
    """Generate missing datasets and verify every file against the manifest."""
    manifest = load_manifest()
    files = manifest.setdefault("files", {})
    if manifest.get("generator_version") != GENERATOR_VERSION and not update_manifest:
        log(f"manifest generator_version {manifest.get('generator_version')} != {GENERATOR_VERSION}; "
            "regenerate with --update-manifest", level="error")
        return False
    ok = True
    changed = False
    for rel in sorted(set(rels)):
        path = DATASETS_DIR / rel
        fresh = False
        if not path.exists():
            log(f"generating {rel} ...")
            generate(rel)
            fresh = True
        elif not verify_existing and rel in files:
            continue
        digest = sha256_file(path)
        size = path.stat().st_size
        entry = files.get(rel)
        if entry is None or update_manifest:
            if entry is not None and entry.get("sha256") != digest:
                log(f"{rel}: manifest updated ({entry.get('sha256')[:12]} -> {digest[:12]})", level="warn")
            files[rel] = {"bytes": size, "sha256": digest}
            changed = True
            log(f"{rel}: {human_bytes(size)} sha256={digest[:16]} (recorded)")
        elif entry["sha256"] != digest:
            log(f"{rel}: sha256 {digest} does not match manifest {entry['sha256']} "
                f"({'freshly generated' if fresh else 'existing file'}); inputs would differ from the reference", level="error")
            ok = False
        else:
            log(f"{rel}: {human_bytes(size)} verified")
    if changed:
        manifest["generator_version"] = GENERATOR_VERSION
        manifest["files"] = dict(sorted(files.items()))
        write_json(MANIFEST, manifest, indent=1)
    return ok


def describe() -> str:
    return json.dumps(load_manifest(), indent=1)
