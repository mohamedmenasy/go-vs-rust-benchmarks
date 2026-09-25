package main

import (
	"path/filepath"
	"strconv"
	"testing"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

type lenFnv struct {
	Len int    `json:"len"`
	Fnv string `json:"fnv1a64"`
}

func hx(t *testing.T, s string) uint64 {
	t.Helper()
	v, err := strconv.ParseUint(s, 16, 64)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestStringsGolden(t *testing.T) {
	var g struct {
		S struct {
			Fixture string `json:"fixture"`
			Concat  lenFnv `json:"concat"`
			Format  struct {
				Records int `json:"records"`
				lenFnv
			} `json:"format"`
			Search       string `json:"search"`
			Split        string `json:"split"`
			Regex        string `json:"regex"`
			ParseNumbers string `json:"parse_numbers"`
			UnicodeCount uint64 `json:"unicode_count"`
			Upper        lenFnv `json:"upper"`
		} `json:"strings"`
	}
	if err := common.LoadGolden(&g); err != nil {
		t.Fatal(err)
	}
	root, _ := common.RepoRoot()
	p := harness.Params{"input": filepath.Join(root, g.S.Fixture)}
	run := func(setup func(harness.Params) (harness.Instance, harness.Work, error), params harness.Params) (uint64, uint64) {
		inst, _, err := setup(params)
		if err != nil {
			t.Fatal(err)
		}
		r := inst.Run()
		if inst.Run() != r {
			t.Fatal("non-deterministic")
		}
		var c uint64
		if ch, ok := inst.(harness.Checker); ok {
			c = ch.Check()
		}
		return r, c
	}
	check := func(name string, got, want uint64) {
		t.Helper()
		if got != want {
			t.Fatalf("%s: got %016x want %016x", name, got, want)
		}
	}
	r, c := run(withCorpus(newConcat), p)
	check("concat len", r, uint64(g.S.Concat.Len))
	check("concat fnv", c, hx(t, g.S.Concat.Fnv))
	r, c = run(setupFormat, harness.Params{"records": strconv.Itoa(g.S.Format.Records)})
	check("format len", r, uint64(g.S.Format.Len))
	check("format fnv", c, hx(t, g.S.Format.Fnv))
	r, _ = run(withCorpus(newSearch), p)
	check("search", r, hx(t, g.S.Search))
	for _, lazy := range []bool{false, true} {
		r, _ = run(withCorpus(newSplit(lazy)), p)
		check("split", r, hx(t, g.S.Split))
	}
	r, _ = run(withCorpus(newRegex), p)
	check("regex", r, hx(t, g.S.Regex))
	r, _ = run(withCorpus(newParse), p)
	check("parse-numbers", r, hx(t, g.S.ParseNumbers))
	r, _ = run(withCorpus(newRuneCount), p)
	check("unicode-count", r, g.S.UnicodeCount)
	r, c = run(withCorpus(newUpper), p)
	check("upper len", r, uint64(g.S.Upper.Len))
	check("upper fnv", c, hx(t, g.S.Upper.Fnv))
}
