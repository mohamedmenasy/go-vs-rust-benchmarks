// Command concurrency compares goroutines + channels with Tokio tasks + async
// channels (rust/concurrency). GOMAXPROCS equals the pinned cores; the Rust
// side uses a multi-threaded Tokio runtime with the same worker count. In
// both languages every workload's coordinating logic itself runs inside a
// spawned goroutine/task (never on a special main thread).
package main

import (
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

func main() {
	harness.Main("concurrency", []harness.Workload{
		{Name: "spawn-join", Mode: harness.ModeIter, Setup: setupSpawn},
		{Name: "sleep", Mode: harness.ModeIter, Setup: setupSleep},
		{Name: "cpu-split", Mode: harness.ModeIter, Setup: setupCPUSplit},
		{Name: "pingpong", Mode: harness.ModeIter, Setup: setupPingPong},
		{Name: "prodcons", Mode: harness.ModeIter, Setup: setupProdCons},
		{Name: "fanout", Mode: harness.ModeIter, Setup: setupFanout},
		{Name: "http-client", Mode: harness.ModeIter, Setup: setupHTTPClient},
	})
}

// inTask runs f in a fresh goroutine and waits for its result (mirrors the
// Rust side's `rt.block_on(tokio::spawn(f))`).
func inTask(f func() uint64) uint64 {
	ch := make(chan uint64, 1)
	go func() { ch <- f() }()
	return <-ch
}
