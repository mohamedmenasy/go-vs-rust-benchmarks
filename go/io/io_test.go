package main

import (
	"os"
	"path/filepath"
	"strconv"
	"testing"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

func hx(t *testing.T, s string) uint64 {
	t.Helper()
	v, err := strconv.ParseUint(s, 16, 64)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestIOGolden(t *testing.T) {
	var g struct {
		IO struct {
			Read struct {
				Seed   uint64 `json:"seed"`
				N      int    `json:"n"`
				Digest string `json:"digest"`
			} `json:"read"`
			Write struct {
				Seed   int    `json:"seed"`
				Bytes  int    `json:"bytes"`
				Digest string `json:"digest"`
			} `json:"write"`
			Lines struct {
				Fixture string `json:"fixture"`
				Digest  string `json:"digest"`
			} `json:"lines"`
		} `json:"io"`
	}
	if err := common.LoadGolden(&g); err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	in := filepath.Join(dir, "in.bin")
	if err := os.WriteFile(in, common.RandomBytes(g.IO.Read.Seed, g.IO.Read.N), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, setup := range []func(harness.Params) (harness.Instance, harness.Work, error){setupReadSeq, setupReadBuffered} {
		inst, _, err := setup(harness.Params{"input": in})
		if err != nil {
			t.Fatal(err)
		}
		if got := inst.Run(); got != hx(t, g.IO.Read.Digest) {
			t.Fatalf("read digest %016x", got)
		}
	}
	for _, setup := range []func(harness.Params) (harness.Instance, harness.Work, error){setupWriteSeq, setupWriteBuffered} {
		inst, _, err := setup(harness.Params{"bytes": strconv.Itoa(g.IO.Write.Bytes), "seed": strconv.Itoa(g.IO.Write.Seed), "dir": dir})
		if err != nil {
			t.Fatal(err)
		}
		inst.(harness.Preparer).Prepare()
		if got := inst.Run(); got != hx(t, g.IO.Write.Digest) {
			t.Fatalf("write digest %016x", got)
		}
		if n := inst.(harness.Checker).Check(); n != uint64(g.IO.Write.Bytes) {
			t.Fatalf("written file has %d bytes", n)
		}
		inst.(harness.Teardowner).Teardown()
	}
	root, _ := common.RepoRoot()
	for _, setup := range []func(harness.Params) (harness.Instance, harness.Work, error){setupLines, setupLinesIdiomatic} {
		inst, _, err := setup(harness.Params{"input": filepath.Join(root, g.IO.Lines.Fixture)})
		if err != nil {
			t.Fatal(err)
		}
		if got := inst.Run(); got != hx(t, g.IO.Lines.Digest) {
			t.Fatalf("lines digest %016x", got)
		}
	}
}
