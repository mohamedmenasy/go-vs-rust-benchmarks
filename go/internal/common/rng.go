// Package common holds primitives that must behave bit-for-bit identically to
// their Rust (rust/common) and Python (scripts/benchctl/refimpl.py)
// counterparts: the SplitMix64 PRNG and the digest functions used to prove
// that both implementations performed the same work. spec/golden.json pins the
// expected outputs and is checked by the test suites of all three languages.
package common

import (
	"encoding/binary"
	"math/bits"
)

// Constants of the SplitMix64 generator (Steele, Lea & Flood 2014).
const (
	gamma = 0x9E3779B97F4A7C15
	mixC1 = 0xBF58476D1CE4E5B9
	mixC2 = 0x94D049BB133111EB
)

// SplitMix64 is a tiny, fast, deterministic PRNG. Every benchmark input that
// is generated in-process uses it so Go and Rust see identical data.
type SplitMix64 struct{ state uint64 }

// NewSplitMix64 returns a generator seeded with seed.
func NewSplitMix64(seed uint64) *SplitMix64 { return &SplitMix64{state: seed} }

// Next returns the next 64-bit output.
func (s *SplitMix64) Next() uint64 {
	s.state += gamma
	return Mix64(s.state)
}

// Below returns a value in [0, n) using Lemire's multiply-high reduction.
func (s *SplitMix64) Below(n uint64) uint64 {
	hi, _ := bits.Mul64(s.Next(), n)
	return hi
}

// Float64 returns a value in [0, 1) with 53 bits of randomness.
func (s *SplitMix64) Float64() float64 {
	return float64(s.Next()>>11) * (1.0 / (1 << 53))
}

// RandomBytes returns n bytes: the SplitMix64(seed) stream as little-endian
// 64-bit words, truncated to n (identical to Rust's rng::random_bytes).
func RandomBytes(seed uint64, n int) []byte {
	out := make([]byte, (n+7)&^7)
	r := NewSplitMix64(seed)
	for i := 0; i < len(out); i += 8 {
		binary.LittleEndian.PutUint64(out[i:], r.Next())
	}
	return out[:n]
}

// Mix64 is the SplitMix64 output finalizer. It is a bijection on uint64.
func Mix64(z uint64) uint64 {
	z = (z ^ (z >> 30)) * mixC1
	z = (z ^ (z >> 27)) * mixC2
	return z ^ (z >> 31)
}
