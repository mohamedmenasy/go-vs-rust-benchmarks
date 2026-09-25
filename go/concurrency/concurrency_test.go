package main

import (
	"strconv"
	"testing"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

type kv = map[string]any

func hx(t *testing.T, s string) uint64 {
	t.Helper()
	v, err := strconv.ParseUint(s, 16, 64)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func params(m kv) harness.Params {
	p := harness.Params{}
	for k, v := range m {
		switch x := v.(type) {
		case float64:
			p[k] = strconv.FormatInt(int64(x), 10)
		case string:
			p[k] = x
		}
	}
	return p
}

func TestConcurrencyGolden(t *testing.T) {
	var g struct {
		Concurrency map[string][]kv `json:"concurrency"`
	}
	if err := common.LoadGolden(&g); err != nil {
		t.Fatal(err)
	}
	setups := map[string]func(harness.Params) (harness.Instance, harness.Work, error){
		"spawn_join": setupSpawn, "cpu_split": setupCPUSplit, "pingpong": setupPingPong,
		"prodcons": setupProdCons, "fanout": setupFanout,
	}
	for name, cases := range g.Concurrency {
		setup := setups[name]
		if setup == nil {
			t.Fatalf("no setup for %s", name)
		}
		for _, c := range cases {
			want := hx(t, c["run"].(string))
			delete(c, "run")
			variants := []kv{c}
			if name == "prodcons" { // every topology must agree
				variants = nil
				for _, pc := range [][2]float64{{1, 1}, {4, 1}, {1, 4}, {4, 4}} {
					v := kv{"producers": pc[0], "consumers": pc[1]}
					for k, x := range c {
						v[k] = x
					}
					variants = append(variants, v)
				}
			}
			for _, v := range variants {
				inst, _, err := setup(params(v))
				if err != nil {
					t.Fatal(err)
				}
				if got := inst.Run(); got != want {
					t.Fatalf("%s %v: %016x want %016x", name, v, got, want)
				}
			}
		}
	}
	inst, _, _ := setupSleep(harness.Params{"tasks": "1000", "sleep_ms": "2"})
	if got := inst.Run(); got != 1000 {
		t.Fatalf("sleep returned %d", got)
	}
	if ex := inst.(harness.ExtraReporter).Extra(); ex["wake_late_min_ns"].(int64) < 0 {
		t.Fatalf("negative lateness: %v", ex)
	}
}
