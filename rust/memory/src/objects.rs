//! `bytes`, `objects-boxed` and `objects-inline` (mirror of go/memory/objects.go).

use bench_common::serde_json::{Value, json};
use bench_common::{Instance, Params, SplitMix64, Work};

use crate::{OBJ_SIZE, Obj, release};

/// One contiguous buffer of `bytes`, filled with SplitMix64 words and folded.
/// The Vec is built without zero-initialisation (Go's make() zeroes by
/// language definition); it is freed at the end of `run`.
struct Bytes {
    words: usize,
    seed: u64,
}

impl Instance for Bytes {
    fn run(&mut self) -> u64 {
        let mut r = SplitMix64::new(self.seed);
        let buf: Vec<u64> = (0..self.words).map(|_| r.next_u64()).collect();
        let x = buf.iter().fold(0u64, |acc, &v| acc ^ v);
        drop(buf);
        x
    }
    fn has_teardown(&self) -> bool {
        true
    }
    fn teardown(&mut self) {
        release();
    }
    fn extra(&mut self) -> Option<Value> {
        Some(json!({"payload_bytes": self.words * 8}))
    }
}

pub fn setup_bytes(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("bytes", 100 << 20) as usize;
    Ok((
        Box::new(Bytes { words: n / 8, seed: p.int("seed", 5) as u64 }),
        Work { unit: "bytes", per_run: (n / 8 * 8) as f64, input_bytes: 0 },
    ))
}

/// bytes/64 objects, each individually heap-allocated (`Box`), kept in a Vec
/// of pointers, read back and dropped.
struct Boxed {
    n: usize,
    seed: u64,
}

impl Instance for Boxed {
    fn run(&mut self) -> u64 {
        let mut r = SplitMix64::new(self.seed);
        let mut ptrs: Vec<Box<Obj>> = Vec::with_capacity(self.n);
        for _ in 0..self.n {
            ptrs.push(Box::new(Obj::filled(r.next_u64())));
        }
        let acc = ptrs.iter().fold(0u64, |acc, o| acc.wrapping_add(o.a ^ o.h));
        drop(ptrs);
        acc
    }
    fn has_teardown(&self) -> bool {
        true
    }
    fn teardown(&mut self) {
        release();
    }
    fn extra(&mut self) -> Option<Value> {
        Some(json!({"objects": self.n, "object_bytes": OBJ_SIZE, "payload_bytes": self.n * OBJ_SIZE}))
    }
}

pub fn setup_boxed(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("bytes", 100 << 20) as usize / OBJ_SIZE;
    Ok((
        Box::new(Boxed { n, seed: p.int("seed", 6) as u64 }),
        Work { unit: "objects", per_run: n as f64, input_bytes: 0 },
    ))
}

/// The same objects stored by value in one Vec.
struct Inline {
    n: usize,
    seed: u64,
}

impl Instance for Inline {
    fn run(&mut self) -> u64 {
        let mut r = SplitMix64::new(self.seed);
        let objs: Vec<Obj> = (0..self.n).map(|_| Obj::filled(r.next_u64())).collect();
        let acc = objs.iter().fold(0u64, |acc, o| acc.wrapping_add(o.a ^ o.h));
        drop(objs);
        acc
    }
    fn has_teardown(&self) -> bool {
        true
    }
    fn teardown(&mut self) {
        release();
    }
    fn extra(&mut self) -> Option<Value> {
        Some(json!({"objects": self.n, "object_bytes": OBJ_SIZE, "payload_bytes": self.n * OBJ_SIZE}))
    }
}

pub fn setup_inline(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("bytes", 100 << 20) as usize / OBJ_SIZE;
    Ok((
        Box::new(Inline { n, seed: p.int("seed", 6) as u64 }),
        Work { unit: "objects", per_run: n as f64, input_bytes: 0 },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{golden_memory, params, run_twice};
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let g = golden_memory();
        let b = &g["bytes"];
        let words = b["words"].as_u64().unwrap();
        let (mut inst, _) =
            setup_bytes(&params(&[("bytes", (words * 8).to_string()), ("seed", b["seed"].to_string())]))
                .unwrap();
        assert_eq!(run_twice(&mut inst), golden_hex(&b["run"]));
        let o = &g["objects"];
        let bytes = (o["n"].as_u64().unwrap() as usize * OBJ_SIZE).to_string();
        for setup in [setup_boxed as bench_common::harness::SetupFn, setup_inline] {
            let (mut inst, _) =
                setup(&params(&[("bytes", bytes.clone()), ("seed", o["seed"].to_string())])).unwrap();
            assert_eq!(run_twice(&mut inst), golden_hex(&o["run"]));
        }
    }
}
