"""Binary-size category driver (METHODOLOGY.md §13.10).

Deterministic measurements, taken once per build variant (no repetitions):

* on-disk size, size after GNU ``strip`` (a copy), ELF section totals
  (``size``: text / data / bss), static vs dynamic linking and the ``ldd``
  list;
* dependency footprint per program: Go packages and non-main modules
  (``go list -deps``), Rust crates in the normal dependency graph
  (``cargo tree -e normal``). The standard libraries are not counted.

Variants (``[binsize]`` in bench.toml); ``pair`` names the other language's
variant it is compared against:

  go:   default (CGO_ENABLED=0, as benchmarked), stripped (-ldflags="-s -w"),
        cgo (CGO_ENABLED=1; dynamic, for programs listed in cgo_programs)
  rust: default (stock release), strip (profile strip = "symbols"),
        tuned (release-tuned: fat LTO, cgu=1, panic=abort),
        size (release-size: opt-level="z" + tuned + strip),
        static (crt-static; hello and http-axum only)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import builds, orchestrate
from .spec import Spec
from .util import ROOT, log, now_iso, sha256_file, write_json

OUT = ROOT / "bin" / "binsize"
GO_BUILD = ["go", "build", "-trimpath", "-buildvcs=false"]


def _go_env(**extra) -> dict:
    env = dict(os.environ)
    env.update({"CGO_ENABLED": "0", "GOAMD64": "v1", "GOTOOLCHAIN": env.get("GOTOOLCHAIN", "go1.27.1")})
    env.update(extra)
    return env


def _sh(cmd: list[str], cwd: Path, env: dict | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{p.stderr[-3000:]}")
    return p.stdout


# --------------------------------------------------------------------------- builds

def build_variants(programs: list[dict], cgo_programs: list[str]) -> dict[tuple[str, str, str], Path]:
    """Build the size-only variants; returns {(lang, variant, program_name): path}."""
    paths: dict[tuple[str, str, str], Path] = {}
    go_dir, rust_dir = ROOT / "go", ROOT / "rust"
    for prog in programs:
        name, g, r = prog["name"], prog["go"], prog["rust"]
        paths[("go", "default", name)] = builds.bin_path("go", g)
        out = OUT / "go-stripped" / g
        out.parent.mkdir(parents=True, exist_ok=True)
        _sh([*GO_BUILD, "-ldflags=-s -w", "-o", str(out), f"./{g}"], go_dir, _go_env())
        paths[("go", "stripped", name)] = out
        if name in cgo_programs:
            out = OUT / "go-cgo" / g
            out.parent.mkdir(parents=True, exist_ok=True)
            _sh([*GO_BUILD, "-o", str(out), f"./{g}"], go_dir, _go_env(CGO_ENABLED="1"))
            paths[("go", "cgo", name)] = out
        paths[("rust", "default", name)] = builds.bin_path("rust", r)
        paths[("rust", "tuned", name)] = builds.bin_path("rust", r, "tuned")
        static = builds.bin_path("rust", r, "static")
        if static.exists():
            paths[("rust", "static", name)] = static
    log("building rust strip / size variants")
    env = dict(os.environ, CARGO_PROFILE_RELEASE_STRIP="symbols")
    _sh(["cargo", "build", "--locked", "--release", "--workspace", "--target-dir", "target/flavor-strip"], rust_dir, env)
    _sh(["cargo", "build", "--locked", "--profile", "release-size", "--workspace"], rust_dir)
    for prog in programs:
        name, r = prog["name"], prog["rust"]
        paths[("rust", "strip", name)] = rust_dir / "target" / "flavor-strip" / "release" / r
        paths[("rust", "size", name)] = rust_dir / "target" / "release-size" / r
    return paths


# --------------------------------------------------------------------------- measurements

def measure(path: Path) -> dict:
    rec: dict = {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / path.name
        shutil.copy2(path, tmp)
        subprocess.run(["strip", str(tmp)], check=True, capture_output=True)
        rec["stripped_bytes"] = tmp.stat().st_size
    m = re.search(r"^\s*(\d+)\s+(\d+)\s+(\d+)", _sh(["size", str(path)], ROOT).splitlines()[1])
    if m:
        rec.update({"text_bytes": int(m[1]), "data_bytes": int(m[2]), "bss_bytes": int(m[3])})
    ftype = _sh(["file", "-b", str(path)], ROOT).strip()
    rec["file"] = ftype
    rec["static"] = "statically linked" in ftype or "static-pie" in ftype
    p = subprocess.run(["ldd", str(path)], capture_output=True, text=True)
    libs = [ln.split()[0] for ln in p.stdout.splitlines() if ln.strip() and "=>" in ln or "ld-linux" in ln]
    rec["dynamic_libs"] = [] if rec["static"] else sorted(libs)
    return rec


def go_deps(pkg: str) -> dict:
    go_dir = ROOT / "go"
    fmt = "{{.ImportPath}}|{{.Standard}}|{{with .Module}}{{if not .Main}}{{.Path}}@{{.Version}}{{end}}{{end}}"
    lines = _sh(["go", "list", "-deps", "-f", fmt, f"./{pkg}"], go_dir, _go_env()).split()
    std = [ln for ln in lines if ln.split("|")[1] == "true"]
    mods = sorted({ln.split("|")[2] for ln in lines if ln.split("|")[2]})
    return {"packages_total": len(lines), "packages_std": len(std), "packages_nonstd": len(lines) - len(std),
            "modules": mods, "modules_count": len(mods)}


def rust_deps(bin_name: str) -> dict:
    out = _sh(["cargo", "tree", "--locked", "--offline", "-p", f"bench-{bin_name}", "-e", "normal", "--prefix", "none",
               "-f", "{p}"], ROOT / "rust")
    crates = sorted({ln.replace(" (*)", "").split(" (")[0] for ln in out.splitlines() if ln.strip()})
    external = [c for c in crates if not c.startswith("bench-")]
    return {"crates": external, "crates_count": len(external),
            "workspace_crates": len(crates) - len(external)}


def load_config(spec: Spec) -> dict:
    return dict(spec.raw.get("binsize", {}))


def run(spec: Spec, profile: str, run_id: str, mode: str, ids=None, rounds_override=None, resume=False) -> Path:
    cfg = load_config(spec)
    programs = cfg["programs"]
    base = orchestrate.ensure_run_metadata(run_id, mode, profile)
    started = now_iso()
    paths = build_variants(programs, cfg.get("cgo_programs", []))
    recs = []
    for (lang, variant, name), path in sorted(paths.items()):
        if not path.exists():
            log(f"binsize: {lang}/{variant}/{name}: {path} missing", level="warn")
            continue
        rec = {"run_id": run_id, "mode": mode, "category": "binsize", "lang": lang, "variant": variant,
               "program": name, **measure(path)}
        recs.append(rec)
        log(f"[binsize] {lang:<4} {variant:<8} {name:<16} {rec['bytes'] / 2**20:7.2f} MiB "
            f"(strip {rec['stripped_bytes'] / 2**20:6.2f} MiB) {'static' if rec['static'] else 'dynamic'}")
    deps = {}
    for prog in programs:
        deps[prog["name"]] = {"go": go_deps(prog["go"]), "rust": rust_deps(prog["rust"])}
        log(f"[binsize deps] {prog['name']:<16} go: {deps[prog['name']]['go']['packages_nonstd']} non-std pkgs / "
            f"{deps[prog['name']]['go']['modules_count']} modules; rust: {deps[prog['name']]['rust']['crates_count']} crates")
    write_json(base / "binsize" / "binaries.json", {"binaries": recs, "pairs": cfg.get("pairs", [])}, indent=1)
    write_json(base / "binsize" / "deps.json", deps, indent=1)
    orchestrate._record_invocation(base, {"kind": "binsize", "categories": ["binsize"], "profile": profile,
                                          "started_at": started, "finished_at": now_iso()})
    return base
