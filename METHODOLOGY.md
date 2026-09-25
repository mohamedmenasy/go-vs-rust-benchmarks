# Methodology

This document is the normative description of how the Go-vs-Rust suite
measures things. If the code and this document disagree, that is a bug.

## 1. Purpose and non-goals

The suite's purpose is to **measure, under controlled and documented
conditions, where Go and Rust implementations of the same work differ** in
speed, latency, memory, CPU use, startup, binary size and build time. It also
explains *why* each difference probably occurs.

Non-goals:

- **Declaring a universal winner.** Every result is conditional on the
  workload, the input size, the library, the runtime configuration, the
  compiler version and the machine.
- **Benchmarking the fastest possible program in each language.** The
  primary comparison deliberately uses default, idiomatic tooling. Tuned
  configurations are measured separately and labelled as such (§2.5).
- **Producing numbers that transfer to other hardware.** The absolute numbers
  belong to the machine they were measured on. Ratios transfer better, but
  still not perfectly.

## 2. Fairness rules

A comparison is only reported when all of these hold.

### 2.1 Same logical work

- Both implementations use the same algorithm, the same data layout (values
  vs pointers, element types), and the same amount of work per iteration.
- Every timed operation returns a 64-bit **result digest**:
  - an order-dependent `Digest` for ordered outputs;
  - an order-independent `Unordered` digest for hash-map iteration and
    concurrent completion;
  - FNV-1a for byte outputs.
- Every workload also reports how much work it did (`work.unit`,
  `work.per_run`, `work.input_bytes`).
- A comparison is **INVALID** if the Go and Rust digests or work descriptors
  differ. This is checked before benchmarking (`make validate`) and again on
  every measured run during analysis.

### 2.2 Same inputs

- **Numeric inputs** (arrays to sort, keys to insert, matrices) are generated
  in-process with **SplitMix64** from fixed seeds. The generator is
  implemented identically in Go (`go/internal/common/rng.go`), Rust
  (`rust/common/src/rng.rs`) and Python (`scripts/benchctl/refimpl.py`).
  `spec/golden.json` pins its outputs, and all three test suites check them.
- **File inputs** (CSV logs, a text corpus, random binary data, JSON documents)
  are generated once by `scripts/benchctl/datasets.py` from the same
  SplitMix64 stream. The SHA-256 of every file is pinned in
  `datasets/manifest.json`. A machine that produces different bytes is refused.

### 2.3 Same conditions

- Go and Rust run on the same machine, the same CPU cores, the same OS and
  kernel, and with the same dataset files.
- The two languages are **interleaved in a seeded random order within every
  round**, so slow drift in machine conditions (thermal state, noisy
  neighbours, background daemons) affects both equally. It does not bias
  whichever language happened to run second.
- The orchestrator pins itself to core 0. Benchmarks are pinned with
  `taskset` to the cores listed in §6.
- Benchmark processes start with a **sanitized environment**: only `PATH`,
  locale, `HOME` and the variables a workload sets explicitly. No stray
  `GOGC`, `GODEBUG`, `MALLOC_*` or `RUSTFLAGS`.
- Logging is disabled in all benchmark programs.

### 2.4 Production builds

See §4. There are no debug builds, and both languages target the same
baseline ISA (x86-64-v1).

### 2.5 Tracks: defaults first, tuning labelled

| Track | Meaning | Examples |
|---|---|---|
| `baseline` (primary) | Same algorithm and data layout, standard or de-facto libraries, **default** runtime, allocator, hasher and build settings | `encoding/json` vs `serde_json`; Go map vs `std::collections::HashMap` (SipHash) |
| `idiomatic` | How an experienced developer would naturally write it in each language, where that differs from the baseline | Rust `BufRead::lines()` vs Go `Scanner.Text()` |
| `tuned` | Non-default settings | Rust fat LTO, mimalloc, a faster hasher; Go `GOGC`/`GOMEMLIMIT`; optimized JSON libraries |

Tracks are never mixed within one comparison. The headline tables in
REPORT.md use `baseline` only.

### 2.6 Language vs library vs runtime

Many differences come from libraries, not from the languages themselves.
Examples:

- Go's `crypto/sha256` is hand-written assembly, while `sha2` is Rust code
  using intrinsics.
- The regex engines are different.
- The default hash functions are different.

Such results are labelled as **ecosystem results**. Where it is feasible, a
second variant runs an identical hand-written algorithm in both languages so
that the compilers can be compared directly (for example `sha256-portable`).

## 3. Environment and toolchains

| Item | Pinned by | Version |
|---|---|---|
| Go | `go/go.mod` (`go 1.27.1`) + `GOTOOLCHAIN=go1.27.1` | 1.27.1 |
| Rust | `rust/rust-toolchain.toml` | 1.98.1 (LLVM 22) |
| Rust crates | `rust/Cargo.lock`, `--locked` | see lockfile |
| Go modules | `go.sum` (baseline programs use only the standard library) | — |
| wrk2 | `scripts/build_wrk2.sh` | commit `44a94c1` |
| Python analysis | `scripts/requirements.txt` | numpy 2.4.6, pandas 3.0.6, matplotlib 3.11.2, scipy 1.17.1 |

