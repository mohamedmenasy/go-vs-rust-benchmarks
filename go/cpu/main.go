// Command cpu holds the single-threaded CPU-bound workloads. Every workload
// mirrors rust/cpu/src exactly: same algorithm, same data layout, same
// operation order (floating-point results must match bit for bit).
package main

import "github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"

func main() {
	harness.Main("cpu", []harness.Workload{
		{Name: "fib", Mode: harness.ModeIter, Setup: setupFib},
		{Name: "sieve", Mode: harness.ModeIter, Setup: setupSieve},
		{Name: "sha256-lib", Mode: harness.ModeIter, Setup: setupSHA256Lib},
		{Name: "sha256-portable", Mode: harness.ModeIter, Setup: setupSHA256Portable},
		{Name: "sort-u64", Mode: harness.ModeIter, Setup: setupSortU64},
		{Name: "sort-stable", Mode: harness.ModeIter, Setup: setupSortStable},
		{Name: "matmul", Mode: harness.ModeIter, Setup: setupMatmul},
		{Name: "matmul-rows", Mode: harness.ModeIter, Setup: setupMatmulRows},
		{Name: "nbody", Mode: harness.ModeIter, Setup: setupNbody},
		{Name: "mandelbrot", Mode: harness.ModeIter, Setup: setupMandelbrot},
		{Name: "csvparse", Mode: harness.ModeIter, Setup: setupCSVParse},
	})
}
