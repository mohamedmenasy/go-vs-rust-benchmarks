//! Harness self-test workloads: trivial, fully deterministic, used to test
//! the orchestrator, the statistics and CI end to end (mirror of go/selftest).

use bench_common::{Instance, Mode, Params, Work, Workload, mix64};

/// Mixes a counter `n` times: a pure, branch-free integer loop.
struct Spin {
    n: u64,
}

impl Instance for Spin {
    fn run(&mut self) -> u64 {
        let mut x = 0u64;
        for i in 0..self.n {
            x = mix64(x.wrapping_add(i));
        }
        x
    }
}

fn spin(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("n", 1_000_000) as u64;
    Ok((
        Box::new(Spin { n }),
        Work {
            unit: "mixes",
            per_run: n as f64,
            input_bytes: 0,
        },
    ))
}

fn opspin(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("n", 1000) as u64;
    Ok((
        Box::new(Spin { n }),
        Work {
            unit: "mixes",
            per_run: n as f64,
            input_bytes: 0,
        },
    ))
}

fn main() {
    bench_common::main(
        "selftest",
        &[
            Workload {
                name: "spin",
                mode: Mode::Iter,
                setup: spin,
            },
            Workload {
                name: "opspin",
                mode: Mode::Op,
                setup: opspin,
            },
        ],
    );
}