Each result set records its environment in `results/raw/<run-id>/environment.json`, captured by `scripts/benchctl/envinfo.py`. The captured fields are:

- **Hardware:** CPU model, flags and cache sizes (`lscpu`), core count and affinity, RAM, virtualization.
- **OS and kernel:** OS, kernel version and command line.
- **Kernel settings:** CPU frequency governor and turbo state (when exposed), transparent hugepages, ASLR, `somaxconn`, local port range, TCP reuse, file-descriptor limits, cgroup limits.
- **Machine state:** load average and `/proc/stat` counters, including steal time.
- **Toolchains and build settings:** `go version`, `go env`, `rustc -vV`, `cargo -V`, build flags.
- **Tools:** perf availability and event sources; the versions of hyperfine, wrk, wrk2, nginx and GNU time; Python package versions; Docker version.
- **Source:** git commit and dirty state.

`results/raw/<run-id>/build.json` records each binary's size, SHA-256, ELF
`.comment` (compiler and linker stamps) and dynamic dependencies (`ldd`).
Every result also embeds the build information the binary reports about itself.

## 4. Build configuration

| | Go | Rust |
|---|---|---|
| Command | `CGO_ENABLED=0 GOAMD64=v1 go build -trimpath -buildvcs=false` | `cargo build --release --locked` |
| Optimization | the gc compiler's default (always optimizing) | `opt-level=3`, `codegen-units=16`, `lto=false` (thin-local), `panic=unwind`, `debug=false`, `strip` = Cargo default (`"debuginfo"`) |
| Target ISA | x86-64-v1 (`GOAMD64=v1`, the default) | x86-64 baseline (no `target-cpu`) |
| Linking | static, pure Go (`CGO_ENABLED=0`) | dynamic against glibc; linker recorded per run |
| Other flavours | — | `allocstats` (`--features alloc-stats`, allocation pass only); `tuned` (`--profile release-tuned`: fat LTO, `codegen-units=1`, `panic=abort`); `mimalloc` (`--features mimalloc`) |

The stock Rust release profile is written out explicitly in `rust/Cargo.toml`,
so a future Cargo change to the defaults cannot silently change the baseline.
`CGO_ENABLED=0` makes Go binaries static and independent of libc. This matches
common Go container deployments. The binary-size category also measures the
`CGO_ENABLED=1` default for the HTTP server.

## 5. Runtime configuration

- **Worker threads** equal the number of pinned cores, set explicitly with
  `GOMAXPROCS=N` for Go and `TOKIO_WORKER_THREADS=N` (or the Actix worker
  count) for Rust. `BENCH_THREADS=N` is set for any hand-rolled thread pool.
  Both runtimes would detect the affinity mask anyway; setting the values
  explicitly makes them visible in the raw data.
- **Go GC:** default (`GOGC=100`, no memory limit) in the baseline. The memory
  category's sensitivity track varies `GOGC` and `GOMEMLIMIT`.
- **Rust allocator:** the system allocator (glibc malloc) in the baseline.
  mimalloc is a tuned variant.
- **Rust's lack of a GC is not assumed to be an advantage.** GC cost is
  measured, not presumed: GC cycles, pause times and the GC share of CPU from
  `runtime/metrics`, alongside allocation counts, peak RSS and RSS
  after release for both languages.

## 6. CPU pinning

Configured in `bench.toml` under `[cores]`. For the 4-core reference machine:

| Category | Cores | Rationale |
|---|---|---|
| orchestrator | 0 | kept off the benchmark cores |
| CPU, JSON, strings, collections, file I/O, startup | 3 | single-threaded workloads compare code generation and runtime overhead on one core |
| memory | 2–3 (`GOMAXPROCS=2`) | Go's concurrent GC has a core to use. Wall time **and** total CPU time are both reported, so offloading GC work to another core is visible rather than hidden. A 1-core variant runs in the full profile. |
| concurrency | 1–3 | three workers per runtime |
| HTTP | server 2–3, load generator 0–1 | server and load generator must not compete for cores |
| compilation | 0–3 | both compilers parallelize across all cores |

## 7. Measurement protocol

### 7.1 The benchmark-binary contract

Every Go and Rust benchmark program implements the same command-line protocol
(`go/internal/harness`, `rust/common/src/harness.rs`):

```text
<bin> run <workload> --param k=v ... --warmup-iters W --warmup-min-ms T --iters N --min-ms M
```

| Phase | Timed? | What happens |
|---|---|---|
| setup | no | parse parameters, load input files, generate in-process data |
| prepare (per iteration) | no | reset mutable state, e.g. re-copy the unsorted array |
| **run** | **yes** | the workload; returns the result digest |
| check (first and last iteration) | no | expensive digest of the post-run state (e.g. hashing a sorted array); both must match |
| teardown | no | release memory; RSS is sampled again afterwards |

Only `run` is timed, with the monotonic clock. Go uses `time.Since` against a
fixed base, which is one `CLOCK_MONOTONIC` vDSO read, like Rust's
`Instant::now()`. `time.Now()` also reads the wall clock, so it is deliberately
not used. Every `run` must return the same digest; a non-deterministic
workload fails the run. Rust passes inputs and outputs through
`std::hint::black_box` where the optimizer could otherwise remove work; in Go,
consuming the result digest serves the same purpose.

