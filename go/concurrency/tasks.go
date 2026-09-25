package main

import (
	"slices"
	"sync"
	"time"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// ---------------------------------------------------------------- spawn-join

// spawnW spawns N goroutines that each compute one value, then joins them;
// `reps` repeats that inside one coordinating goroutine so that, for small N,
// the measurement is spawn/join cost rather than the cost of entering the
// runtime from outside (which Rust's block_on pays once per Run).
type spawnW struct{ n, reps int }

func (w *spawnW) Run() uint64 {
	return inTask(func() uint64 {
		var total uint64
		results := make([]uint64, w.n)
		for rep := 0; rep < w.reps; rep++ {
			var wg sync.WaitGroup
			wg.Add(w.n)
			for i := 0; i < w.n; i++ {
				go func(i int) {
					results[i] = common.Mix64(uint64(i))
					wg.Done()
				}(i)
			}
			wg.Wait()
			for _, r := range results {
				total += r
			}
		}
		return total
	})
}

func setupSpawn(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("tasks", 10000))
	reps := int(p.Int("reps", 1))
	return &spawnW{n: n, reps: reps}, harness.Work{Unit: "tasks", PerRun: float64(n * reps)}, nil
}

// ---------------------------------------------------------------- sleep

// sleepW spawns N goroutines that each sleep, then report how late they woke:
// a direct view of timer and scheduler behaviour under many waiting tasks.
type sleepW struct {
	n        int
	d        time.Duration
	lateness []int64 // ns, last iteration
}

func (w *sleepW) Run() uint64 {
	return inTask(func() uint64 {
		late := make([]int64, w.n)
		var wg sync.WaitGroup
		wg.Add(w.n)
		for i := 0; i < w.n; i++ {
			go func(i int) {
				t0 := time.Now()
				time.Sleep(w.d)
				late[i] = int64(time.Since(t0) - w.d)
				wg.Done()
			}(i)
		}
		wg.Wait()
		w.lateness = late
		return uint64(w.n)
	})
}

func (w *sleepW) Extra() map[string]any { return latenessStats(w.lateness) }

func latenessStats(late []int64) map[string]any {
	if len(late) == 0 {
		return nil
	}
	s := slices.Clone(late)
	slices.Sort(s)
	q := func(p float64) int64 { return s[int(p*float64(len(s)-1))] }
	return map[string]any{
		"wake_late_p50_ns": q(0.50), "wake_late_p90_ns": q(0.90), "wake_late_p99_ns": q(0.99),
		"wake_late_max_ns": s[len(s)-1], "wake_late_min_ns": s[0],
	}
}

func setupSleep(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("tasks", 10000))
	d := time.Duration(p.Int("sleep_ms", 10)) * time.Millisecond
	return &sleepW{n: n, d: d}, harness.Work{Unit: "tasks", PerRun: float64(n)}, nil
}

// ---------------------------------------------------------------- cpu-split

// cpuSplitW divides a fixed amount of CPU work (mixing rounds) evenly across
// N goroutines: total work is constant, only scheduling granularity changes.
type cpuSplitW struct {
	n     int
	total uint64
}

func chunk(total uint64, n, i int) uint64 {
	base, rem := total/uint64(n), total%uint64(n)
	if uint64(i) < rem {
		return base + 1
	}
	return base
}

func spin(seed, rounds uint64) uint64 {
	x := seed
	for k := uint64(0); k < rounds; k++ {
		x = common.Mix64(x)
	}
	return x
}

func (w *cpuSplitW) Run() uint64 {
	return inTask(func() uint64 {
		results := make([]uint64, w.n)
		var wg sync.WaitGroup
		wg.Add(w.n)
		for i := 0; i < w.n; i++ {
			go func(i int) {
				results[i] = spin(uint64(i), chunk(w.total, w.n, i))
				wg.Done()
			}(i)
		}
		wg.Wait()
		var sum uint64
		for _, r := range results {
			sum += r
		}
		return sum
	})
}

func setupCPUSplit(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("tasks", 1000))
	total := uint64(p.Int("rounds", 1<<25))
	return &cpuSplitW{n: n, total: total}, harness.Work{Unit: "mix_rounds", PerRun: float64(total)}, nil
}
