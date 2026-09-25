// Command memory holds the allocation / GC workloads (METHODOLOGY.md §13.2).
// Allocation and deallocation are part of the timed work here: in Rust the
// free happens inside Run (drop), in Go the GC reclaims garbage during later
// iterations, so steady-state per-iteration times include GC work.
package main

import "github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"

func main() {
	harness.Main("memory", []harness.Workload{
		{Name: "bytes", Mode: harness.ModeIter, Setup: setupBytes},
		{Name: "objects-boxed", Mode: harness.ModeIter, Setup: setupBoxed},
		{Name: "objects-inline", Mode: harness.ModeIter, Setup: setupInline},
		{Name: "binarytrees", Mode: harness.ModeIter, Setup: setupTrees},
		{Name: "churn", Mode: harness.ModeIter, Setup: setupChurn},
	})
}
