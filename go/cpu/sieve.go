package main

import (
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// sieveW is the classic Sieve of Eratosthenes over a byte-per-number array.
// The array is allocated once in setup; clearing it is part of the timed work
// (as in any real sieve) but allocation and page faults are not.
type sieveW struct {
	n         int
	composite []bool
}

func (w *sieveW) Run() uint64 {
	c := w.composite
	clear(c)
	n := w.n
	for i := 2; i*i <= n; i++ {
		if !c[i] {
			for j := i * i; j <= n; j += i {
				c[j] = true
			}
		}
	}
	var count, sum uint64
	for i := 2; i <= n; i++ {
		if !c[i] {
			count++
			sum += uint64(i)
		}
	}
	d := common.NewDigest()
	d.Add(count)
	d.Add(sum)
	return d.Sum()
}

func setupSieve(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 10_000_000))
	return &sieveW{n: n, composite: make([]bool, n+1)}, harness.Work{Unit: "numbers", PerRun: float64(n)}, nil
}
