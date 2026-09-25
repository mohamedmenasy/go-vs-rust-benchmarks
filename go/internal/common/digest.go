package common

import "fmt"

// FNV-1a 64-bit parameters.
const (
	FNVOffset = 0xcbf29ce484222325
	FNVPrime  = 0x100000001b3
)

// Fnv1a64 hashes b with 64-bit FNV-1a.
func Fnv1a64(b []byte) uint64 { return Fnv1a64Update(FNVOffset, b) }

// Fnv1a64Update continues an FNV-1a hash.
func Fnv1a64Update(h uint64, b []byte) uint64 {
	for _, c := range b {
		h ^= uint64(c)
		h *= FNVPrime
	}
	return h
}

// Fnv1a64String hashes s with 64-bit FNV-1a without allocating.
func Fnv1a64String(s string) uint64 {
	h := uint64(FNVOffset)
	for i := 0; i < len(s); i++ {
		h ^= uint64(s[i])
		h *= FNVPrime
	}
	return h
}

// Digest is an order-dependent accumulator over 64-bit words.
type Digest struct{ h uint64 }

// NewDigest returns an empty digest.
func NewDigest() Digest { return Digest{h: FNVOffset} }

// Add folds x into the digest.
func (d *Digest) Add(x uint64) { d.h = Mix64(d.h ^ x) }

// AddF64 folds the IEEE-754 bits of f into the digest.
func (d *Digest) AddF64(f float64) { d.Add(F64Bits(f)) }

// AddString folds the FNV-1a hash of s and its length into the digest.
func (d *Digest) AddString(s string) {
	d.Add(Fnv1a64String(s))
	d.Add(uint64(len(s)))
}

// AddBytes folds the FNV-1a hash of b and its length into the digest.
func (d *Digest) AddBytes(b []byte) {
	d.Add(Fnv1a64(b))
	d.Add(uint64(len(b)))
}

// Sum returns the current digest value.
func (d *Digest) Sum() uint64 { return d.h }

// Unordered accumulates values independent of their order (for hash-map
// iteration and concurrent completion order).
type Unordered struct{ sum, n uint64 }

// Add folds x in, order-independently.
func (u *Unordered) Add(x uint64) {
	u.sum += Mix64(x)
	u.n++
}

// Sum returns the order-independent digest.
func (u *Unordered) Sum() uint64 { return Mix64(u.sum ^ Mix64(u.n)) }

// Hex formats a digest the way both harnesses print it.
func Hex(x uint64) string { return fmt.Sprintf("%016x", x) }
