//! Request logic shared by the Rust HTTP servers, mirroring go/internal/api:
//! same CPU work per request and byte-identical JSON responses.

use bench_common::mix64;
use serde::Serialize;

/// The "small CPU operation" performed per request.
pub const SCORE_ROUNDS: u32 = 1000;

/// Body returned with status 400 for a malformed id.
pub const ERROR_BODY: &[u8] = br#"{"error":"invalid id"}"#;

const TAGS: &[&str] = &["alpha", "beta", "gamma"];

/// Response object of `GET /users/{id}` (field order == JSON key order).
#[derive(Serialize)]
pub struct User {
    pub id: u64,
    pub name: String,
    pub email: String,
    pub score: u64,
    pub tags: &'static [&'static str],
    pub active: bool,
}

/// Mix the id SCORE_ROUNDS times (SplitMix64 finalizer).
#[inline]
pub fn score(id: u64) -> u64 {
    let mut x = id;
    for _ in 0..SCORE_ROUNDS {
        x = mix64(x.wrapping_add(0x9E37_79B9_7F4A_7C15));
    }
    x
}

/// Parse the path parameter and build the response object.
pub fn build_user(raw: &str) -> Option<User> {
    let id: u64 = raw.parse().ok()?;
    let name = format!("user-{id}");
    let email = format!("{name}@example.com");
    Some(User { id, name, email, score: score(id), tags: TAGS, active: id.is_multiple_of(2) })
}

/// Listen address from `--addr` or `$BENCH_ADDR`.
pub fn addr() -> String {
    let args: Vec<String> = std::env::args().collect();
    for (i, a) in args.iter().enumerate() {
        if a == "--addr" && i + 1 < args.len() {
            return args[i + 1].clone();
        }
        if let Some(v) = a.strip_prefix("--addr=") {
            return v.to_string();
        }
    }
    std::env::var("BENCH_ADDR").unwrap_or_else(|_| "127.0.0.1:18080".to_string())
}

/// The kernel's listen-backlog cap; Go's net.Listen uses exactly this value,
/// so the Rust servers request it explicitly too.
pub fn somaxconn() -> u32 {
    std::fs::read_to_string("/proc/sys/net/core/somaxconn")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(4096)
}

/// Worker threads: $BENCH_THREADS (set by the orchestrator to the number of
/// pinned cores), else the available parallelism.
pub fn threads() -> usize {
    std::env::var("BENCH_THREADS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or_else(|| std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1))
}
