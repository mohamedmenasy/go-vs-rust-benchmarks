//! Single-threaded CPU-bound workloads. Every workload mirrors go/cpu exactly:
//! same algorithm, same data layout, same operation order (floating-point
//! results must match bit for bit).

mod csvparse;
mod fib;
mod mandelbrot;
mod matmul;
mod nbody;
mod sha;
mod sieve;
mod sort;

use bench_common::{Mode, Workload};

fn main() {
    bench_common::main(
        "cpu",
        &[
            Workload { name: "fib", mode: Mode::Iter, setup: fib::setup },
            Workload { name: "sieve", mode: Mode::Iter, setup: sieve::setup },
            Workload { name: "sha256-lib", mode: Mode::Iter, setup: sha::setup_lib },
            Workload { name: "sha256-portable", mode: Mode::Iter, setup: sha::setup_portable },
            Workload { name: "sort-u64", mode: Mode::Iter, setup: sort::setup_u64 },
            Workload { name: "sort-stable", mode: Mode::Iter, setup: sort::setup_stable },
            Workload { name: "matmul", mode: Mode::Iter, setup: matmul::setup_flat },
            Workload { name: "matmul-rows", mode: Mode::Iter, setup: matmul::setup_rows },
            Workload { name: "nbody", mode: Mode::Iter, setup: nbody::setup },
            Workload { name: "mandelbrot", mode: Mode::Iter, setup: mandelbrot::setup },
            Workload { name: "csvparse", mode: Mode::Iter, setup: csvparse::setup },
        ],
    );
}

#[cfg(test)]
pub(crate) mod testutil {
    use bench_common::{Instance, Params};

    pub fn params(kv: &[(&str, String)]) -> Params {
        let mut p = Params::default();
        for (k, v) in kv {
            p.0.insert(k.to_string(), v.clone());
        }
        p
    }

    /// Drive an instance like the harness does; returns (run, check) digests.
    pub fn run_once(inst: &mut Box<dyn Instance>) -> (u64, u64) {
        inst.prepare();
        let r = inst.run();
        let c = if inst.has_check() { inst.check() } else { 0 };
        inst.prepare();
        assert_eq!(inst.run(), r, "non-deterministic run digest");
        (r, c)
    }

    pub fn golden_cpu() -> bench_common::serde_json::Value {
        bench_common::load_golden()["cpu"].clone()
    }
}
