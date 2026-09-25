// Command collections benchmarks the standard collections (mirror of
// rust/collections): slices vs Vec, built-in maps vs std HashMap (each with
// its default hash function), sets, FIFO queues, priority queues, sorting.
// Inputs come from SplitMix64 streams with fixed seeds.
package main

import (
	"cmp"
	"container/heap"
	"os"
	"slices"
	"strings"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

func main() {
	harness.Main("collections", []harness.Workload{
		{Name: "vec-push", Mode: harness.ModeIter, Setup: setupVecPush},
		{Name: "vec-random-read", Mode: harness.ModeIter, Setup: setupVecRead},
		{Name: "map-insert", Mode: harness.ModeIter, Setup: setupMapInsert},
		{Name: "map-lookup", Mode: harness.ModeIter, Setup: setupMapLookup},
		{Name: "map-string", Mode: harness.ModeIter, Setup: setupMapString},
		{Name: "set-ops", Mode: harness.ModeIter, Setup: setupSetOps},
		{Name: "queue", Mode: harness.ModeIter, Setup: setupQueue},
		{Name: "priority-queue", Mode: harness.ModeIter, Setup: setupPQ},
		{Name: "sort-structs", Mode: harness.ModeIter, Setup: setupSortStructs},
	})
}

func stream(seed uint64, n int) []uint64 {
	r := common.NewSplitMix64(seed)
	out := make([]uint64, n)
	for i := range out {
		out[i] = r.Next()
	}
	return out
}

func work(n int) harness.Work { return harness.Work{Unit: "elements", PerRun: float64(n)} }

// ---------------------------------------------------------------- vec-push

// vecPushW appends N values to a slice that starts empty (append's growth
// policy vs Vec's doubling), then sums them.
type vecPushW struct{ vals []uint64 }

func (w *vecPushW) Run() uint64 {
	var s []uint64
	for _, v := range w.vals {
		s = append(s, v)
	}
	var sum uint64
	for _, v := range s {
		sum += v
	}
	return sum ^ uint64(len(s))
}

func setupVecPush(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	return &vecPushW{vals: stream(11, n)}, work(n), nil
}

// ---------------------------------------------------------------- vec-random-read

// vecReadW reads N elements at precomputed random indices (lookup-heavy,
// cache-miss dominated for large N; bounds-checked in both languages).
type vecReadW struct {
	data []uint64
	idx  []uint32
}

func (w *vecReadW) Run() uint64 {
	var sum uint64
	for _, i := range w.idx {
		sum += w.data[i]
	}
	return sum
}

func setupVecRead(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	r := common.NewSplitMix64(13)
	idx := make([]uint32, n)
	for i := range idx {
		idx[i] = uint32(r.Below(uint64(n)))
	}
	return &vecReadW{data: stream(12, n), idx: idx}, work(n), nil
}

// ---------------------------------------------------------------- maps

func mapDigest(m map[uint64]uint64) uint64 {
	var u common.Unordered
	for k, v := range m {
		u.Add(common.Mix64(k) ^ v)
	}
	return u.Sum()
}

// mapInsertW inserts N random keys into a fresh map with no size hint.
type mapInsertW struct {
	keys []uint64
	m    map[uint64]uint64
}

func (w *mapInsertW) Run() uint64 {
	m := make(map[uint64]uint64)
	for i, k := range w.keys {
		m[k] = uint64(i)
	}
	w.m = m
	return uint64(len(m))
}

func (w *mapInsertW) Check() uint64 { return mapDigest(w.m) }

func setupMapInsert(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	return &mapInsertW{keys: stream(14, n)}, work(n), nil
}

// mapLookupW probes a prebuilt map N times, half hits and half misses.
type mapLookupW struct {
	m      map[uint64]uint64
	probes []uint64
}

func (w *mapLookupW) Run() uint64 {
	var hits, sum uint64
	for _, k := range w.probes {
		if v, ok := w.m[k]; ok {
			hits++
			sum += v
		}
	}
	return hits<<40 ^ sum
}

func setupMapLookup(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	keys := stream(14, n)
	m := make(map[uint64]uint64, n)
	for i, k := range keys {
		m[k] = uint64(i)
	}
	r := common.NewSplitMix64(15)
	probes := make([]uint64, n)
	for i := range probes {
		if i%2 == 0 {
			probes[i] = keys[r.Below(uint64(n))]
		} else {
			probes[i] = r.Next()
		}
	}
	return &mapLookupW{m: m, probes: probes}, work(n), nil
}

// mapStringW counts word frequencies of the first N corpus tokens in a
// string-keyed map (keys are views into the corpus in both languages).
type mapStringW struct {
	tokens []string
	m      map[string]uint64
}

func (w *mapStringW) Run() uint64 {
	m := make(map[string]uint64)
	for _, t := range w.tokens {
		m[t]++
	}
	w.m = m
	return uint64(len(m))
}

func (w *mapStringW) Check() uint64 {
	var u common.Unordered
	for k, v := range w.m {
		u.Add(common.Fnv1a64String(k) ^ common.Mix64(v))
	}
	return u.Sum()
}

func setupMapString(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	b, err := os.ReadFile(p.MustStr("input"))
	if err != nil {
		return nil, harness.Work{}, err
	}
	tokens := strings.Fields(string(b))
	if len(tokens) < n {
		n = len(tokens)
	}
	return &mapStringW{tokens: tokens[:n]}, work(n), nil
}

// ---------------------------------------------------------------- set-ops

// setOpsW builds two sets of N draws from a universe of 2N and counts their
// intersection (map[uint64]struct{} vs HashSet<u64>).
type setOpsW struct{ a, b []uint64 }

func (w *setOpsW) Run() uint64 {
	sa := make(map[uint64]struct{})
	for _, k := range w.a {
		sa[k] = struct{}{}
	}
	sb := make(map[uint64]struct{})
	for _, k := range w.b {
		sb[k] = struct{}{}
	}
	small, large := sa, sb
	if len(small) > len(large) {
		small, large = large, small
	}
	var inter uint64
	for k := range small {
		if _, ok := large[k]; ok {
			inter++
		}
	}
	return inter<<40 ^ uint64(len(sa))<<20 ^ uint64(len(sb))
}

func setupSetOps(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	draw := func(seed uint64) []uint64 {
		r := common.NewSplitMix64(seed)
		out := make([]uint64, n)
		for i := range out {
			out[i] = r.Below(uint64(2 * n))
		}
		return out
	}
	return &setOpsW{a: draw(16), b: draw(17)}, work(2 * n), nil
}

// ---------------------------------------------------------------- queue

// queueW streams N items through a FIFO with a 1024-item window: Go's usual
// slice-as-queue idiom (append + reslice) vs Rust's VecDeque ring buffer.
type queueW struct{ n int }

const queueWindow = 1024

func (w *queueW) Run() uint64 {
	var q []uint64
	var sum uint64
	for i := 0; i < w.n; i++ {
		q = append(q, uint64(i))
		if len(q) > queueWindow {
			sum += q[0]
			q = q[1:]
		}
	}
	for len(q) > 0 {
		sum += q[0] * 3
		q = q[1:]
	}
	return sum
}

func setupQueue(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	return &queueW{n: n}, work(n), nil
}

// ---------------------------------------------------------------- priority-queue

// minHeap implements heap.Interface (container/heap, interface dispatch).
type minHeap []uint64

func (h minHeap) Len() int           { return len(h) }
func (h minHeap) Less(i, j int) bool { return h[i] < h[j] }
func (h minHeap) Swap(i, j int)      { h[i], h[j] = h[j], h[i] }
func (h *minHeap) Push(x any)        { *h = append(*h, x.(uint64)) }
func (h *minHeap) Pop() any {
	old := *h
	n := len(old)
	x := old[n-1]
	*h = old[:n-1]
	return x
}

// pqW pushes N random values then pops them all in ascending order
// (container/heap vs BinaryHeap<Reverse<u64>>).
type pqW struct{ vals []uint64 }

func (w *pqW) Run() uint64 {
	h := &minHeap{}
	for _, v := range w.vals {
		heap.Push(h, v)
	}
	d := common.NewDigest()
	for h.Len() > 0 {
		d.Add(heap.Pop(h).(uint64))
	}
	return d.Sum()
}

func setupPQ(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	return &pqW{vals: stream(18, n)}, work(n), nil
}

// ---------------------------------------------------------------- sort-structs

type record struct{ a, b, c, d uint64 }

// sortStructsW sorts 32-byte records by the composite key (a, b); a has
// duplicates, b is unique, so the order is total and the result unique.
type sortStructsW struct{ orig, work []record }

func (w *sortStructsW) Prepare() { copy(w.work, w.orig) }

func (w *sortStructsW) Run() uint64 {
	slices.SortFunc(w.work, func(x, y record) int {
		if c := cmp.Compare(x.a, y.a); c != 0 {
			return c
		}
		return cmp.Compare(x.b, y.b)
	})
	n := len(w.work)
	return w.work[0].b ^ w.work[n/2].b ^ w.work[n-1].b
}

func (w *sortStructsW) Check() uint64 {
	d := common.NewDigest()
	for _, r := range w.work {
		d.Add(r.a)
		d.Add(r.b)
	}
	return d.Sum()
}

func setupSortStructs(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("n", 1_000_000))
	r := common.NewSplitMix64(19)
	kmax := uint64(max(n/4, 1))
	orig := make([]record, n)
	for i := range orig {
		orig[i] = record{a: r.Below(kmax), b: uint64(i), c: r.Next(), d: common.Mix64(uint64(i))}
	}
	return &sortStructsW{orig: orig, work: make([]record, n)}, work(n), nil
}
