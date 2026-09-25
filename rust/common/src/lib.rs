//! Shared harness for the Rust benchmark programs. Every item here has a Go
//! twin in go/internal/{harness,common}; spec/golden.json keeps them honest.

pub mod alloc;
pub mod digest;
pub mod harness;
pub mod hist;
pub mod params;
pub mod procfs;
pub mod rng;

pub use digest::{Digest, Unordered, fnv1a64, hex};
pub use harness::{Instance, Mode, Work, Workload, main};
pub use params::Params;
pub use rng::{SplitMix64, mix64};

use std::path::PathBuf;

/// The repository root (the directory holding bench.toml), found by walking up
/// from the crate directory. Used by tests to locate spec/ and fixtures.
pub fn repo_root() -> PathBuf {
    let mut dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    loop {
        if dir.join("bench.toml").exists() {
            return dir;
        }
        if !dir.pop() {
            panic!("bench.toml not found above {}", env!("CARGO_MANIFEST_DIR"));
        }
    }
}

/// Parse spec/golden.json.
pub fn load_golden() -> serde_json::Value {
    let path = repo_root().join("spec").join("golden.json");
    let text =
        std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    serde_json::from_str(&text).expect("parse golden.json")
}

/// Parse a 16-digit hex u64 from the golden file.
pub fn golden_hex(v: &serde_json::Value) -> u64 {
    u64::from_str_radix(v.as_str().expect("hex string"), 16).expect("hex u64")
}
