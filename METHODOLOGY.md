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

### 13.3 JSON (single core)

- **Operations:** typed decode and typed encode, plus a dynamic decode (Go
  `any` vs Rust `serde_json::Value`).
- **Inputs:** 1 KiB–1 MiB objects and arrays of 1k–100k objects.
- **Timing:** op mode for small payloads.
- **Correctness:** encoded output must be byte-identical to the input
  document.

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

### 13.6 File I/O (single core)

- **Workloads:** sequential raw reads and writes (1 MiB syscalls), buffered
  reads and writes (the buffer is set explicitly to 64 KiB in both languages,
  because the defaults differ: 4 KiB in Go and 8 KiB in Rust), and line
  parsing.
- **Cache state:** the primary mode uses a warm page cache, so it measures
  the language and runtime overhead rather than the disk. A cold-cache mode
  (`drop_caches` before every iteration) and an fsync variant are separate.

### 13.7 Strings, 13.8 Collections (single core)

- **Strings:** operations on the shared text corpus.
- **Collections:** 10k–1M (and 10M) elements.
- **Hashing:** the default hashers differ (Go's AES-based hash vs Rust's
  SipHash-1-3). This is part of the baseline. A faster Rust hasher is a
  tuned variant.
- **Digests:** hash-map results are digested independently of iteration
  order.

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
