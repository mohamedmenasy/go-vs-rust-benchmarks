package main

import "github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"

// fib is the naive doubly-recursive definition: a pure function-call
// benchmark (call overhead, stack frames, branch prediction).
func fib(n uint64) uint64 {
	if n < 2 {
		return n
	}
	return fib(n-1) + fib(n-2)
}

// fibIter computes F(n) iteratively (setup only).
func fibIter(n uint64) uint64 {
	a, b := uint64(0), uint64(1)
	for i := uint64(0); i < n; i++ {
		a, b = b, a+b
	}
	return a
}

type fibW struct{ n uint64 }

func (w *fibW) Run() uint64 { return fib(w.n) }

func setupFib(p harness.Params) (harness.Instance, harness.Work, error) {
	n := uint64(p.Int("n", 35))
	calls := 2*fibIter(n+1) - 1 // calls made by fib(n)
	return &fibW{n: n}, harness.Work{Unit: "calls", PerRun: float64(calls)}, nil
}
