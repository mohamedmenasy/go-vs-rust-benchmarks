package main

import (
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// churn: a live set of `bytes` worth of boxed objects stays reachable (built
// in untimed setup) while each Run replaces `replace` randomly chosen slots
// with fresh objects. In Go the old objects become garbage and every GC
// cycle must mark the whole live set; in Rust the assignment frees the old
// object immediately. Object content depends only on the slot index, so the
// live set is identical after every Run and digests are reproducible.
type churnW struct {
	n, k int
	seed uint64
	live []*obj
}

func (w *churnW) Run() uint64 {
	r := common.NewSplitMix64(w.seed)
	n := uint64(w.n)
	var acc uint64
	for j := 0; j < w.k; j++ {
		i := r.Below(n)
		o := &obj{}
		fillObj(o, i)
		w.live[i] = o
		acc += o.a ^ o.h
	}
	return acc
}

func (w *churnW) Check() uint64 {
	var acc uint64
	for _, o := range w.live {
		acc += o.a ^ o.h
	}
	return acc
}

func (w *churnW) Teardown() {
	w.live = nil
	release()
}

func (w *churnW) Extra() map[string]any {
	return map[string]any{"live_objects": w.n, "replacements": w.k, "live_payload_bytes": w.n * objSize}
}

func setupChurn(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("bytes", 100<<20)) / objSize
	k := int(p.Int("replace_pct", 100)) * n / 100
	live := make([]*obj, n)
	for i := range live {
		o := &obj{}
		fillObj(o, uint64(i))
		live[i] = o
	}
	return &churnW{n: n, k: k, seed: uint64(p.Int("seed", 7)), live: live},
		harness.Work{Unit: "allocations", PerRun: float64(k)}, nil
}
