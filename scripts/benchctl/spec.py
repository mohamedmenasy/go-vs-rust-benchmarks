"""Load bench.toml and expand it into concrete (workload, size) runs."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import DATASETS_DIR, LANGS, ROOT, parse_cpuset, parse_size

HARNESS_KINDS = {"harness"}


@dataclass(frozen=True)
class Size:
    label: str
    params: dict[str, str]  # values already stringified, sizes converted to integers
    profiles: tuple[str, ...]
    raw: dict[str, Any]

    def inputs(self) -> list[str]:
        """Dataset paths (relative to datasets/) referenced by this size."""
        return [str(v) for k, v in self.raw.items() if k == "input" or k.startswith("input_")]


@dataclass
class Workload:
    id: str
    category: str
    bin: str
    impl: dict[str, str]
    track: str
    cores: str
    desc: str
    sizes: list[Size]
    kind: str = "harness"
    langs: tuple[str, ...] = LANGS
    flavor: dict[str, str] = field(default_factory=dict)
    env: dict[str, dict[str, str]] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    rounds: dict[str, int] = field(default_factory=dict)
    variant_of: str | None = None
    notes: str = ""
    alloc_pass: bool = True
    timeout_s: float = 900.0
    sample_ms: int = 20
    extra: dict[str, Any] = field(default_factory=dict)

    def impl_for(self, lang: str) -> str:
        return self.impl.get(lang, self.impl.get("*", self.id.split(".")[-1]))

    def flavor_for(self, lang: str) -> str:
        return self.flavor.get(lang, "")

    def env_for(self, lang: str) -> dict[str, str]:
        return dict(self.env.get(lang, {}))


@dataclass
class Profile:
    name: str
    rounds: int
    timing: dict[str, Any]


@dataclass
class Spec:
    path: Path
    seed: int
    profiles: dict[str, Profile]
    cores: dict[str, str]
    workloads: list[Workload]
    categories: dict[str, dict[str, Any]]

    def workload(self, wid: str) -> Workload:
        for w in self.workloads:
            if w.id == wid:
                return w
        raise KeyError(wid)

    def select(
        self,
        profile: str,
        categories: list[str] | None = None,
        ids: list[str] | None = None,
        tracks: list[str] | None = None,
        kinds: set[str] | None = None,
    ) -> list[tuple[Workload, Size]]:
        if profile not in self.profiles:
            raise KeyError(f"unknown profile {profile!r}")
        out = []
        for w in self.workloads:
            if categories and w.category not in categories:
                continue
            if ids and w.id not in ids:
                continue
            if tracks and w.track not in tracks:
                continue
            if kinds and w.kind not in kinds:
                continue
            for s in w.sizes:
                if profile in s.profiles:
                    out.append((w, s))
        return out

    def timing_for(self, profile: str, w: Workload) -> dict[str, Any]:
        t = dict(self.profiles[profile].timing)
        override = w.timing.get(profile, w.timing.get("*", {}))
        t.update(override)
        return t

    def rounds_for(self, profile: str, w: Workload) -> int:
        return int(w.rounds.get(profile, self.profiles[profile].rounds))

    def cpus(self, key: str) -> str:
        if key in self.cores:
            return self.cores[key]
        return key  # literal cpuset such as "2-3"

    def ncpus(self, key: str) -> int:
        return len(parse_cpuset(self.cpus(key)))

    def category_names(self) -> list[str]:
        seen: list[str] = []
        for w in self.workloads:
            if w.category not in seen:
                seen.append(w.category)
        return seen


def _stringify_params(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in raw.items():
        if k in ("label", "profiles"):
            continue
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (int, float)):
            out[k] = str(v)
        elif isinstance(v, str):
            if k == "input" or k.startswith("input_"):
                out[k] = str(DATASETS_DIR / v)
            else:
                size = parse_size(v)
                out[k] = str(size) if size is not None else v
        else:
            raise ValueError(f"unsupported param type for {k}: {type(v).__name__}")
    return out


def _as_lang_map(value: Any, default: str) -> dict[str, str]:
    if value is None:
        return {"*": default}
    if isinstance(value, str):
        return {"*": value}
    return {str(k): str(v) for k, v in value.items()}


def load(path: Path | None = None) -> Spec:
    path = path or (ROOT / "bench.toml")
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    profiles = {
        name: Profile(name=name, rounds=int(p["rounds"]), timing=dict(p.get("timing", {})))
        for name, p in doc["profiles"].items()
    }
    workloads: list[Workload] = []
    seen: set[str] = set()
    for w in doc.get("workload", []):
        wid = w["id"]
        if wid in seen:
            raise ValueError(f"duplicate workload id {wid}")
        seen.add(wid)
        sizes = []
        for s in w["sizes"]:
            profs = tuple(s.get("profiles", list(profiles)))
            for p in profs:
                if p not in profiles:
                    raise ValueError(f"{wid}: unknown profile {p!r} in size {s.get('label')}")
            sizes.append(Size(label=str(s["label"]), params=_stringify_params(s), profiles=profs, raw=dict(s)))
        env = {lang: {k: str(v) for k, v in vals.items()} for lang, vals in w.get("env", {}).items()}
        workloads.append(
            Workload(
                id=wid,
                category=w["category"],
                bin=w.get("bin", w["category"]),
                impl=_as_lang_map(w.get("impl"), wid.split(".")[-1]),
                track=w.get("track", "baseline"),
                cores=w.get("cores", "single"),
                desc=w.get("desc", ""),
                sizes=sizes,
                kind=w.get("kind", "harness"),
                langs=tuple(w.get("langs", LANGS)),
                flavor={k: str(v) for k, v in w.get("flavor", {}).items()},
                env=env,
                timing=dict(w.get("timing", {})),
                rounds={k: int(v) for k, v in w.get("rounds", {}).items()},
                variant_of=w.get("variant_of"),
                notes=w.get("notes", ""),
                alloc_pass=bool(w.get("alloc_pass", True)),
                timeout_s=float(w.get("timeout_s", 900)),
                sample_ms=int(w.get("sample_ms", 20)),
                extra=dict(w.get("extra", {})),
            )
        )
    return Spec(
        path=path,
        seed=int(doc.get("suite", {}).get("seed", 1)),
        profiles=profiles,
        cores={k: str(v) for k, v in doc.get("cores", {}).items()},
        workloads=workloads,
        categories=dict(doc.get("category", {})),
    )
