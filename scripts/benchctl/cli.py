"""Command-line interface: `scripts/bench <command> ...`."""

from __future__ import annotations

import argparse
import os
import sys

from . import spec as specmod
from .util import RAW_DIR, die, log, new_run_id, read_json, write_json

# Categories driven by dedicated modules instead of the harness protocol.
SPECIAL_DRIVERS = {
    "http": ("benchctl.http", "run"),
    "startup": ("benchctl.startup", "run"),
    "binsize": ("benchctl.binsize", "run"),
    "compile": ("benchctl.compile", "run"),
}


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", default=os.environ.get("PROFILE", "standard"))
    p.add_argument("--category", "-c", action="append", help="category (repeatable)")
    p.add_argument("--id", action="append", help="workload id (repeatable)")
    p.add_argument("--track", action="append", help="baseline|idiomatic|tuned (repeatable)")


def _needed_datasets(spec, profile: str, categories, ids) -> list[str]:
    rels: list[str] = []
    for w, s in spec.select(profile, categories, ids):
        rels.extend(s.inputs())
    return rels


def cmd_env(args, spec) -> int:
    from . import envinfo

    info = envinfo.capture(args.mode)
    if args.out:
        write_json(args.out, info, indent=1)
        log(f"wrote {args.out}")
    else:
        import json

        print(json.dumps(info, indent=1))
    return 0


def cmd_golden(args, spec) -> int:
    from . import golden
    from .util import ROOT

    if args.check:
        ok = golden.check(ROOT)
        log("spec/golden.json is " + ("up to date" if ok else "STALE (run `scripts/bench golden`)"))
        return 0 if ok else 1
    log(f"wrote {golden.write(ROOT)}")
    return 0


def cmd_datasets(args, spec) -> int:
    from . import datasets

    if args.name:
        rels = args.name
    elif args.all_profiles:
        rels = []
        for prof in spec.profiles:
            rels += _needed_datasets(spec, prof, args.category, args.id)
    else:
        rels = _needed_datasets(spec, args.profile, args.category, args.id)
    if not rels:
        log("no datasets needed for this selection")
        return 0
    ok = datasets.ensure(rels, update_manifest=args.update_manifest, verify_existing=not args.fast)
    return 0 if ok else 1


def cmd_validate(args, spec) -> int:
    from . import validate

    if not args.skip_datasets:
        from . import datasets

        rels = _needed_datasets(spec, args.profile, args.category, args.id)
        if rels and not datasets.ensure(rels, verify_existing=False):
            return 1
    ok = validate.validate(spec, args.profile, args.category, args.id)
    return 0 if ok else 1


def cmd_run(args, spec) -> int:
    from . import orchestrate

    run_id = args.run_id or os.environ.get("RUN_ID") or new_run_id(args.mode)
    cats = args.category or spec.category_names()
    harness_cats = [c for c in cats if c not in SPECIAL_DRIVERS]
    log(f"run_id={run_id} profile={args.profile} mode={args.mode} categories={','.join(cats)}")
    if harness_cats:
        orchestrate.run_harness(
            spec,
            args.profile,
            run_id,
            args.mode,
            categories=harness_cats,
            ids=args.id,
            tracks=args.track,
            rounds_override=args.rounds,
            resume=args.resume,
            alloc_pass=not args.no_alloc_pass,
        )
    for cat in cats:
        if cat in SPECIAL_DRIVERS:
            mod_name, fn = SPECIAL_DRIVERS[cat]
            try:
                mod = __import__(mod_name, fromlist=[fn])
            except ImportError as e:
                log(f"category {cat}: driver not available ({e})", level="warn")
                continue
            getattr(mod, fn)(spec, args.profile, run_id, args.mode, ids=args.id, rounds_override=args.rounds,
                             resume=args.resume)
    print(run_id)
    return 0


def cmd_plan(args, spec) -> int:
    total = 0.0
    rows = []
    for w, s in spec.select(args.profile, args.category, args.id):
        if w.kind != "harness":
            continue
        t = spec.timing_for(args.profile, w)
        per_proc = (t.get("warmup_min_ms", 0) + t.get("min_ms", 0)) / 1000 + float(w.extra.get("est_overhead_s", 0.5))
        per_proc = max(per_proc, float(w.extra.get("est_s", 0)))
        n = spec.rounds_for(args.profile, w) * len(w.langs) + (1 if w.alloc_pass else 0)
        est = per_proc * n
        total += est
        rows.append((w.id, s.label, n, est))
    for wid, label, n, est in rows:
        print(f"{wid:<36} {label:<10} {n:>4} procs  ~{est / 60:6.1f} min")
    print(f"TOTAL (harness categories only, lower bound): ~{total / 3600:.2f} h")
    return 0


def cmd_docs(args, spec) -> int:
    from . import docs

    log(f"wrote {docs.write(spec)}")
    return 0


def cmd_list(args, spec) -> int:
    for w, s in spec.select(args.profile, args.category, args.id, args.track):
        print(f"{w.category:<12} {w.id:<36} {s.label:<10} track={w.track:<9} cores={spec.cpus(w.cores)}")
    return 0


def cmd_process(args, spec) -> int:
    sys.path.insert(0, str(RAW_DIR.parents[1] / "scripts"))
    from analysis import process

    return process.main(args)


def cmd_charts(args, spec) -> int:
    from analysis import charts

    return charts.main(args)


def cmd_report(args, spec) -> int:
    from analysis import report

    return report.main(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bench", description="Go vs Rust benchmark orchestration")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("env", help="capture the environment as JSON")
    s.add_argument("--mode", default=os.environ.get("MODE", "native"))
    s.add_argument("--out")
    s.set_defaults(fn=cmd_env)

    s = sub.add_parser("golden", help="regenerate spec/golden.json")
    s.add_argument("--check", action="store_true")
    s.set_defaults(fn=cmd_golden)

    s = sub.add_parser("datasets", help="generate + verify datasets needed by a profile")
    _add_common(s)
    s.add_argument("--all-profiles", action="store_true")
    s.add_argument("--name", action="append", help="explicit dataset path(s)")
    s.add_argument("--update-manifest", action="store_true")
    s.add_argument("--fast", action="store_true", help="skip re-hashing files already in the manifest")
    s.set_defaults(fn=cmd_datasets)

    s = sub.add_parser("validate", help="cross-language correctness validation")
    _add_common(s)
    s.add_argument("--skip-datasets", action="store_true")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("run", help="run benchmarks")
    _add_common(s)
    s.add_argument("--run-id")
    s.add_argument("--mode", default=os.environ.get("MODE", "native"), choices=["native", "container"])
    s.add_argument("--rounds", type=int)
    s.add_argument("--resume", action="store_true")
    s.add_argument("--no-alloc-pass", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("plan", help="estimate runtime of a profile")
    _add_common(s)
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("list", help="list selected workloads")
    _add_common(s)
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("docs", help="generate docs/BENCHMARKS.md")
    s.set_defaults(fn=cmd_docs)

    for name, fn in (("process", cmd_process), ("charts", cmd_charts), ("report", cmd_report)):
        s = sub.add_parser(name, help=f"{name} results")
        s.add_argument("--run-id", action="append", help="raw run id(s); default: latest per category")
        s.add_argument("--mode", default=os.environ.get("MODE", "native"))
        s.set_defaults(fn=fn)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec = specmod.load()
    try:
        return int(args.fn(args, spec) or 0)
    except KeyboardInterrupt:
        log("interrupted", level="warn")
        return 130
    except KeyError as e:
        die(f"unknown key: {e}")
        return 2
