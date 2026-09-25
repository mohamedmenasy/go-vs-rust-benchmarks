//! Allocation / memory workloads (METHODOLOGY.md §13.2), mirror of go/memory.
//! Allocation and deallocation are part of the timed work: Rust frees inside
//! `run` (drop), Go's GC reclaims garbage during later iterations.

// Individually boxed objects in a Vec (mirroring Go's []*obj) are the point
// of the boxed and churn workloads.
#![allow(clippy::vec_box)]

mod churn;
mod objects;
mod trees;

use bench_common::{Mode, Workload};

/// A 64-byte record, identical to Go's `obj`.
#[derive(Clone, Copy, Default)]
pub struct Obj {
    pub a: u64,
    pub b: u64,
    pub c: u64,
    pub d: u64,
    pub e: u64,
    pub f: u64,
    pub g: u64,
    pub h: u64,
}

pub const OBJ_SIZE: usize = 64;
const _: () = assert!(std::mem::size_of::<Obj>() == OBJ_SIZE);

impl Obj {
    #[inline]
    pub fn filled(x: u64) -> Obj {
        Obj {
            a: x,
            b: x.wrapping_add(1),
            c: x.wrapping_add(2),
            d: x.wrapping_add(3),
            e: x.wrapping_add(4),
            f: x.wrapping_add(5),
            g: x.wrapping_add(6),
            h: x.wrapping_add(7),
        }
    }
}

/// Return freed memory to the OS where the allocator supports it (the Rust
/// counterpart of Go's runtime.GC() + debug.FreeOSMemory() in teardown).
pub fn release() {
    #[cfg(not(feature = "mimalloc"))]
    // SAFETY: malloc_trim only inspects glibc's own heap metadata.
    unsafe {
        libc::malloc_trim(0);
    }
}

fn main() {
    bench_common::main(
        "memory",
        &[
            Workload { name: "bytes", mode: Mode::Iter, setup: objects::setup_bytes },
            Workload { name: "objects-boxed", mode: Mode::Iter, setup: objects::setup_boxed },
            Workload { name: "objects-inline", mode: Mode::Iter, setup: objects::setup_inline },
            Workload { name: "binarytrees", mode: Mode::Iter, setup: trees::setup },
            Workload { name: "churn", mode: Mode::Iter, setup: churn::setup },
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

    pub fn run_twice(inst: &mut Box<dyn Instance>) -> u64 {
        let r = inst.run();
        assert_eq!(inst.run(), r, "non-deterministic run digest");
        r
    }

    pub fn golden_memory() -> bench_common::serde_json::Value {
        bench_common::load_golden()["memory"].clone()
    }
}
