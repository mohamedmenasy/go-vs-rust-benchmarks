"""Cross-language correctness validation.

Every harness workload is run once per language in `validate` mode (no
warmup, a single timed iteration) with the exact parameters of the selected
profile. The Go and Rust results must agree on the checksum, the unit and
amount of work, and the input size; otherwise the comparison is INVALID and
`make benchmark` refuses to run. Special categories plug in extra checks
(e.g. HTTP response parity) via `EXTRA_VALIDATORS`.
"""

from __future__ import annotations

from typing import Callable

from . import orchestrate
from .spec import Spec
from .util import log

EXTRA_VALIDATORS: dict[str, Callable[[Spec, str], bool]] = {}


def compare(results: dict[str, dict]) -> list[str]:
    """Return a list of human-readable mismatches between language results."""
    problems: list[str] = []
    langs = sorted(results)
    ref_lang = langs[0]
    ref = results[ref_lang]
    for lang in langs[1:]:
        other = results[lang]
        if ref.get("checksum") != other.get("checksum"):
            problems.append(f"checksum {ref_lang}={ref.get('checksum')} {lang}={other.get('checksum')}")
        rw, ow = ref.get("work", {}), other.get("work", {})
        for key in ("unit", "per_run", "input_bytes"):
            if rw.get(key) != ow.get(key):
                problems.append(f"work.{key} {ref_lang}={rw.get(key)} {lang}={ow.get(key)}")
    return problems


def validate(spec: Spec, profile: str, categories: list[str] | None = None, ids: list[str] | None = None) -> bool:
    items = spec.select(profile, categories, ids, kinds={"harness"})
    ok_all = True
    rows = []
    for w, size in items:
        results: dict[str, dict] = {}
        errors: list[str] = []
        for lang in w.langs:
            rec = orchestrate.run_one(spec, w, size, lang, {}, command="validate", pin=False, keep_series=False)
            if not rec.get("ok"):
                errors.append(f"{lang}: {rec.get('error')}")
            else:
                results[lang] = rec["result"]
        problems = errors or compare(results)
        status = "OK" if not problems else "INVALID"
        ok_all &= not problems
        checks = " ".join(f"{lang}={results[lang].get('checksum', '?')[:16]}" for lang in sorted(results))
        rows.append((status, w.id, size.label, checks, "; ".join(problems)))
        log(f"{status:<8} {w.id:<32} {size.label:<10} {checks} {'; '.join(problems)}", level="info" if not problems else "error")
    for cat, fn in EXTRA_VALIDATORS.items():
        if categories and cat not in categories:
            continue
        if not fn(spec, profile):
            ok_all = False
    log(f"validation {'PASSED' if ok_all else 'FAILED'}: {sum(1 for r in rows if r[0] == 'OK')}/{len(rows)} workload-sizes agree")
    return ok_all
