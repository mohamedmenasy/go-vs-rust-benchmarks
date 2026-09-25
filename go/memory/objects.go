package main

import (
	"runtime"
	"runtime/debug"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// obj is a 64-byte, pointer-free record (the GC never scans its contents,
// but must trace every pointer that refers to it).
type obj struct{ a, b, c, d, e, f, g, h uint64 }

const objSize = 64

func fillObj(o *obj, x uint64) {
	o.a, o.b, o.c, o.d = x, x+1, x+2, x+3
	o.e, o.f, o.g, o.h = x+4, x+5, x+6, x+7
}

// release drops all garbage and asks the runtime to return memory to the OS,
// so the harness can observe how much RSS is actually given back.
func release() {
	runtime.GC()
	debug.FreeOSMemory()
}

// ---------------------------------------------------------------- bytes

// bytesW allocates one contiguous buffer of `bytes`, fills it with
// SplitMix64 words and folds it. Go's make() zeroes memory by language
// definition; the Rust version fills a fresh Vec without zeroing.
type bytesW struct {
	words int
	seed  uint64
}

func (w *bytesW) Run() uint64 {
	buf := make([]uint64, w.words)
	r := common.NewSplitMix64(w.seed)
	for i := range buf {
		buf[i] = r.Next()
	}
	var x uint64
	for _, v := range buf {
		x ^= v
	}
	return x
}

func (w *bytesW) Teardown() { release() }

func (w *bytesW) Extra() map[string]any {
	return map[string]any{"payload_bytes": w.words * 8}
}

func setupBytes(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("bytes", 100<<20))
	return &bytesW{words: n / 8, seed: uint64(p.Int("seed", 5))}, harness.Work{Unit: "bytes", PerRun: float64(n / 8 * 8)}, nil
}

// ---------------------------------------------------------------- objects-boxed

// boxedW allocates bytes/64 objects individually on the heap, keeps them in
// a slice of pointers, reads them back, and lets them die.
type boxedW struct {
	n    int
	seed uint64
}

func (w *boxedW) Run() uint64 {
	ptrs := make([]*obj, w.n)
	r := common.NewSplitMix64(w.seed)
	for i := range ptrs {
		o := &obj{}
		fillObj(o, r.Next())
		ptrs[i] = o
	}
	var acc uint64
	for _, o := range ptrs {
		acc += o.a ^ o.h
	}
	return acc
}

func (w *boxedW) Teardown() { release() }

func (w *boxedW) Extra() map[string]any {
	return map[string]any{"objects": w.n, "object_bytes": objSize, "payload_bytes": w.n * objSize}
}

func setupBoxed(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("bytes", 100<<20)) / objSize
	return &boxedW{n: n, seed: uint64(p.Int("seed", 6))}, harness.Work{Unit: "objects", PerRun: float64(n)}, nil
}

// ---------------------------------------------------------------- objects-inline

// inlineW is the same data as boxedW stored by value in one slice.
type inlineW struct {
	n    int
	seed uint64
}

func (w *inlineW) Run() uint64 {
	objs := make([]obj, w.n)
	r := common.NewSplitMix64(w.seed)
	for i := range objs {
		fillObj(&objs[i], r.Next())
	}
	var acc uint64
	for i := range objs {
		acc += objs[i].a ^ objs[i].h
	}
	return acc
}

func (w *inlineW) Teardown() { release() }

func (w *inlineW) Extra() map[string]any {
	return map[string]any{"objects": w.n, "object_bytes": objSize, "payload_bytes": w.n * objSize}
}

func setupInline(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("bytes", 100<<20)) / objSize
	return &inlineW{n: n, seed: uint64(p.Int("seed", 6))}, harness.Work{Unit: "objects", PerRun: float64(n)}, nil
}