### 7.2 Warmup

Each process first runs at least `warmup_iters` iterations **and** at least
`warmup_min_ms` of timed work. Warmup:

- faults in memory pages and warms the caches, the branch predictor and the
  page cache;
- lets Go's GC pacer reach steady state;
- triggers lazy initialization.

Warmup samples are kept in the raw data but excluded from statistics.

### 7.3 Measurement

After warmup, each process records at least `iters` iterations **and** at
least `min_ms` of timed work. Hard caps (`max_iters`, `max_ms`) bound runaway
workloads. Profile defaults:

| Profile | Rounds | Warmup | Measurement |
|---|---|---|---|
| quick | 3 | ≥1 iteration, ≥100 ms | ≥3 iterations, ≥300 ms |
| standard | 10 | ≥2 iterations, ≥500 ms | ≥5 iterations, ≥1 s |
| full | 20 | ≥3 iterations, ≥1 s | ≥10 iterations, ≥2 s |

Workloads may override these values in `bench.toml`. The effective values for
every benchmark are listed in `docs/BENCHMARKS.md`.

### 7.4 Per-operation timing (op mode)

Microsecond-scale operations, such as decoding a 1 KB JSON document, are
timed **individually**. Each duration goes into a log-linear histogram
(`loglin6`: exact below 64 ns, then 64 linear sub-buckets per power of two,
so relative bucket width is at most 1.6%). The histogram is implemented
identically in both languages. A short calibration sizes batches to about
10 ms. Each batch's summed op time is one sample for throughput statistics,
and the histograms give the per-operation latency percentiles.

### 7.5 Rounds and interleaving

A *round* runs every selected (workload, size) once per language, each in a
**fresh process**. Go and Rust are shuffled within the round with a seeded
PRNG. The outer loop is over rounds, so a transient disturbance hits one
round of many benchmarks rather than every round of one benchmark. The
process is the unit of replication: ASLR, heap layout and GC timing differ
between processes, and the between-process spread is what the confidence
intervals capture.

### 7.6 Allocation profiling pass

Rust has no always-on allocation counters. Counting every `malloc` with atomics
would slow the timed runs, so the Rust allocation profile comes from a
**separate pass**. That pass uses the `allocstats` build: the same code
wrapped in a counting global allocator, which counts a `realloc` as a new
allocation plus a free, matching Go's `append` semantics. Its timings are
never used. Go's allocation counters (`runtime.MemStats`) are always
maintained by the runtime. They are read only outside the timed region.

In both languages the allocation counters cover the **measured window only**
(from the first measured iteration to the last). The harness keeps its own
bookkeeping out of that window:

- the samples buffer is pre-sized;
- phase markers are printed outside the window;
- the Go snapshot allocates its metrics buffer before reading `MemStats` at
  the start of the window, and after reading it at the end.

The counters therefore report the workload's own allocations, including
those of the untimed per-iteration `prepare` step. Workloads avoid
allocating in `prepare`; for example, the sort benchmarks re-copy into an
existing buffer. In a run with 0 allocations per operation (Fibonacci,
sorting u64s), both languages report exactly 0.

## 8. Metrics

| Metric | Definition | Source |
|---|---|---|
| time / op | median over samples of timed `run` duration (per op in op mode) | binary |
| throughput | `work.per_run` / median time (e.g. bytes/s, elements/s, requests/s) | derived |
| CPU time / op, CPU utilization | user+sys CPU during the measured phase ÷ ops, or ÷ measured wall time | `getrusage(RUSAGE_SELF)` in the binary |
| user vs system time | split of the above (important for I/O) | same |
| peak RSS | `VmHWM`, the kernel's exact per-process RSS high-water mark | `/proc/self/status` in the binary; `/proc/<pid>/status` for external processes |
| average RSS | time-weighted mean RSS during the measured window only (aligned with phase markers) | orchestrator sampler, 10–250 ms |
| RSS after release | RSS after teardown: is memory returned to the OS? | binary |
| allocations | objects and bytes allocated per op | Go: `MemStats.Mallocs`/`TotalAlloc`; Rust: `allocstats` pass |
| GC | cycles, total and max pause, GC CPU fraction (`/cpu/classes/gc/total` ÷ `/cpu/classes/total`) | Go `runtime.MemStats`, `runtime/metrics` |
| context switches, page faults | voluntary and involuntary switches, minor and major faults | `getrusage` |
| threads | maximum OS threads observed | sampler |
| steal | share of CPU time the hypervisor stole from the pinned cores during the run | `/proc/stat` |

**Why not `ru_maxrss` from `wait4`?** On Linux the RSS high-water mark
carries over across `exec()`. A child forked from the (large) Python
orchestrator therefore inherits the orchestrator's RSS, and small programs
appear to use about 90 MB. `ru_maxrss` is kept in the raw data as
`maxrss_kb_unreliable`, but peak RSS always comes from `VmHWM`.

## 9. Statistics

