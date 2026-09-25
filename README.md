# Go vs Rust benchmarks

A reproducible benchmark suite comparing **Go** and **Rust** implementations of
the same work across CPU, memory, JSON, HTTP, concurrency, file I/O, strings,
collections, startup time, binary size and build time.

The goal is **not** to crown a winner. It is to measure, under controlled and
documented conditions, where each language's implementation is faster or
slower, uses more or less memory or CPU, and why. Every comparison:

- does the same logical work in both languages, **proven** by result digests
  that must match;
- reads byte-identical inputs, pinned by SHA-256;
- runs interleaved on the same pinned CPU cores, with production compiler
  settings;
- is repeated in independent processes and reported with confidence
  intervals.

See [METHODOLOGY.md](METHODOLOGY.md) for the rules,
[docs/BENCHMARKS.md](docs/BENCHMARKS.md) for every benchmark's exact command
and parameters, and [REPORT.md](REPORT.md) for results.

## Quick start

```bash
git clone https://github.com/mohamedmenasy/go-vs-rust-benchmarks
cd go-vs-rust-benchmarks
make setup        # tools (hyperfine, wrk, wrk2, nginx, ...), pinned Go/Rust toolchains, Python venv
make benchmark    # build -> datasets -> validate -> run every category -> process -> charts
make report       # refresh processed tables, charts and REPORT.md
```

`PROFILE=quick` finishes in minutes and is meant for smoke tests only; its
results are marked "insufficient rounds". `PROFILE=standard` is the default.
`PROFILE=full` is intended for dedicated bare-metal hosts. `make plan` prints
an estimated runtime.

Individual categories:

```bash
make benchmark-cpu benchmark-memory benchmark-json benchmark-http benchmark-concurrency \
     benchmark-io benchmark-strings benchmark-collections benchmark-startup \
     benchmark-binsize benchmark-compile
```

Other useful targets: `make validate` (Go and Rust must agree on every
result), `make test` (unit tests and golden values in Go, Rust and Python),
`make env` (print the captured environment), `make docs`, `make lint`.

## Requirements

- Linux on x86-64. The reference results come from Ubuntu 24.04.
- The following are installed by `make setup`:
  - Go ≥ 1.21 to bootstrap. Go 1.27.1 is pinned by `go/go.mod` and
    `GOTOOLCHAIN`.
  - rustup. Rust 1.98.1 is pinned by `rust/rust-toolchain.toml`.
  - Python ≥ 3.11 with venv.
  - hyperfine, wrk, wrk2 (built from a pinned commit), nginx, sysstat and GNU
    time.
- At least 4 CPU cores and about 16 GB of RAM for the default core layout.
  Edit `[cores]` in `bench.toml` for other machine shapes.

## Layout

```text
bench.toml            single source of truth: workloads, sizes per profile, rounds, timing, CPU pinning
go/                   Go programs (one per category) + internal/{harness,common}
rust/                 Rust workspace (one crate per category) + common/ (same protocol)
scripts/bench         orchestrator entry point (scripts/benchctl/)
scripts/analysis/     raw -> processed tables, charts, report tables
spec/golden.json      golden values checked by all three test suites
datasets/             generated inputs (only manifest.json is tracked)
results/raw/<run-id>/ every raw measurement, environment.json, build.json
results/processed/    normalized CSV/JSON (latest run per category per mode)
charts/               generated charts
docker/               containerized benchmark image
docs/BENCHMARKS.md    generated benchmark catalog
```

## Native vs containerized runs

`make docker-build && make docker-benchmark` runs the whole suite inside one
image that contains both toolchains. Container results are stored with
`mode=container` and are **never** compared with native results. See
[docker/README.md](docker/README.md).

## Status

| Category | Status |
|---|---|
| Harness, orchestrator, statistics, datasets | done |
| CPU, memory, JSON, HTTP, concurrency, file I/O, strings, collections | implemented |
| Startup, binary size, compilation | planned |
