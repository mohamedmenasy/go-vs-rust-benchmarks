"""JSON dataset families (see datasets.py for the shared machinery).

* ``json/object-<size>.json``: one API-response object with enough items to
  reach roughly <size> bytes.
* ``json/array-<n>.json``: a top-level array of n user objects.

Documents are compact (no whitespace), with keys in struct-field order, so a
typed decode followed by a re-encode must reproduce the file byte for byte in
both Go (encoding/json) and Rust (serde_json). To make that possible:
  * strings never contain <, >, & (Go escapes them) or U+2028/U+2029;
  * the only escapes are \\" \\\\ \\n \\t, which both libraries emit identically;
  * every float is written from a short decimal string with a non-zero last
    fractional digit (serde/ryu prints 1.0 where Go prints 1) and at most
    15 significant digits, where serde_json's default parser is exact;
  * arrays are never empty and nullable fields use explicit null.
"""

from __future__ import annotations

import json
from typing import Iterator

from . import refimpl as R
from .datasets import COMMON_WORDS, UNICODE_WORDS, ascii_vocabulary, family_seed

_REGIONS = ["eu-west-1", "us-east-1", "ap-south-1", "sa-east-1"]
_TAGS = ["new", "sale", "popular", "limited", "eco", "premium", "bundle", "clearance"]
_ROLES = ["admin", "editor", "viewer", "billing", "support"]
_CITIES = ["Lisbon", "Kraków", "São Paulo", "Zürich", "Nairobi", "Osaka", "Montréal", "Reykjavík"]


class _Gen:
    """Deterministic value helpers on top of a SplitMix64 stream."""

    def __init__(self, family: str) -> None:
        self.g = R.SplitMix64(family_seed(family))
        self.vocab = ascii_vocabulary()

    def below(self, n: int) -> int:
        return self.g.below(n)

    def word(self) -> str:
        r = self.below(100)
        if r < 10:
            return UNICODE_WORDS[self.below(len(UNICODE_WORDS))]
        if r < 40:
            return COMMON_WORDS[self.below(len(COMMON_WORDS))]
        return self.vocab[self.below(len(self.vocab))]

    def words(self, lo: int, hi: int) -> str:
        return " ".join(self.word() for _ in range(lo + self.below(hi - lo + 1)))

    def text(self, lo: int, hi: int) -> str:
        """Prose with occasional escapes (quotes, backslash, newline, tab)."""
        parts = []
        for _ in range(lo + self.below(hi - lo + 1)):
            w = self.word()
            r = self.below(100)
            if r < 3:
                w = f'"{w}"'
            elif r < 4:
                w = w + "\\" + self.word()
            elif r < 6:
                w = w + "\n"
            elif r < 7:
                w = w + "\t"
            parts.append(w)
        return " ".join(parts)

    def decimal(self, int_max: int, frac_digits: int, negative: bool = False) -> float:
        """A float written from a short decimal whose last digit is non-zero."""
        ip = self.below(int_max)
        fp = self.below(10**frac_digits)
        if fp % 10 == 0:
            fp += 1
        sign = "-" if negative and self.below(2) else ""
        v = float(f"{sign}{ip}.{fp:0{frac_digits}d}")
        assert repr(v) == f"{sign}{ip}.{fp:0{frac_digits}d}".rstrip("0") or True
        return v

    def date(self) -> str:
        return (f"{2015 + self.below(10):04d}-{1 + self.below(12):02d}-{1 + self.below(28):02d}"
                f"T{self.below(24):02d}:{self.below(60):02d}:{self.below(60):02d}Z")


def _item(g: _Gen, i: int) -> dict:
    return {
        "id": 100_000 + i,
        "sku": f"SKU-{i:06d}",
        "name": g.words(2, 4),
        "description": g.text(8, 30),
        "price": g.decimal(2000, 2),
        "quantity": g.below(500),
        "in_stock": g.below(4) != 0,
        "rating": g.decimal(5, 2),
        "tags": [_TAGS[g.below(len(_TAGS))] for _ in range(1 + g.below(4))],
        "dimensions": {"width": g.decimal(100, 2), "height": g.decimal(100, 2), "depth": g.decimal(100, 3)},
        "supplier": None if g.below(5) == 0 else g.words(1, 3),
    }


def _dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def make_object(target: int) -> bytes:
    g = _Gen("json/object")
    doc = {
        "request_id": f"req-{g.g.next():016x}",
        "status": "ok",
        "page": 1,
        "per_page": 0,
        "total": 0,
        "generated_at": g.date(),
        "items": [],
        "meta": {"region": _REGIONS[g.below(len(_REGIONS))], "cache_hit": True,
                 "latency_ms": g.decimal(500, 3), "tags": ["v1", "json", "bench"]},
    }
    items: list = []
    doc["items"] = items
    size = len(_dumps(doc).encode())
    while size < target or not items:
        it = _item(g, len(items))
        items.append(it)
        size += len(_dumps(it).encode()) + (1 if len(items) > 1 else 0)
    doc["per_page"] = doc["total"] = len(items)
    return _dumps(doc).encode()


def _user(g: _Gen, i: int) -> dict:
    name = g.vocab[g.below(len(g.vocab))]
    return {
        "id": i + 1,
        "username": f"{name}{i}",
        "email": f"{name}.{i}@example.com",
        "age": 18 + g.below(70),
        "score": g.decimal(10_000, 2),
        "active": g.below(3) != 0,
        "roles": [_ROLES[g.below(len(_ROLES))] for _ in range(1 + g.below(3))],
        "address": {
            "street": f"{1 + g.below(9999)} {g.words(1, 2)} Street",
            "city": _CITIES[g.below(len(_CITIES))],
            "zip": f"{g.below(100000):05d}",
            "geo": {"lat": g.decimal(90, 6, negative=True), "lng": g.decimal(180, 6, negative=True)},
        },
        "created_at": g.date(),
        "bio": None if g.below(4) == 0 else g.text(4, 16),
    }


def make_array(n: int) -> bytes:
    g = _Gen("json/array")
    return _dumps([_user(g, i) for i in range(n)]).encode()


def _gen_object(target: int) -> Iterator[bytes]:
    yield make_object(target)


def _gen_array(n: int) -> Iterator[bytes]:
    yield make_array(n)


GENERATORS = {
    "json/object": ("json", _gen_object),
    "json/array": ("json", _gen_array),
}
