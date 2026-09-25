//! Naive doubly-recursive Fibonacci: a pure function-call benchmark.

use std::hint::black_box;

use bench_common::{Instance, Params, Work};

pub fn fib(n: u64) -> u64 {
    if n < 2 { n } else { fib(n - 1) + fib(n - 2) }
}

fn fib_iter(n: u64) -> u64 {
    let (mut a, mut b) = (0u64, 1u64);
    for _ in 0..n {
        (a, b) = (b, a + b);
    }
    a
}

struct Fib {
    n: u64,
}

impl Instance for Fib {
    fn run(&mut self) -> u64 {
        fib(black_box(self.n))
    }
}

pub fn setup(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("n", 35) as u64;
    let calls = 2 * fib_iter(n + 1) - 1; // calls made by fib(n)
    Ok((Box::new(Fib { n }), Work { unit: "calls", per_run: calls as f64, input_bytes: 0 }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::golden_cpu;

    #[test]
    fn matches_golden() {
        for c in golden_cpu()["fib"].as_array().unwrap() {
            assert_eq!(fib(c["n"].as_u64().unwrap()), c["value"].as_u64().unwrap());
        }
    }
}