Implemented in `scripts/benchctl/stats.py`, with synthetic-data tests in
`scripts/tests/test_stats.py`.

- **Descriptive statistics** for every (workload, size, language): mean,
  median, min, max, standard deviation, coefficient of variation, p50, p95 and
  p99. They are computed over all measured samples, and separately over the
  per-process medians.
- **Comparison statistic:** the ratio *median(Rust) / median(Go)* of the
  per-process medians (below 1 means Rust took less time). The table also
  gives the absolute difference and the percentage difference.
- **Uncertainty:** a percentile bootstrap 95% confidence interval for the
  ratio. It uses 10,000 resamples, drawn independently per language, with a
  fixed seed.
- **Test:** a two-sided Mann-Whitney U test on the per-process medians.
- **Verdict rule.** A difference is called only when **all** of these hold:
  1. at least 5 process runs per language;
  2. the 95% CI of the ratio excludes 1.0;
  3. p < 0.05;
  4. |ratio − 1| > 2% (practical-equivalence band).

  Otherwise the verdict is "no measurable difference", or "insufficient
  rounds" (for example with the `quick` profile). Across 200 synthetic trials
  on identical distributions, the rule's false-positive rate is tested to stay
  ≤ 5%.
- **Never a single run.** The quick profile exists only to smoke-test the
  pipeline, and its results are marked "insufficient rounds".

## 10. Anomalies and exclusions

No raw data is ever deleted. A run is **flagged and excluded from headline
statistics** only for a documented, mechanical reason:

| Flag | Rule |
|---|---|
| `failed` | non-zero exit, timeout, crash, or malformed output |
| `steal` | hypervisor steal time above 5% on the run's pinned cores (§8) |
| `loadgen_saturated` (HTTP) | the load generator's cores were over 95% busy, so the measured throughput is a property of the load generator, not the server |

- **Statistical outliers are flagged, never dropped.** The report lists the
  number of excluded runs for every comparison.
- A **checksum or work mismatch** marks the whole comparison INVALID. It is
  never excluded silently.

## 11. Correctness validation

1. **Unit tests** in all three languages check the shared primitives
   (SplitMix64, digests, histogram buckets) and each workload's known answers
   against `spec/golden.json`. The Python reference implementation generates
   that file independently.
2. **`make validate`** runs every workload in `validate` mode (one untimed
   iteration) with the parameters of the selected profile, in both languages.
   It compares digests and work descriptors, plus category-specific checks
   such as HTTP response parity. `make benchmark` stops on any mismatch.
3. **Every measured run** carries its digest. `scripts/analysis/process.py`
   re-checks that all runs of a comparison agree.

## 12. Datasets

`scripts/benchctl/datasets.py` produces the families below. Sizes are powers
of two (MiB/GiB). The smaller files of each family are prefixes of the larger
ones.

| Family | Content | Used by |
|---|---|---|
| `bin/random-<size>.bin` | little-endian u64 words from SplitMix64 | file I/O, hashing |
| `csv/requests-<size>.csv` | `ts,user_id,endpoint,status,latency_ms,bytes` request log | CPU parsing, line parsing |
| `text/corpus-<size>.txt` | space- and newline-separated words, about 10% non-ASCII (Latin, Greek, Cyrillic, CJK, Arabic, Hebrew, Devanagari, emoji), with planted e-mails, dates, integers, decimals and keyword tokens | strings, word-frequency maps |
| `json/object-<size>.json`, `json/array-<n>.json` | API-response object; array of user objects | JSON |

Content constraints keep the programs' outputs byte-identical across
languages:

- **Unicode casing.** Characters with Unicode *SpecialCasing* rules (ß, İ,
  ligatures, iota-subscript Greek) are excluded. Rust's `to_uppercase`
  applies those rules and Go's `strings.ToUpper` does not.
- **JSON strings.** JSON contains no `<`, `>`, `&`, U+2028 or U+2029, because
  Go's `encoding/json` escapes them by default and `serde_json` does not.
- **JSON floats.** Floats always have a non-zero fractional part, because
  serde (ryu) prints `1.0` where Go prints `1`. They have at most 15
  significant digits and stay in a moderate range. `serde_json`'s default
  float parser is *best effort*: we observed a one-ULP error on a 17-digit
  value while building this suite. Go's parser is correctly rounded, so longer
  literals could make the two decode different values.
- **Regex classes.** Regex patterns use explicit ASCII classes (`[0-9]`,
  `[A-Za-z]`). Rust's `\d`, `\w` and `\b` are Unicode-aware; Go's are ASCII.

## 13. Category-specific methodology

Each category section states what is timed and which caveats apply. The exact
parameters live in `bench.toml` and `docs/BENCHMARKS.md`.

### 13.1 CPU (single core)

- **Workloads:**
  - recursive Fibonacci
  - Sieve of Eratosthenes
  - SHA-256, two variants: each language's standard or de-facto library, and
    an identical portable implementation
  - sorting: unstable u64 sort and stable record sort
  - naive i-k-j matrix multiplication
  - n-body
  - Mandelbrot
  - CSV parse-and-aggregate
- **Floating-point equality.** Results are compared bit for bit, which works
  because neither compiler contracts `a*b+c` into an FMA at the baseline ISA.
  If a future toolchain changes this, the workload documents a tolerance.
