package main

import (
	"path/filepath"
	"strconv"
	"testing"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

type runCheck struct {
	Run   string `json:"run"`
	Check string `json:"check"`
}

func hx(t *testing.T, s string) uint64 {
	t.Helper()
	v, err := strconv.ParseUint(s, 16, 64)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestCollectionsGolden(t *testing.T) {
	var g struct {
		C struct {
			N             int      `json:"n"`
			VecPush       string   `json:"vec_push"`
			VecRandomRead string   `json:"vec_random_read"`
			MapInsert     runCheck `json:"map_insert"`
			MapLookup     string   `json:"map_lookup"`
			MapString     struct {
				Fixture string `json:"fixture"`
				runCheck
			} `json:"map_string"`
			SetOps        string   `json:"set_ops"`
			Queue         string   `json:"queue"`
			PriorityQueue string   `json:"priority_queue"`
			SortStructs   runCheck `json:"sort_structs"`
		} `json:"collections"`
	}
	if err := common.LoadGolden(&g); err != nil {
		t.Fatal(err)
	}
	c := g.C
	p := harness.Params{"n": strconv.Itoa(c.N)}
	run := func(name string, setup func(harness.Params) (harness.Instance, harness.Work, error), params harness.Params, want string, wantCheck string) {
		t.Helper()
		inst, _, err := setup(params)
		if err != nil {
			t.Fatal(err)
		}
		if pr, ok := inst.(harness.Preparer); ok {
			pr.Prepare()
		}
		if r := inst.Run(); r != hx(t, want) {
			t.Fatalf("%s: run %016x want %s", name, r, want)
		}
		if wantCheck != "" {
			if ch := inst.(harness.Checker).Check(); ch != hx(t, wantCheck) {
				t.Fatalf("%s: check %016x want %s", name, ch, wantCheck)
			}
		}
	}
	run("vec-push", setupVecPush, p, c.VecPush, "")
	run("vec-random-read", setupVecRead, p, c.VecRandomRead, "")
	run("map-insert", setupMapInsert, p, c.MapInsert.Run, c.MapInsert.Check)
	run("map-lookup", setupMapLookup, p, c.MapLookup, "")
	root, _ := common.RepoRoot()
	ps := harness.Params{"n": strconv.Itoa(c.N), "input": filepath.Join(root, c.MapString.Fixture)}
	run("map-string", setupMapString, ps, c.MapString.Run, c.MapString.Check)
	run("set-ops", setupSetOps, p, c.SetOps, "")
	run("queue", setupQueue, p, c.Queue, "")
	run("priority-queue", setupPQ, p, c.PriorityQueue, "")
	run("sort-structs", setupSortStructs, p, c.SortStructs.Run, c.SortStructs.Check)
}
