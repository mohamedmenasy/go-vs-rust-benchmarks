package main

import (
	"strconv"
	"testing"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

type memGolden struct {
	Memory struct {
		Bytes struct {
			Words, Seed int
			Run         string
		} `json:"bytes"`
		Objects struct {
			N, Seed int
			Run     string
		} `json:"objects"`
		Trees []struct {
			Depth int
			Run   string
		} `json:"binarytrees"`
		Churn struct {
			N, Replace, Seed int
			Run, Check       string
		} `json:"churn"`
	} `json:"memory"`
}

func hx(t *testing.T, s string) uint64 {
	t.Helper()
	v, err := strconv.ParseUint(s, 16, 64)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func p(kv ...string) harness.Params {
	out := harness.Params{}
	for i := 0; i+1 < len(kv); i += 2 {
		out[kv[i]] = kv[i+1]
	}
	return out
}

func mustRun(t *testing.T, inst harness.Instance, err error) uint64 {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
	r := inst.Run()
	if r2 := inst.Run(); r2 != r {
		t.Fatalf("non-deterministic: %x != %x", r2, r)
	}
	return r
}

func TestMemoryGolden(t *testing.T) {
	var g memGolden
	if err := common.LoadGolden(&g); err != nil {
		t.Fatal(err)
	}
	m := g.Memory
	i := strconv.Itoa
	inst, _, err := setupBytes(p("bytes", i(m.Bytes.Words*8), "seed", i(m.Bytes.Seed)))
	if r := mustRun(t, inst, err); r != hx(t, m.Bytes.Run) {
		t.Fatalf("bytes %x", r)
	}
	for _, setup := range []func(harness.Params) (harness.Instance, harness.Work, error){setupBoxed, setupInline} {
		inst, _, err := setup(p("bytes", i(m.Objects.N*objSize), "seed", i(m.Objects.Seed)))
		if r := mustRun(t, inst, err); r != hx(t, m.Objects.Run) {
			t.Fatalf("objects %x", r)
		}
	}
	for _, c := range m.Trees {
		inst, _, err := setupTrees(p("depth", i(c.Depth)))
		if r := mustRun(t, inst, err); r != hx(t, c.Run) {
			t.Fatalf("binarytrees depth %d: %x", c.Depth, r)
		}
	}
	inst, _, err = setupChurn(p("bytes", i(m.Churn.N*objSize), "replace_pct", "100", "seed", i(m.Churn.Seed)))
	if r := mustRun(t, inst, err); r != hx(t, m.Churn.Run) {
		t.Fatalf("churn run %x", r)
	}
	if c := inst.(harness.Checker).Check(); c != hx(t, m.Churn.Check) {
		t.Fatalf("churn check %x", c)
	}
}