- **Floating-point constants.** Go evaluates constant expressions such as
  `4*math.Pi*math.Pi` exactly, with arbitrary precision, and rounds once.
  Rust and Python round after every IEEE operation. The two can differ in
  the last bit. The Go n-body code therefore derives its constants with
  run-time `float64` variables, so all three implementations start from
  identical bits. `spec/golden.json` checks the initial energy
  (−0.169075164) and the energy after 1,000 steps (−0.169087605) against
  the Python reference.
- **Python reference.** Every CPU workload also has an independent Python
  implementation (`scripts/benchctl/golden_workloads.py`), and the Go and
  Rust unit tests check their small-size digests against it.
- **SHA-256 backends on the reference host.** This CPU has AVX2 but no
  SHA-NI.
  - Go's `crypto/sha256` uses its AVX2 assembly path.
  - `sha2` 0.11 detects SHA-NI at run time and otherwise falls back to its
    portable ("soft") Rust implementation.
  - `sha256-lib` therefore compares Go assembly with portable Rust.
    `sha256-portable` compares the same portable algorithm in both
    languages.
- **Stable sort algorithms differ.** Go's `slices.SortStableFunc` uses
  insertion-sorted blocks and an in-place SymMerge: no allocation,
  O(n log² n). Rust's `sort_by_key` uses driftsort with an O(n) scratch
  buffer. The allocation columns show this.
- **Recursion.** For `fib`, LLVM may turn one of the two recursive calls into
  a loop. Go's compiler does not. The logical call tree is identical.

### 13.2 Memory (2 cores)

- **Workloads:** allocating and processing 100 MiB, 500 MiB and 1 GiB:
  - one contiguous buffer;
  - individually heap-allocated 64-byte objects;
  - the same objects stored inline in an array;
  - binary trees;
  - a *churn* workload, where a live set of size L is fully replaced by
    short-lived allocations (the steady-state GC case).
- **Reported:** time, CPU time, peak and average RSS, RSS after release,
  allocation counts and rates, and Go GC cycles, pauses and CPU share.
- **Sensitivity track:** Go `GOGC` set to 50, 100, 200, and off with a
  `GOMEMLIMIT`; Rust glibc malloc vs mimalloc.
- **What is timed.** Allocation, filling, reading and releasing are all
  inside `run`.
  - Rust frees at the end of `run` (`drop`).
  - Go's garbage is reclaimed by GC cycles that the next iterations trigger.
    Steady-state per-iteration time and the measured window's CPU time
    therefore include GC work, including background mark workers on the
    second core.
- **Identical logical allocations.** Go's `MemStats.Mallocs` and Rust's
  counting allocator report the *same* number of allocations per iteration.
  For example, `objects-boxed` 100 MiB makes 1,638,401 allocations in both:
  one per object plus the pointer slice. The differences come from how
  allocations are served and reclaimed, not from how many there are.
- **Zeroing.** Go's `make` zero-initializes by language definition; the Rust
  `bytes` and `objects-inline` workloads build their vectors without
  zeroing. For these sizes glibc uses `mmap`/`munmap` for every buffer, so
  Rust pays page faults on every iteration. Go reuses its heap after GC and
  pays for zeroing instead.
- **Three RSS readings:**
  1. `peak` (VmHWM over the process lifetime);
  2. `end`: the natural state right after the last iteration, including
     garbage Go has not yet collected;
  3. `after_teardown`: after an explicit release (`runtime.GC()` +
     `debug.FreeOSMemory()` in Go, `malloc_trim(0)` for glibc in Rust),
     which shows how much memory each runtime can give back to the OS.
- **`churn`.** Object contents depend only on the slot index, so the live set
  is identical after every iteration and digests are reproducible.
- **Single-core variants.** The `.1core` variants (full profile) pin
  `GOMAXPROCS=1`, so Go's GC competes with the mutator for the only core.

### 13.3 JSON (single core)

- **Operations:** typed decode and typed encode, plus a dynamic decode (Go
  `any` vs Rust `serde_json::Value`).
- **Inputs:** 1 KiB–1 MiB objects and arrays of 1k–100k objects.
- **Timing:** op mode for small payloads.
- **Correctness:** encoded output must be byte-identical to the input
  document.
- **Libraries.**
  - Go: `encoding/json` (the v1 API). **Go 1.27 enables the `jsonv2`
    experiment by default**, so this API runs on the new `encoding/json/v2`
    engine. The `json.*.go-legacyjson` variants rebuild Go with
    `GOEXPERIMENT=nojsonv2`, the previous implementation.
  - Rust: `serde` 1.0 + `serde_json` 1.0.151 with `#[derive]` types.
  - Optimized-library track (`json.*-fast`, tuned): Go
    `github.com/goccy/go-json` v0.10.6 vs Rust `sonic-rs` 0.5.10. Both are
    drop-in replacements for the standard APIs.
- **What is timed.** Each operation decodes (or encodes) one whole document,
  timed individually. A decoded value replaces the previous one, so Rust's
  drop and Go's garbage are part of the steady-state cost.
