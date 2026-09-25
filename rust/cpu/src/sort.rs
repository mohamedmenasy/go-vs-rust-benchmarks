//! Standard-library sorting.
//! * `sort-u64`: unstable sort of random u64 (Rust ipnsort vs Go pdqsort).
//! * `sort-stable`: stable sort of 16-byte records by a key with duplicates
//!   (Rust driftsort vs Go insertion blocks + in-place SymMerge).

use bench_common::{Digest, Instance, Params, SplitMix64, Work};

struct SortU64 {
    orig: Vec<u64>,
    work: Vec<u64>,
}

impl Instance for SortU64 {
    fn prepare(&mut self) {
        self.work.copy_from_slice(&self.orig);
    }
    fn run(&mut self) -> u64 {
        self.work.sort_unstable();
        let n = self.work.len();
        self.work[0] ^ self.work[n / 2] ^ self.work[n - 1]
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        let mut d = Digest::new();
        for (i, &x) in self.work.iter().enumerate() {
            assert!(i == 0 || self.work[i - 1] <= x, "not sorted at {i}");
            d.add(x);
        }
        d.sum()
    }
}

pub fn setup_u64(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("n", 1_000_000) as usize;
    let mut r = SplitMix64::new(p.int("seed", 1) as u64);
    let orig: Vec<u64> = (0..n).map(|_| r.next_u64()).collect();
    Ok((
        Box::new(SortU64 { orig, work: vec![0; n] }),
        Work { unit: "elements", per_run: n as f64, input_bytes: 0 },
    ))
}

#[derive(Clone, Copy, Default)]
struct Rec {
    key: u64,
    val: u64,
}

struct SortStable {
    orig: Vec<Rec>,
    work: Vec<Rec>,
}

impl Instance for SortStable {
    fn prepare(&mut self) {
        self.work.copy_from_slice(&self.orig);
    }
    fn run(&mut self) -> u64 {
        self.work.sort_by_key(|r| r.key);
        let n = self.work.len();
        self.work[0].key ^ self.work[n / 2].val ^ self.work[n - 1].key
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        let mut d = Digest::new();
        for r in &self.work {
            d.add(r.key);
            d.add(r.val);
        }
        d.sum()
    }
}

pub fn setup_stable(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("n", 1_000_000) as usize;
    let mut r = SplitMix64::new(p.int("seed", 2) as u64);
    let kmax = (n / 4).max(1) as u64;
    let orig: Vec<Rec> = (0..n).map(|i| Rec { key: r.below(kmax), val: i as u64 }).collect();
    Ok((
        Box::new(SortStable { orig, work: vec![Rec::default(); n] }),
        Work { unit: "elements", per_run: n as f64, input_bytes: 0 },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{golden_cpu, params, run_once};
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let g = golden_cpu();
        for (name, setup) in
            [("sort_u64", setup_u64 as bench_common::harness::SetupFn), ("sort_stable", setup_stable)]
        {
            let c = &g[name];
            let (mut inst, _) =
                setup(&params(&[("n", c["n"].to_string()), ("seed", c["seed"].to_string())])).unwrap();
            let (r, ch) = run_once(&mut inst);
            assert_eq!(r, golden_hex(&c["run"]), "{name}");
            assert_eq!(ch, golden_hex(&c["check"]), "{name}");
        }
    }
}
