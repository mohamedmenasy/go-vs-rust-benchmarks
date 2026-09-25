package main

import (
	"math"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// matmul: C = A x B for n x n row-major float64 matrices, naive i-k-j loop
// order. Two formulations of the same arithmetic:
//
//   - matmul      (baseline): flat indexing c[i*n+j] += a[i*n+k] * b[k*n+j]
//   - matmul-rows (idiomatic): row sub-slices, letting each compiler drop
//     bounds checks (and, where it can, vectorize the inner loop)
//
// Each C element accumulates over k in the same order in both languages and
// neither compiler emits FMA at the baseline ISA, so results are bit-identical.
type matmul struct {
	n       int
	a, b, c []float64
	rows    bool
}

func (w *matmul) Prepare() { clear(w.c) }

func (w *matmul) Run() uint64 {
	if w.rows {
		matmulRows(w.n, w.a, w.b, w.c)
	} else {
		matmulFlat(w.n, w.a, w.b, w.c)
	}
	return math.Float64bits(w.c[0]) ^ math.Float64bits(w.c[w.n*w.n-1])
}

func (w *matmul) Check() uint64 {
	d := common.NewDigest()
	for _, x := range w.c {
		d.AddF64(x)
	}
	return d.Sum()
}

func matmulFlat(n int, a, b, c []float64) {
	for i := 0; i < n; i++ {
		for k := 0; k < n; k++ {
			aik := a[i*n+k]
			for j := 0; j < n; j++ {
				c[i*n+j] += aik * b[k*n+j]
			}
		}
	}
}

func matmulRows(n int, a, b, c []float64) {
	for i := 0; i < n; i++ {
		ci := c[i*n : i*n+n]
		ai := a[i*n : i*n+n]
		for k, aik := range ai {
			bk := b[k*n : k*n+n]
			bk = bk[:len(ci)] // bounds-check-elimination hint
			for j := range ci {
				ci[j] += aik * bk[j]
			}
		}
	}
}

func newMatmul(p harness.Params, rows bool) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 512))
	r := common.NewSplitMix64(uint64(p.Int("seed", 3)))
	a := make([]float64, n*n)
	b := make([]float64, n*n)
	for i := range a {
		a[i] = r.Float64()
	}
	for i := range b {
		b[i] = r.Float64()
	}
	flops := 2 * float64(n) * float64(n) * float64(n)
	return &matmul{n: n, a: a, b: b, c: make([]float64, n*n), rows: rows},
		harness.Work{Unit: "flops", PerRun: flops}, nil
}

func setupMatmul(p harness.Params) (harness.Instance, harness.Work, error) {
	return newMatmul(p, false)
}

func setupMatmulRows(p harness.Params) (harness.Instance, harness.Work, error) {
	return newMatmul(p, true)
}