- **Correctness check** (untimed, first and last operation):
  - The typed decode is re-encoded and must reproduce the input file byte
    for byte. Every field is then digested; the Python reference produces
    the same digest.
  - The encode output must equal the input file.
  - The dynamic decode is digested order-independently, because Go maps
    iterate in random order while serde_json maps are sorted. Numbers are
    compared as float64, because Go's `any` decodes every number to
    `float64` while `serde_json::Value` keeps integers as integers.
- **Representations differ by design.**
  - Go's `any` produces `map[string]any` (a hash map) and `float64`
    numbers.
  - `serde_json::Value` uses a `BTreeMap` (sorted) and integer-preserving
    `Number`.

  These are each ecosystem's default dynamic representation, and the results
  are labelled as such.

### 13.4 HTTP

- **Endpoint:** `GET /users/{id}` parses the id, runs 1,000 SplitMix64 mixing
  rounds, builds a response struct, serializes it to JSON and returns it.
- **Stacks:** `net/http` vs Axum (baseline); Gin vs Actix Web (secondary).
- **Equal settings on both servers:**
  - `TCP_NODELAY` on (Go's default, set explicitly in Rust);
  - listen backlog = `somaxconn`;
  - HTTP/1.1 keep-alive;
  - no logging;
  - worker threads = pinned cores.
- **Response parity:** before any load test, both servers are sent identical
  requests. Status codes and bodies must match byte for byte, and header
  sizes are recorded.
- **Throughput:** closed-loop `wrk` sweeps at 1–10,000 connections, each
  with a fresh server, 10 s warmup and 30 s measurement.
- **Latency:** open-loop `wrk2` at fixed request rates (25–90% of the
  *slower* server's capacity, the same absolute rates for both).
  Closed-loop generators wait for each response before sending the next
  request. A server stall (for example a GC pause) therefore also stalls the
  generator and hides the stall from the latency data ("coordinated
  omission"). Tail-latency claims come only from the open-loop runs.
- **Sustained load:** 5-minute runs measured in consecutive 10 s windows.
- **Load-generator saturation:** its CPU use is sampled; saturated runs are
  flagged.
- **Implementations.**
  - Baseline pair: Go `net/http` (Go 1.22+ `ServeMux` patterns) vs Rust
    Axum 0.8.9 on hyper 1.11 and Tokio 1.53.
  - Secondary pair: Gin 1.12, which runs on `net/http`, vs Actix Web 4.15.
  - The shared request logic is `go/internal/api` and `rust/http-common`:
    parse the id as an unsigned 64-bit integer, run 1,000 SplitMix64
    finalizer rounds, build `{id,name,email,score,tags,active}`, and encode
    it with `encoding/json` or `serde_json`.
- **Server settings made equal explicitly:**
  - listen backlog = `somaxconn` (Go's default; Axum through
    `TcpSocket::listen`, Actix through `.backlog()`);
  - `TCP_NODELAY` (Go's default; Axum through `ListenerExt::tap_io`,
    Actix through `.tcp_nodelay(true)`);
  - worker threads = pinned cores (`GOMAXPROCS`, `TOKIO_WORKER_THREADS`,
    Actix `.workers()`).
- **Parity check (`make validate`).** 17 requests are sent to both servers:
  valid ids, 0, a leading zero, `u64::MAX`, overflow, negative, non-numeric,
  a decimal and a percent-encoded id.
  - Status codes and bodies must match byte for byte.
  - `net/http` and Axum also send the same response header size (128 bytes).
  - Gin's idiomatic `c.JSON` adds `; charset=utf-8` (143 vs 128 header
    bytes). This is recorded, not corrected.
  - **Known difference:** `/users/+5` returns 400 from Go and 200 from Rust,
    because Rust's `u64::from_str` accepts a leading `+` and Go's
    `strconv.ParseUint` does not. It is reported as informational. The
    benchmark's request stream never contains signed ids.
- **Load generation commands:**
  - `taskset -c <loadgen> wrk -t2 -c<C> -d<D>s --timeout 5s --latency -s scripts/wrk/report.lua`,
    or `wrk2 ... -R<rate>`.
  - Each thread cycles through `/users/1..10000` from a thread-specific
    offset, so both servers see the same request mix.
  - `report.lua` emits totals, per-type error counts (connect, read, write,
    non-2xx, timeout) and latency percentiles as JSON.
  - wrk runs one thread per load-generator core, capped at the number of
    connections.
- **Metrics.**
  - Server CPU, RSS and threads are sampled from `/proc` every 250 ms during
    the measured window. CPU is reported in cores busy. RSS is reported as the
    time-weighted average and the peak during the window, and as `VmHWM`
    over the server's whole life.
  - **Requests per CPU-second** = requests ÷ (server CPU cores busy ×
    window). It measures efficiency independently of how many cores were
    saturated.
  - In the latency tests both servers receive the *same* offered load, so
    their CPU use is directly comparable.
- **Capacity for the latency tests.** Latency-test rates are fractions of
  the **slower** server's median closed-loop throughput at 100 connections,
  from the same run. Runs flagged as load-generator-saturated are excluded
  from that capacity estimate.

### 13.5 Concurrency (3 cores)

- **Runtimes compared:** goroutines and channels vs Tokio tasks and
  channels.
- **Channel mapping:** Tokio's `mpsc` is used where one consumer suffices.
  Go channels are multi-producer/multi-consumer, so Rust uses
  `async-channel` where several consumers are needed.
- **Workloads:**
  - spawn/join
  - sleeping tasks (the wake-lateness distribution measures scheduler
    behaviour)
  - CPU work split across N tasks
  - ping-pong
  - producer/consumer topologies
  - fan-out/fan-in
  - concurrent HTTP client requests against a neutral nginx server
- **Task counts:** N = 10 … 100,000. HTTP client concurrency is capped at
  10,000 by the file-descriptor limit.
- **Symmetric structure.**
  - Go runs with `GOMAXPROCS=3`. The Rust side builds a multi-threaded Tokio
    runtime with 3 workers during untimed setup.
  - In both languages the coordinating logic of every workload runs inside a
    spawned goroutine or task: Go's `inTask`, Rust's
    `rt.block_on(tokio::spawn(f))`. It never runs on Rust's non-worker main
    thread, where every channel operation would be a cross-thread wake-up.
  - Entering the Tokio runtime from outside costs Rust roughly 20–50 µs per
    iteration on this VM, because a sleeping worker must be woken. A Go
    goroutine handoff stays on the same P.
  - `spawn-join` therefore repeats small batches `reps` times inside one task,
    so every iteration spawns about 100k tasks and measures in-runtime
    spawn/join cost.
- **Timers.** Tokio's timer wheel has 1 ms granularity; Go's timers are
  nanosecond-precision. The `sleep` workload reports wake-lateness
  percentiles for each run, and they differ partly for this reason.
- **Memory per task.** This is (peak RSS − RSS after setup) ÷ N:
  - goroutine stacks start at a few KiB and can grow;
  - a Tokio task is a heap-allocated future sized to its state.
- **HTTP client.** The server is nginx 1.24, with 2 workers on the nginx
  cores serving a static 130-byte JSON body over keep-alive. The clients run
  on the other two cores:
  - Go: `net/http` with `MaxIdleConnsPerHost = N`;
  - Rust: `reqwest` 0.13 without default features (plain HTTP/1.1 via hyper)
    with `pool_max_idle_per_host = N`.

  The validated result is total body bytes (requests × 130), and every
  request must succeed.

### 13.6 File I/O (single core)

- **Workloads:** sequential raw reads and writes (1 MiB syscalls), buffered
  reads and writes (the buffer is set explicitly to 64 KiB in both languages,
  because the defaults differ: 4 KiB in Go and 8 KiB in Rust), and line
  parsing.
- **Cache state:** the primary mode uses a warm page cache, so it measures
  the language and runtime overhead rather than the disk. A cold-cache mode
  (`drop_caches` before every iteration) and an fsync variant are separate.
- **What is timed.** `open`, all reads or writes, and `close`.
- **Content digest.** One byte per 4 KiB page, weighted by page index, plus
  the byte count, identical in Go, Rust and Python. It proves that the same
  bytes flowed through without turning the benchmark into a CPU-bound fold.
- **Writes.**
  - Output goes to `scratch/io/` on the same ext4 filesystem as the
    datasets.
  - The previous iteration's file is unlinked in the untimed `prepare`
    step, which discards its dirty pages without writeback.
  - Without fsync, writes measure the page cache, and background writeback
    and dirty-page throttling can add variance at 1 GiB.
  - `io.write-fsync` adds `fsync` before `close`; it mostly measures the
    (virtual) storage device.
- **Line parsing.**
  - Baseline: one reused line buffer (`Scanner.Bytes` vs `read_until`), a
    64 KiB buffer, and the same hand-written integer parser on the same two
    fields in both languages.
  - `io.lines-idiomatic` measures typical code instead: Go
    `Scanner.Text` + `strings.Split` + `strconv.Atoi`, vs Rust
    `BufRead::lines`, which allocates a `String` per line and validates
    UTF-8, + `split().collect()` + `parse`.
- **Cold cache.** In the cold-cache variants, the measured window's CPU time
  includes the kernel's page-cache eviction, which is charged to the
  process that writes `drop_caches`. Only their time columns are meaningful.

### 13.7 Strings, 13.8 Collections (single core)

- **Strings:** operations on the shared text corpus.
  - The corpus is read in untimed setup; Rust also validates UTF-8 there,
    once.
  - Token lists are *views* into the corpus in both languages: Go
    substrings, and in Rust `&str` into a leaked copy of the corpus. No
    token is copied.
  - `format` compares `fmt.Fprintf` into a `strings.Builder` with
    `write!`/`writeln!` into a `String`. Both format `%.2f` with correct
    rounding, and the outputs are byte-identical.
  - `regex` compares Go `regexp` (RE2-style) with Rust `regex` 1.13. Both
    are linear-time automata with leftmost-first semantics. Patterns use
    explicit ASCII classes. The digest covers match counts and the sum of
    match byte offsets, so the same matches must be found.
  - `upper` uses full Unicode case mapping in Rust and simple mapping in
    Go. The corpus contains no SpecialCasing characters, so the outputs are
    identical; Python's `str.upper` produces the same bytes.
- **Collections:** 10k–1M (and 10M) elements.
- **Hashing:** the default hashers differ (Go's AES-based hash vs Rust's
  SipHash-1-3). This is part of the baseline. A faster Rust hasher is a
  tuned variant.
- **Digests:** hash-map results are digested independently of iteration
  order.
- **Maps.** Both maps are Swiss tables: Go's built-in map since Go 1.24, and
  Rust's `std::collections::HashMap` (hashbrown). With identical table
  designs, the default *hash functions* are the main baseline difference:
  - Go: AES-NI hashing, seeded per map;
  - Rust: SipHash-1-3, seeded per `RandomState`, which resists hash
    flooding.

  The `*.foldhash` variants (tuned) give Rust foldhash 0.2. Go maps cannot
  take a custom hasher.
- **Queue.** Go has no standard-library deque. The baseline therefore uses
  the common slice idiom (`append` plus `q = q[1:]`) against Rust's
  `VecDeque` ring buffer.
- **Priority queue.** Go's `container/heap` works through `heap.Interface`
  (dynamic dispatch and boxing to `any`). Rust's `BinaryHeap<Reverse<u64>>`
  is monomorphized. This is each ecosystem's standard tool.
- **Sizes.** Workloads run at 10k, 100k and 1M elements (10M in the full
  profile). Inputs come from fixed-seed SplitMix64 streams and are
  generated in untimed setup.

### 13.9 Startup

- **CLI:** a tiny CLI is measured with `hyperfine -N` (no intermediate shell)
  in alternating rounds.
- **HTTP server:** the measure is time from `exec` to the first successful
  response.
- **Warm page cache:** binaries are in the page cache.
- **Reported:** mean, median, p95 and standard deviation.

### 13.10 Binary size

- **Builds measured:** default and stripped (`-ldflags="-s -w"` in Go,
  `strip=symbols` in Rust), plus the tuned (LTO) and static (`crt-static`)
  Rust variants.
- **Recorded:** GNU `strip` size, dynamic dependencies and the dependency
  footprint.

### 13.11 Compilation

- **Scenarios:** clean build, no-op rebuild, and a one-file change (a
  constant toggles in a leaf file).
- **Offline:** builds run with prefetched dependencies.
- **Asymmetries, documented:**
  - Rust ships a precompiled standard library, while `go clean -cache` makes
    Go rebuild its standard library.
  - Cargo's release profile is not incremental. The Rust dev profile and
    `cargo check` form a separate developer-iteration track.

## 14. Native vs containerized runs

- `MODE=native` and `MODE=container` results are stored and processed
  separately. `mode` is part of every grouping key.
- A native Go result is **never** compared with a containerized Rust result,
  or the reverse.
- In container mode, both languages run inside the same image (`docker/`),
  with host networking and the same CPU set.

## 15. Threats to validity

- **Shared cloud VM.** The reference results were measured on a 4-vCPU
  KVM/Firecracker guest. It has noisy neighbours, no hardware performance
  counters, no control over CPU frequency, and no SMT topology information.
  Mitigations:
  - steal-time flags;
  - interleaved rounds;
  - confidence intervals;
  - clear labelling;
  - a bare-metal preparation guide (§17).
- **Few cores.** The HTTP load generator and server share one machine with 2
  cores each, and saturation is flagged. Results at 5,000–10,000 connections
  are affected by this machine's file-descriptor and port limits.
- **Library effects.** See §2.6.
- **Compiler versions.** Results hold for Go 1.27.1 and Rust 1.98.1 only.
- **Page cache.** I/O results reflect the page cache, not the storage
  device.
- **Timer overhead.** In op mode each op includes two clock reads (about
  20–40 ns). This is negligible for operations over 1 µs, and op mode is
  used only for those.
- **The orchestrator's own activity.** It samples `/proc` and runs on core 0.
  The benchmark cores are 1–3.

## 16. Reporting rules

REPORT.md separates, for every category:

1. **Measured facts:** numbers with confidence intervals, conditions and
   sizes.
2. **Interpretation:** what the facts mean for a kind of workload.
3. **Possible explanation:** mechanisms such as GC, allocator, bounds checks,
   inlining, library implementation or scheduler design. These are labelled
   as hypotheses unless they were confirmed by a targeted experiment.

Claims are phrased conditionally. Write "in this benchmark, under this
configuration, the Rust implementation's median time was X% lower (95% CI
…)", never "Rust is faster".

## 17. Preparing a host for authoritative runs

For publishable numbers, run on dedicated bare metal:

- **CPU frequency:** set the governor to `performance`
  (`cpupower frequency-set -g performance`) and disable turbo/boost for
  stable clocks.
- **Isolate the benchmark cores:** `isolcpus=`/`nohz_full=` kernel
  parameters, or a cgroup cpuset. Update `[cores]` in `bench.toml` to match.
- **Quiet the machine:** stop background services, and keep THP and ASLR at
  their defaults (they are recorded).
- **Use the full profile:** `make benchmark PROFILE=full`, then check the
  `steal` and CV columns in `results/processed/`.
