// Command selftest exercises the harness protocol with trivial, fully
// deterministic workloads. It exists so the orchestrator, the statistics and
// CI can be tested end to end without running a real benchmark.
package main

import (
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// spin mixes a counter n times: a pure, branch-free integer loop.
type spin struct{ n uint64 }

func (s *spin) Run() uint64 {
	var x uint64
	for i := uint64(0); i < s.n; i++ {
		x = common.Mix64(x + i)
	}
	return x
}

// opspin is the same loop, but short enough to be timed per operation.
type opspin struct{ spin }

func main() {
	harness.Main("selftest", []harness.Workload{
		{Name: "spin", Mode: harness.ModeIter, Setup: func(p harness.Params) (harness.Instance, harness.Work, error) {
			n := uint64(p.Int("n", 1_000_000))
			return &spin{n: n}, harness.Work{Unit: "mixes", PerRun: float64(n)}, nil
		}},
		{Name: "opspin", Mode: harness.ModeOp, Setup: func(p harness.Params) (harness.Instance, harness.Work, error) {
			n := uint64(p.Int("n", 1000))
			return &opspin{spin{n: n}}, harness.Work{Unit: "mixes", PerRun: float64(n)}, nil
		}},
	})
}
