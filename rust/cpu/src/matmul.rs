//! C = A x B for n x n row-major f64 matrices, naive i-k-j loop order.
//!
//! * `matmul` (baseline): flat indexing `c[i*n+j] += a[i*n+k] * b[k*n+j]`
//! * `matmul-rows` (idiomatic): row sub-slices zipped with iterators, letting
//!   the compiler drop bounds checks and vectorize the inner loop.
//!
//! Each C element accumulates over k in the same order as go/cpu/matmul.go
//! and no FMA contraction happens at the baseline ISA: results are
//! bit-identical.

use bench_common::{Digest, Instance, Params, SplitMix64, Work};

struct Matmul {
    n: usize,
    a: Vec<f64>,
    b: Vec<f64>,
    c: Vec<f64>,
    rows: bool,
}

fn matmul_flat(n: usize, a: &[f64], b: &[f64], c: &mut [f64]) {
    for i in 0..n {
        for k in 0..n {
            let aik = a[i * n + k];
            for j in 0..n {
                c[i * n + j] += aik * b[k * n + j];
            }
        }
    }
}

fn matmul_rows(n: usize, a: &[f64], b: &[f64], c: &mut [f64]) {
    for (ci, ai) in c.chunks_exact_mut(n).zip(a.chunks_exact(n)) {
        for (&aik, bk) in ai.iter().zip(b.chunks_exact(n)) {
            for (cij, &bkj) in ci.iter_mut().zip(bk) {
                *cij += aik * bkj;
            }
        }
    }
}

impl Instance for Matmul {
    fn prepare(&mut self) {
        self.c.fill(0.0);
    }
    fn run(&mut self) -> u64 {
        if self.rows {
            matmul_rows(self.n, &self.a, &self.b, &mut self.c);
        } else {
            matmul_flat(self.n, &self.a, &self.b, &mut self.c);
        }
        self.c[0].to_bits() ^ self.c[self.n * self.n - 1].to_bits()
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        let mut d = Digest::new();
        for &x in &self.c {
            d.add_f64(x);
        }
        d.sum()
    }
}

fn setup(p: &Params, rows: bool) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("n", 512) as usize;
    let mut r = SplitMix64::new(p.int("seed", 3) as u64);
    let a: Vec<f64> = (0..n * n).map(|_| r.float64()).collect();
    let b: Vec<f64> = (0..n * n).map(|_| r.float64()).collect();
    let flops = 2.0 * (n as f64).powi(3);
    Ok((
        Box::new(Matmul { n, a, b, c: vec![0.0; n * n], rows }),
        Work { unit: "flops", per_run: flops, input_bytes: 0 },
    ))
}

pub fn setup_flat(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    setup(p, false)
}

pub fn setup_rows(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    setup(p, true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{golden_cpu, params, run_once};
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let c = &golden_cpu()["matmul"];
        for s in [setup_flat as bench_common::harness::SetupFn, setup_rows] {
            let (mut inst, _) =
                s(&params(&[("n", c["n"].to_string()), ("seed", c["seed"].to_string())])).unwrap();
            let (r, ch) = run_once(&mut inst);
            assert_eq!(r, golden_hex(&c["run"]));
            assert_eq!(ch, golden_hex(&c["check"]));
        }
    }
}
