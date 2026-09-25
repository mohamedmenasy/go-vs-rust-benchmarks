//! SplitMix64, bit-for-bit identical to go/internal/common/rng.go and
//! scripts/benchctl/refimpl.py (checked against spec/golden.json).

const GAMMA: u64 = 0x9E37_79B9_7F4A_7C15;
const MIX_C1: u64 = 0xBF58_476D_1CE4_E5B9;
const MIX_C2: u64 = 0x94D0_49BB_1331_11EB;

/// A tiny, fast, deterministic PRNG. Every in-process benchmark input is
/// generated with it so Go and Rust see identical data.
#[derive(Clone, Debug)]
pub struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    pub fn new(seed: u64) -> Self {
        SplitMix64 { state: seed }
    }

    /// Next 64-bit output.
    #[inline]
    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(GAMMA);
        mix64(self.state)
    }

    /// A value in [0, n) via Lemire's multiply-high reduction.
    #[inline]
    pub fn below(&mut self, n: u64) -> u64 {
        ((self.next_u64() as u128 * n as u128) >> 64) as u64
    }

    /// A value in [0, 1) with 53 bits of randomness.
    #[inline]
    pub fn float64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
    }
}

/// `n` bytes: the SplitMix64(seed) stream as little-endian 64-bit words,
/// truncated to `n` (identical to Go's common.RandomBytes).
pub fn random_bytes(seed: u64, n: usize) -> Vec<u8> {
    let mut out = vec![0u8; n.div_ceil(8) * 8];
    let mut r = SplitMix64::new(seed);
    let (words, _) = out.as_chunks_mut::<8>();
    for w in words {
        *w = r.next_u64().to_le_bytes();
    }
    out.truncate(n);
    out
}

/// The SplitMix64 output finalizer; a bijection on u64.
#[inline]
pub fn mix64(mut z: u64) -> u64 {
    z = (z ^ (z >> 30)).wrapping_mul(MIX_C1);
    z = (z ^ (z >> 27)).wrapping_mul(MIX_C2);
    z ^ (z >> 31)
}
