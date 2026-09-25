//! Sieve of Eratosthenes over a byte-per-number array. The array is allocated
//! once in setup; clearing it is part of the timed work, allocation is not.

use bench_common::{Digest, Instance, Params, Work};

struct Sieve {
    n: usize,
    composite: Vec<bool>,
}

impl Instance for Sieve {
    // Index loops mirror go/cpu/sieve.go line for line (both keep bounds checks).
    #[allow(clippy::needless_range_loop)]
    fn run(&mut self) -> u64 {
        let c = &mut self.composite[..];
        c.fill(false);
        let n = self.n;
        let mut i = 2;
        while i * i <= n {
            if !c[i] {
                let mut j = i * i;
                while j <= n {
                    c[j] = true;
                    j += i;
                }
            }
            i += 1;
        }
        let (mut count, mut sum) = (0u64, 0u64);
        for i in 2..n + 1 {
            if !c[i] {
                count += 1;
                sum += i as u64;
            }
        }
        let mut d = Digest::new();
        d.add(count);
        d.add(sum);
        d.sum()
    }
}

pub fn setup(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("n", 10_000_000) as usize;
    Ok((
        Box::new(Sieve { n, composite: vec![false; n + 1] }),
        Work { unit: "numbers", per_run: n as f64, input_bytes: 0 },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{golden_cpu, params, run_once};
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        for c in golden_cpu()["sieve"].as_array().unwrap() {
            let (mut inst, _) = setup(&params(&[("n", c["n"].to_string())])).unwrap();
            assert_eq!(run_once(&mut inst).0, golden_hex(&c["digest"]), "n={}", c["n"]);
        }
    }
}
