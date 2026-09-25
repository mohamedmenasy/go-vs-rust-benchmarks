package main

import (
	"path/filepath"
	"strconv"
	"testing"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

type jsonCase struct {
	Fixture       string `json:"fixture"`
	Fnv           string `json:"fnv1a64"`
	TypedDigest   string `json:"typed_digest"`
	DynamicDigest string `json:"dynamic_digest"`
}

func hx(t *testing.T, s string) uint64 {
	t.Helper()
	v, err := strconv.ParseUint(s, 16, 64)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestJSONGolden(t *testing.T) {
	var g struct {
		JSON map[string]jsonCase `json:"json"`
	}
	if err := common.LoadGolden(&g); err != nil {
		t.Fatal(err)
	}
	root, _ := common.RepoRoot()
	for schema, c := range g.JSON {
		p := harness.Params{"input": filepath.Join(root, c.Fixture), "schema": schema}
		check := func(setup func(harness.Params) (harness.Instance, harness.Work, error), want uint64, name string) {
			inst, _, err := setup(p)
			if err != nil {
				t.Fatal(err)
			}
			r := inst.Run()
			if inst.Run() != r {
				t.Fatalf("%s/%s: non-deterministic", schema, name)
			}
			if got := inst.(harness.Checker).Check(); got != want {
				t.Fatalf("%s/%s: digest %016x want %016x", schema, name, got, want)
			}
		}
		check(setupDecode(stdCodec), hx(t, c.TypedDigest), "decode")
		check(setupEncode(stdCodec), hx(t, c.Fnv), "encode")
		check(setupDynamic, hx(t, c.DynamicDigest), "decode-dynamic")
		check(setupDecode(fastCodec), hx(t, c.TypedDigest), "decode-fast")
		check(setupEncode(fastCodec), hx(t, c.Fnv), "encode-fast")
	}
}
