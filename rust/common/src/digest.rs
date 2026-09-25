//! Result digests, identical to go/internal/common/digest.go.

use crate::rng::mix64;

pub const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;
pub const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;

/// 64-bit FNV-1a of `b`.
#[inline]
pub fn fnv1a64(b: &[u8]) -> u64 {
    fnv1a64_update(FNV_OFFSET, b)
}

/// Continue an FNV-1a hash.
#[inline]
pub fn fnv1a64_update(mut h: u64, b: &[u8]) -> u64 {
    for &c in b {
        h ^= c as u64;
        h = h.wrapping_mul(FNV_PRIME);
    }
    h
}

/// Order-dependent accumulator over 64-bit words.
#[derive(Clone, Copy, Debug)]
pub struct Digest {
    h: u64,
}

impl Default for Digest {
    fn default() -> Self {
        Self::new()
    }
}

impl Digest {
    pub fn new() -> Self {
        Digest { h: FNV_OFFSET }
    }
    #[inline]
    pub fn add(&mut self, x: u64) {
        self.h = mix64(self.h ^ x);
    }
    #[inline]
    pub fn add_f64(&mut self, f: f64) {
        self.add(f.to_bits());
    }
    #[inline]
    pub fn add_str(&mut self, s: &str) {
        self.add_bytes(s.as_bytes());
    }
    #[inline]
    pub fn add_bytes(&mut self, b: &[u8]) {
        self.add(fnv1a64(b));
        self.add(b.len() as u64);
    }
    pub fn sum(&self) -> u64 {
        self.h
    }
}

/// Order-independent accumulator (hash-map iteration, concurrent completion).
#[derive(Clone, Copy, Debug, Default)]
pub struct Unordered {
    sum: u64,
    n: u64,
}

impl Unordered {
    pub fn new() -> Self {
        Self::default()
    }
    #[inline]
    pub fn add(&mut self, x: u64) {
        self.sum = self.sum.wrapping_add(mix64(x));
        self.n += 1;
    }
    pub fn sum(&self) -> u64 {
        mix64(self.sum ^ mix64(self.n))
    }
}

/// Format a digest the way both harnesses print it.
pub fn hex(x: u64) -> String {
    format!("{x:016x}")
}
