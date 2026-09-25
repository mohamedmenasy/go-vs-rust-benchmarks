//! The benchmark-binary protocol, identical to go/internal/harness/harness.go.
//!
//! ```text
//! <bin> list
//! <bin> run      <workload> [--param k=v]... [--warmup-iters N] [--warmup-min-ms N]
//!                           [--iters N] [--min-ms N] [--max-iters N] [--max-ms N] [--batch-min-ms N]
//! <bin> validate <workload> [--param k=v]...
//! ```
//!
//! Setup, prepare, check and teardown are never timed. Only `run` is timed,
//! with the monotonic clock. One JSON document is printed on stdout; phase
//! markers on stderr let the orchestrator align its RSS sampler with the
//! measured window. METHODOLOGY.md ("Measurement protocol") is normative.

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::process;
use std::time::Instant;

use serde_json::{Map, Value, json};

use crate::alloc;
use crate::digest::hex;
use crate::hist::Histogram;
use crate::params::Params;
use crate::procfs;

pub const SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    /// One `run` call is one timed iteration (a whole workload pass).
    Iter,
    /// One `run` call is one short operation, timed individually into a
    /// histogram and grouped into batches for samples.
    Op,
}

impl Mode {
    fn as_str(self) -> &'static str {
        match self {
            Mode::Iter => "iter",
            Mode::Op => "op",
        }
    }
}

/// A prepared workload. `run` performs the timed work and returns a digest of
/// its result; every call must return the same digest.
pub trait Instance {
    fn run(&mut self) -> u64;
    /// Untimed reset before each iteration (e.g. re-copying unsorted data).
    fn prepare(&mut self) {}
    /// Whether `check` is implemented.
    fn has_check(&self) -> bool {
        false
    }
    /// Untimed, expensive digest of the post-run state; called after the
    /// first and last run and both values must agree.
    fn check(&mut self) -> u64 {
        0
    }
    /// Untimed release of resources after measurement.
    fn teardown(&mut self) {}
    /// Whether `teardown` is implemented (the harness then samples RSS again).
    fn has_teardown(&self) -> bool {
        false
    }
    /// Workload-specific metrics.
    fn extra(&mut self) -> Option<Value> {
        None
    }
}

/// How much logical work one `run` call performs.
pub struct Work {
    pub unit: &'static str,
    pub per_run: f64,
    pub input_bytes: u64,
}

pub type SetupFn = fn(&Params) -> Result<(Box<dyn Instance>, Work), String>;

pub struct Workload {
    pub name: &'static str,
    pub mode: Mode,
    pub setup: SetupFn,
}

struct Options {
    warmup_iters: u64,
    warmup_min_ms: u64,
    iters: u64,
    min_ms: u64,
    max_iters: u64,
    max_ms: u64,
    batch_min_ms: u64,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            warmup_iters: 2,
            warmup_min_ms: 500,
            iters: 5,
            min_ms: 1000,
            max_iters: 100_000,
            max_ms: 600_000,
            batch_min_ms: 10,
        }
    }
}

/// Run the protocol for a binary exposing `workloads`. Never returns.
pub fn main(bin: &str, workloads: &[Workload]) -> ! {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        usage(bin, workloads);
    }
    match args[1].as_str() {
        "list" => {
            let names: Vec<Value> =
                workloads.iter().map(|w| json!({"name": w.name, "mode": w.mode.as_str()})).collect();
            emit(&json!({"bin": bin, "lang": "rust", "workloads": names}));
            process::exit(0);
        }
        cmd @ ("run" | "validate") => {
            if args.len() < 3 {
                usage(bin, workloads);
            }
            let name = &args[2];
            let Some(wl) = workloads.iter().find(|w| w.name == name) else {
                fail(&format!("unknown workload {name:?} for {bin}"));
            };
            let (params, mut o) = parse_flags(&args[3..]);
            if cmd == "validate" {
                o.warmup_iters = 0;
                o.warmup_min_ms = 0;
                o.iters = 1;
                o.min_ms = 0;
            }
            let outcome = catch_unwind(AssertUnwindSafe(|| execute(bin, wl, &params, &o)));
            match outcome {
                Ok(Ok(v)) => {
                    emit(&v);
                    process::exit(0);
                }
                Ok(Err(e)) => fail(&e),
                Err(p) => {
                    let msg = p
                        .downcast_ref::<String>()
                        .cloned()
                        .or_else(|| p.downcast_ref::<&str>().map(|s| s.to_string()))
                        .unwrap_or_else(|| "unknown panic".to_string());
                    fail(&format!("panic: {msg}"));
                }
            }
        }
        _ => usage(bin, workloads),
    }
}

