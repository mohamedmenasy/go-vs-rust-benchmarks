//! Log-linear latency histogram ("loglin6"), identical to
//! go/internal/harness/hist.go: exact buckets below 64, then 64 linear
//! sub-buckets per power of two (relative bucket width <= 1/64).

use serde_json::{Value, json};

const SUB_BITS: u32 = 6;
const SUB: u64 = 1 << SUB_BITS;
pub const BUCKETS: usize = ((64 - SUB_BITS + 1) as u64 * SUB) as usize; // 3776

/// Bucket index of `v`.
#[inline]
pub fn bucket(v: u64) -> usize {
    if v < SUB {
        return v as usize;
    }
    let e = 63 - v.leading_zeros(); // >= SUB_BITS
    let m = (v >> (e - SUB_BITS)) & (SUB - 1);
    ((e - SUB_BITS + 1) as u64 * SUB + m) as usize
}

pub struct Histogram {
    counts: Vec<u64>,
    count: u64,
    sum: u64,
    min: u64,
    max: u64,
}

impl Default for Histogram {
    fn default() -> Self {
        Self::new()
    }
}

impl Histogram {
    pub fn new() -> Self {
        Histogram { counts: vec![0; BUCKETS], count: 0, sum: 0, min: 0, max: 0 }
    }

    #[inline]
    pub fn record(&mut self, v: u64) {
        self.counts[bucket(v)] += 1;
        if self.count == 0 || v < self.min {
            self.min = v;
        }
        if v > self.max {
            self.max = v;
        }
        self.count += 1;
        self.sum += v;
    }

    pub fn export(&self) -> Value {
        let buckets: Vec<[u64; 2]> =
            self.counts.iter().enumerate().filter(|(_, c)| **c != 0).map(|(i, c)| [i as u64, *c]).collect();
        json!({
            "scheme": "loglin6",
            "count": self.count,
            "sum_ns": self.sum,
            "min_ns": self.min,
            "max_ns": self.max,
            "buckets": buckets,
        })
    }

    pub fn count(&self) -> u64 {
        self.count
    }
}
