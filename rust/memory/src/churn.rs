//! Live-set churn (mirror of go/memory/churn.go): a live set of `bytes`
//! worth of boxed objects stays reachable while each run replaces
//! `replace_pct`% as many randomly chosen slots with fresh objects. The
//! assignment frees the replaced object immediately.

use bench_common::serde_json::{Value, json};
use bench_common::{Instance, Params, SplitMix64, Work};

use crate::{OBJ_SIZE, Obj, release};

struct Churn {
    n: usize,
    k: usize,
    seed: u64,
    live: Vec<Box<Obj>>,
}

impl Instance for Churn {
    fn run(&mut self) -> u64 {
        let mut r = SplitMix64::new(self.seed);
        let n = self.n as u64;
        let mut acc = 0u64;
        for _ in 0..self.k {
            let i = r.below(n);
            let o = Box::new(Obj::filled(i));
            acc = acc.wrapping_add(o.a ^ o.h);
            self.live[i as usize] = o;
        }
        acc
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        self.live.iter().fold(0u64, |acc, o| acc.wrapping_add(o.a ^ o.h))
    }
    fn has_teardown(&self) -> bool {
        true
    }
    fn teardown(&mut self) {
        self.live = Vec::new();
        release();
    }
    fn extra(&mut self) -> Option<Value> {
        Some(json!({"live_objects": self.n, "replacements": self.k, "live_payload_bytes": self.n * OBJ_SIZE}))
    }
}

pub fn setup(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("bytes", 100 << 20) as usize / OBJ_SIZE;
    let k = p.int("replace_pct", 100) as usize * n / 100;
    let live: Vec<Box<Obj>> = (0..n).map(|i| Box::new(Obj::filled(i as u64))).collect();
    Ok((
        Box::new(Churn { n, k, seed: p.int("seed", 7) as u64, live }),
        Work { unit: "allocations", per_run: k as f64, input_bytes: 0 },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{golden_memory, params, run_twice};
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let c = &golden_memory()["churn"];
        let bytes = (c["n"].as_u64().unwrap() as usize * OBJ_SIZE).to_string();
        let (mut inst, _) = setup(&params(&[
            ("bytes", bytes),
            ("replace_pct", "100".to_string()),
            ("seed", c["seed"].to_string()),
        ]))
        .unwrap();
        assert_eq!(run_twice(&mut inst), golden_hex(&c["run"]));
        assert_eq!(inst.check(), golden_hex(&c["check"]));
    }
}