fn usage(bin: &str, workloads: &[Workload]) -> ! {
    let names: Vec<&str> = workloads.iter().map(|w| w.name).collect();
    eprintln!(
        "usage: {bin} list | run <workload> [flags] | validate <workload> [flags]\nworkloads: {}",
        names.join(" ")
    );
    process::exit(2);
}

fn parse_flags(args: &[String]) -> (Params, Options) {
    let mut params = Params::default();
    let mut o = Options::default();
    let mut i = 0;
    while i < args.len() {
        let (flag, inline) = match args[i].split_once('=') {
            Some((f, v)) if f.starts_with("--") => (f.to_string(), Some(v.to_string())),
            _ => (args[i].clone(), None),
        };
        let mut value = || -> String {
            if let Some(v) = &inline {
                return v.clone();
            }
            i += 1;
            args.get(i).cloned().unwrap_or_else(|| fail(&format!("flag {flag} needs a value")))
        };
        let num = |s: String| -> u64 {
            s.parse().unwrap_or_else(|_| fail(&format!("flag {flag}: bad number {s:?}")))
        };
        match flag.trim_start_matches('-') {
            "param" => {
                let kv = value();
                let Some((k, v)) = kv.split_once('=') else {
                    fail(&format!("want key=value, got {kv:?}"));
                };
                if k.is_empty() {
                    fail(&format!("want key=value, got {kv:?}"));
                }
                params.0.insert(k.to_string(), v.to_string());
            }
            "warmup-iters" => o.warmup_iters = num(value()),
            "warmup-min-ms" => o.warmup_min_ms = num(value()),
            "iters" => o.iters = num(value()),
            "min-ms" => o.min_ms = num(value()),
            "max-iters" => o.max_iters = num(value()),
            "max-ms" => o.max_ms = num(value()),
            "batch-min-ms" => o.batch_min_ms = num(value()),
            other => fail(&format!("unknown flag {other:?}")),
        }
        i += 1;
    }
    (params, o)
}

fn emit(v: &Value) {
    println!("{}", serde_json::to_string(v).expect("serialize result"));
}

fn fail(msg: &str) -> ! {
    emit(&json!({"schema": SCHEMA_VERSION, "lang": "rust", "error": msg}));
    process::exit(1);
}

fn phase(name: &str) {
    eprintln!("@@phase {name}");
}

#[derive(Default)]
struct DigestState {
    have: bool,
    digest: u64,
}

impl DigestState {
    #[inline]
    fn observe(&mut self, x: u64) -> Result<(), String> {
        if !self.have {
            self.have = true;
            self.digest = x;
            return Ok(());
        }
        if x != self.digest {
            return Err(format!("non-deterministic result digest: {x:016x} != {:016x}", self.digest));
        }
        Ok(())
    }
}

struct Snap {
    ru: procfs::Rusage,
    al: alloc::Snapshot,
}

fn snapshot() -> Snap {
    Snap { ru: procfs::rusage(), al: alloc::snapshot() }
}

fn build_info() -> Value {
    json!({
        "rustc_version": env!("BENCH_RUSTC_VERSION"),
        "profile": env!("BENCH_BUILD_PROFILE"),
        "opt_level": env!("BENCH_BUILD_OPT_LEVEL"),
        "debug": env!("BENCH_BUILD_DEBUG"),
        "target": env!("BENCH_BUILD_TARGET"),
        "target_features": env!("BENCH_TARGET_FEATURES"),
        "allocator": alloc::allocator_name(),
        "alloc_stats": alloc::counting_enabled(),
    })
}

