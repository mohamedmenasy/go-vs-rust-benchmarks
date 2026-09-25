package main

import (
	"cmp"
	"fmt"
	"slices"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// sort-u64: the standard library's unstable sort of random uint64s
// (Go: pattern-defeating quicksort; Rust: ipnsort). Copying the unsorted
// input back before each iteration is untimed.
type sortU64 struct{ orig, work []uint64 }

func (w *sortU64) Prepare() { copy(w.work, w.orig) }

func (w *sortU64) Run() uint64 {
	slices.Sort(w.work)
	n := len(w.work)
	return w.work[0] ^ w.work[n/2] ^ w.work[n-1]
}

func (w *sortU64) Check() uint64 {
	d := common.NewDigest()
	for i, x := range w.work {
		if i > 0 && w.work[i-1] > x {
			panic(fmt.Sprintf("not sorted at %d", i))
		}
		d.Add(x)
	}
	return d.Sum()
}

func setupSortU64(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	r := common.NewSplitMix64(uint64(p.Int("seed", 1)))
	orig := make([]uint64, n)
	for i := range orig {
		orig[i] = r.Next()
	}
	return &sortU64{orig: orig, work: make([]uint64, n)}, harness.Work{Unit: "elements", PerRun: float64(n)}, nil
}

// sort-stable: stable sort of 16-byte records by a key with many duplicates
// (Go: insertion-sort blocks + in-place SymMerge; Rust: driftsort with an
// auxiliary buffer). Stability makes the output unique.
type rec struct{ key, val uint64 }

type sortStable struct{ orig, work []rec }

func (w *sortStable) Prepare() { copy(w.work, w.orig) }

func (w *sortStable) Run() uint64 {
	slices.SortStableFunc(w.work, func(a, b rec) int { return cmp.Compare(a.key, b.key) })
	n := len(w.work)
	return w.work[0].key ^ w.work[n/2].val ^ w.work[n-1].key
}

func (w *sortStable) Check() uint64 {
	d := common.NewDigest()
	for _, r := range w.work {
		d.Add(r.key)
		d.Add(r.val)
	}
	return d.Sum()
}

func setupSortStable(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	r := common.NewSplitMix64(uint64(p.Int("seed", 2)))
	kmax := uint64(max(n/4, 1))
	orig := make([]rec, n)
	for i := range orig {
		orig[i] = rec{key: r.Below(kmax), val: uint64(i)}
	}
	return &sortStable{orig: orig, work: make([]rec, n)}, harness.Work{Unit: "elements", PerRun: float64(n)}, nil
}
