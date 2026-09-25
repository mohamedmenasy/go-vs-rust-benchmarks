// Command io benchmarks file I/O (mirror of rust/io). Opening, reading or
// writing, and closing the file are all timed; the page cache is warm unless
// a workload asks to drop it (drop_caches=1, requires root).
package main

import (
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

func main() {
	harness.Main("io", []harness.Workload{
		{Name: "read-seq", Mode: harness.ModeIter, Setup: setupReadSeq},
		{Name: "read-buffered", Mode: harness.ModeIter, Setup: setupReadBuffered},
		{Name: "write-seq", Mode: harness.ModeIter, Setup: setupWriteSeq},
		{Name: "write-buffered", Mode: harness.ModeIter, Setup: setupWriteBuffered},
		{Name: "lines", Mode: harness.ModeIter, Setup: setupLines},
		{Name: "lines-idiomatic", Mode: harness.ModeIter, Setup: setupLinesIdiomatic},
	})
}