fn execute(bin: &str, wl: &Workload, params: &Params, o: &Options) -> Result<Value, String> {
    let (mut inst, work) = (wl.setup)(params)?;
    let (rss_setup, hwm_setup) = procfs::mem_status();

    let has_check = inst.has_check();
    let mut ds = DigestState::default();
    let mut check_first: Option<u64> = None;
    let mut warm: Vec<u64> = Vec::new();
    // Pre-sized so harness bookkeeping does not allocate inside the measured window.
    let mut samples: Vec<u64> = Vec::with_capacity(4096);
    let mut ops_per_sample: u64 = 1;
    let mut hist: Option<Histogram> = None;
    let max_phase = o.max_ms as u128 * 1_000_000;
    let warmup_min = o.warmup_min_ms * 1_000_000;
    let min_ns = o.min_ms * 1_000_000;

    let snap0;
    let snap1;
    match wl.mode {
        Mode::Iter => {
            let mut one = |inst: &mut Box<dyn Instance>| -> Result<u64, String> {
                inst.prepare();
                let t0 = Instant::now();
                let d = inst.run();
                let dt = t0.elapsed().as_nanos() as u64;
                ds.observe(d)?;
                if has_check && check_first.is_none() {
                    check_first = Some(inst.check());
                }
                Ok(dt)
            };
            let mut sum = 0u64;
            let start = Instant::now();
            let mut i = 0u64;
            while (i < o.warmup_iters || sum < warmup_min)
                && i < o.max_iters
                && start.elapsed().as_nanos() < max_phase
            {
                let dt = one(&mut inst)?;
                warm.push(dt);
                sum += dt;
                i += 1;
            }
            phase("measure_start");
            snap0 = snapshot();
            alloc::reset_peak();
            let (mut sum, start, mut i) = (0u64, Instant::now(), 0u64);
            while (i < o.iters || sum < min_ns) && i < o.max_iters && start.elapsed().as_nanos() < max_phase {
                let dt = one(&mut inst)?;
                samples.push(dt);
                sum += dt;
                i += 1;
            }
            snap1 = snapshot();
            phase("measure_end");
        }
        Mode::Op => {
            let mut batch =
                |inst: &mut Box<dyn Instance>, n: u64, h: Option<&mut Histogram>| -> Result<u64, String> {
                    let mut s = 0u64;
                    let mut h = h;
                    for _ in 0..n {
                        let t0 = Instant::now();
                        let d = inst.run();
                        let dt = t0.elapsed().as_nanos() as u64;
                        ds.observe(d)?;
                        if has_check && check_first.is_none() {
                            check_first = Some(inst.check());
                        }
                        s += dt;
                        if let Some(h) = h.as_deref_mut() {
                            h.record(dt);
                        }
                    }
                    Ok(s)
                };
            // Calibrate the batch size so one batch lasts about batch_min_ms.
            let (mut cal_ns, mut cal_ops) = (0u64, 0u64);
            let cal_start = Instant::now();
            while cal_ops == 0 || cal_start.elapsed().as_nanos() < 20_000_000 {
                cal_ns += batch(&mut inst, 1, None)?;
                cal_ops += 1;
            }
            let per_op = (cal_ns / cal_ops).max(1);
            ops_per_sample = (o.batch_min_ms * 1_000_000 / per_op).max(1);
            if o.iters == 1 && o.min_ms == 0 {
                ops_per_sample = 1; // validate mode: a single op suffices
            }
            let (mut sum, start, mut i) = (0u64, Instant::now(), 0u64);
            while (i < o.warmup_iters || sum < warmup_min)
                && i < o.max_iters
                && start.elapsed().as_nanos() < max_phase
            {
                let dt = batch(&mut inst, ops_per_sample, None)?;
                warm.push(dt);
                sum += dt;
                i += 1;
            }
            let mut h = Histogram::new();
            phase("measure_start");
            snap0 = snapshot();
            alloc::reset_peak();
            let (mut sum, start, mut i) = (0u64, Instant::now(), 0u64);
            while (i < o.iters || sum < min_ns) && i < o.max_iters && start.elapsed().as_nanos() < max_phase {
                let dt = batch(&mut inst, ops_per_sample, Some(&mut h))?;
                samples.push(dt);
                sum += dt;
                i += 1;
            }
            snap1 = snapshot();
            phase("measure_end");
            hist = Some(h);
        }
    }

    let mut checksum = hex(ds.digest);
    if has_check {
        let last = inst.check();
        if let Some(first) = check_first
            && first != last
        {
            return Err(format!("post-run check digest changed: {last:016x} != {first:016x}"));
        }
        checksum = format!("{checksum}:{}", hex(last));
    }
    let (rss_end, hwm_end) = procfs::mem_status();
    let extra = inst.extra().unwrap_or(Value::Null);
    let mut rss = Map::new();
    rss.insert("after_setup".into(), json!(rss_setup));
    rss.insert("hwm_after_setup".into(), json!(hwm_setup));
    rss.insert("end".into(), json!(rss_end));
    rss.insert("hwm_end".into(), json!(hwm_end));
    if inst.has_teardown() {
        inst.teardown();
        rss.insert("after_teardown".into(), json!(procfs::mem_status().0));
    }
    let mut runtime = alloc::delta_json(&snap0.al, &snap1.al);
    if let Value::Object(m) = &mut runtime {
        m.insert("threads_end".into(), json!(procfs::thread_count()));
    }

    let mut res = json!({
        "schema": SCHEMA_VERSION,
        "lang": "rust",
        "bin": bin,
        "workload": wl.name,
        "mode": wl.mode.as_str(),
        "params": params.0,
        "work": {"unit": work.unit, "per_run": work.per_run, "input_bytes": work.input_bytes},
        "checksum": checksum,
        "warmup_ns": warm,
        "samples_ns": samples,
        "ops_per_sample": ops_per_sample,
        "rss_kb": Value::Object(rss),
        "rusage_measure": snap0.ru.delta_json(&snap1.ru),
        "runtime": runtime,
        "extra": extra,
        "build": build_info(),
    });
    if let Some(h) = hist {
        res["histogram"] = h.export();
    }
    Ok(res)
}
