// Package harness implements the benchmark-binary protocol shared by every Go
// benchmark program. rust/common/src/harness.rs implements the same protocol;
// METHODOLOGY.md ("Measurement protocol") is the normative description.
//
//	<bin> list
//	<bin> run      <workload> [--param k=v]... [--warmup-iters N] [--warmup-min-ms N]
//	                          [--iters N] [--min-ms N] [--max-iters N] [--max-ms N] [--batch-min-ms N]
//	<bin> validate <workload> [--param k=v]...
//
// Setup, Prepare, Check and Teardown are never timed. Only Run is timed, with
// the monotonic clock. The result is a single JSON document on stdout; phase
// markers on stderr let the orchestrator align its RSS sampler with the
// measured window.
package harness

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
)

const schemaVersion = 1

// Mode selects how Run is timed.
type Mode int

const (
	// ModeIter: one Run call is one timed iteration (a whole workload pass).
	ModeIter Mode = iota
	// ModeOp: one Run call is a single short operation. Ops are timed
	// individually into a histogram and grouped into batches for samples.
	ModeOp
)

func (m Mode) String() string {
	if m == ModeOp {
		return "op"
	}
	return "iter"
}

// Instance is a prepared workload. Run performs the timed work and returns a
// digest of its result; every call must return the same digest, otherwise
// the run is rejected as non-deterministic.
type Instance interface{ Run() uint64 }

// Preparer resets state before each timed Run (e.g. re-copying unsorted data).
type Preparer interface{ Prepare() }

// Checker computes an expensive digest of the post-Run state. It is called
// after the first and the last Run and both values must agree.
type Checker interface{ Check() uint64 }

// Teardowner releases resources after measurement (used by memory workloads
// to observe whether memory is returned to the OS).
type Teardowner interface{ Teardown() }

// ExtraReporter adds workload-specific metrics to the result.
type ExtraReporter interface{ Extra() map[string]any }

// Work describes how much logical work one Run call performs.
type Work struct {
	Unit       string  // e.g. "calls", "bytes", "elements", "ops"
	PerRun     float64 // units of work per Run call
	InputBytes int64   // size of the input consumed per Run call, if meaningful
}

// Workload is a named benchmark exposed by a binary.
type Workload struct {
	Name  string
	Mode  Mode
	Setup func(p Params) (Instance, Work, error)
}

type options struct {
	warmupIters, warmupMinMs, iters, minMs, maxIters, maxMs, batchMinMs int
}

// clock reads only the monotonic clock (one vDSO call), matching Rust's
// Instant::now(). time.Now() would additionally read the wall clock.
type clock struct{ base time.Time }

func (c clock) now() int64 { return int64(time.Since(c.base)) }

// Main runs the protocol for a binary exposing the given workloads.
func Main(bin string, workloads []Workload) {
	if len(os.Args) < 2 {
		usage(bin, workloads)
		os.Exit(2)
	}
	switch cmd := os.Args[1]; cmd {
	case "list":
		names := make([]map[string]string, 0, len(workloads))
		for _, w := range workloads {
			names = append(names, map[string]string{"name": w.Name, "mode": w.Mode.String()})
		}
		emit(map[string]any{"bin": bin, "lang": "go", "workloads": names})
	case "run", "validate":
		if len(os.Args) < 3 {
			usage(bin, workloads)
			os.Exit(2)
		}
		name := os.Args[2]
		var wl *Workload
		for i := range workloads {
			if workloads[i].Name == name {
				wl = &workloads[i]
			}
		}
		if wl == nil {
			fail(fmt.Errorf("unknown workload %q for %s", name, bin))
		}
		params := Params{}
		o := options{}
		fs := flag.NewFlagSet(cmd, flag.ExitOnError)
		fs.Var(paramFlag(params), "param", "workload parameter key=value (repeatable)")
		fs.IntVar(&o.warmupIters, "warmup-iters", 2, "minimum warmup iterations (batches in op mode)")
		fs.IntVar(&o.warmupMinMs, "warmup-min-ms", 500, "minimum warmup time")
		fs.IntVar(&o.iters, "iters", 5, "minimum measured iterations (batches in op mode)")
		fs.IntVar(&o.minMs, "min-ms", 1000, "minimum measured time")
		fs.IntVar(&o.maxIters, "max-iters", 100000, "hard cap on iterations per phase")
		fs.IntVar(&o.maxMs, "max-ms", 600000, "hard cap on wall time per phase")
		fs.IntVar(&o.batchMinMs, "batch-min-ms", 10, "op mode: target duration of one batch")
		_ = fs.Parse(os.Args[3:])
		if cmd == "validate" {
			o.warmupIters, o.warmupMinMs, o.iters, o.minMs = 0, 0, 1, 0
		}
		res, err := execute(bin, wl, params, o)
		if err != nil {
			fail(err)
		}
		emit(res)
	default:
		usage(bin, workloads)
		os.Exit(2)
	}
}

func usage(bin string, workloads []Workload) {
	fmt.Fprintf(os.Stderr, "usage: %s list | run <workload> [flags] | validate <workload> [flags]\nworkloads:", bin)
	for _, w := range workloads {
		fmt.Fprintf(os.Stderr, " %s", w.Name)
	}
	fmt.Fprintln(os.Stderr)
}

func emit(v any) {
	b, err := json.Marshal(v)
	if err != nil {
		fail(err)
	}
	os.Stdout.Write(append(b, '\n'))
}

func fail(err error) {
	b, _ := json.Marshal(map[string]any{"schema": schemaVersion, "lang": "go", "error": err.Error()})
	os.Stdout.Write(append(b, '\n'))
	os.Exit(1)
}

func phase(name string) { fmt.Fprintf(os.Stderr, "@@phase %s\n", name) }

type digestState struct {
	have   bool
	digest uint64
}

func (d *digestState) observe(x uint64) error {
	if !d.have {
		d.have, d.digest = true, x
		return nil
	}
	if x != d.digest {
		return fmt.Errorf("non-deterministic result digest: %016x != %016x", x, d.digest)
	}
	return nil
}

func execute(bin string, wl *Workload, params Params, o options) (res map[string]any, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("panic: %v", r)
		}
	}()
	inst, work, err := wl.Setup(params)
	if err != nil {
		return nil, err
	}
	rssSetup, hwmSetup := memStatus()

	var (
		clk              = clock{base: time.Now()}
		prep, _          = inst.(Preparer)
		checker, _       = inst.(Checker)
		ds               digestState
		checkFirst       uint64
		haveCheck        bool
		warm, samples    []int64
		opsPerSample     int64 = 1
		hist             *Histogram
		maxPhase         = int64(o.maxMs) * int64(time.Millisecond)
		warmupMin, minNs = int64(o.warmupMinMs) * 1e6, int64(o.minMs) * 1e6
	)
	afterFirst := func() {
		if checker != nil && !haveCheck {
			checkFirst, haveCheck = checker.Check(), true
		}
	}

	var snap0, snap1 rtSnapshot
	switch wl.Mode {
	case ModeIter:
		one := func() (int64, error) {
			if prep != nil {
				prep.Prepare()
			}
			t0 := clk.now()
			d := inst.Run()
			dt := clk.now() - t0
			if err := ds.observe(d); err != nil {
				return 0, err
			}
			afterFirst()
			return dt, nil
		}
		var sum int64
		start := clk.now()
		for i := 0; (i < o.warmupIters || sum < warmupMin) && i < o.maxIters && clk.now()-start < maxPhase; i++ {
			dt, err := one()
			if err != nil {
				return nil, err
			}
			warm = append(warm, dt)
			sum += dt
		}
		snap0 = snapshotRuntime()
		phase("measure_start")
		sum, start = 0, clk.now()
		for i := 0; (i < o.iters || sum < minNs) && i < o.maxIters && clk.now()-start < maxPhase; i++ {
			dt, err := one()
			if err != nil {
				return nil, err
			}
			samples = append(samples, dt)
			sum += dt
		}
		phase("measure_end")
		snap1 = snapshotRuntime()

	case ModeOp:
		batch := func(n int64, h *Histogram) (int64, error) {
			var s int64
			for k := int64(0); k < n; k++ {
				t0 := clk.now()
				d := inst.Run()
				dt := clk.now() - t0
				if err := ds.observe(d); err != nil {
					return 0, err
				}
				afterFirst()
				s += dt
				if h != nil {
					h.Record(uint64(dt))
				}
			}
			return s, nil
		}
		// Calibrate the batch size so one batch lasts about batchMinMs.
		var calNs, calOps int64
		calStart := clk.now()
		for calOps == 0 || clk.now()-calStart < 20*int64(time.Millisecond) {
			dt, err := batch(1, nil)
			if err != nil {
				return nil, err
			}
			calNs += dt
			calOps++
		}
		perOp := max(calNs/calOps, 1)
		opsPerSample = max(int64(o.batchMinMs)*1e6/perOp, 1)
		if o.iters == 1 && o.minMs == 0 { // validate mode: a single op suffices
			opsPerSample = 1
		}
		var sum int64
		start := clk.now()
		for i := 0; (i < o.warmupIters || sum < warmupMin) && i < o.maxIters && clk.now()-start < maxPhase; i++ {
			dt, err := batch(opsPerSample, nil)
			if err != nil {
				return nil, err
			}
			warm = append(warm, dt)
			sum += dt
		}
		hist = &Histogram{}
		snap0 = snapshotRuntime()
		phase("measure_start")
		sum, start = 0, clk.now()
		for i := 0; (i < o.iters || sum < minNs) && i < o.maxIters && clk.now()-start < maxPhase; i++ {
			dt, err := batch(opsPerSample, hist)
			if err != nil {
				return nil, err
			}
			samples = append(samples, dt)
			sum += dt
		}
		phase("measure_end")
		snap1 = snapshotRuntime()
	}

	checksum := common.Hex(ds.digest)
	if checker != nil {
		last := checker.Check()
		if haveCheck && last != checkFirst {
			return nil, fmt.Errorf("post-run check digest changed: %016x != %016x", last, checkFirst)
		}
		checksum += ":" + common.Hex(last)
	}
	rssEnd, hwmEnd := memStatus()

	var extra map[string]any
	if er, ok := inst.(ExtraReporter); ok {
		extra = er.Extra()
	}
	rss := map[string]int64{"after_setup": rssSetup, "hwm_after_setup": hwmSetup, "end": rssEnd, "hwm_end": hwmEnd}
	if td, ok := inst.(Teardowner); ok {
		td.Teardown()
		rss["after_teardown"], _ = memStatus()
	}

	res = map[string]any{
		"schema":         schemaVersion,
		"lang":           "go",
		"bin":            bin,
		"workload":       wl.Name,
		"mode":           wl.Mode.String(),
		"params":         params,
		"work":           map[string]any{"unit": work.Unit, "per_run": work.PerRun, "input_bytes": work.InputBytes},
		"checksum":       checksum,
		"warmup_ns":      nonNil(warm),
		"samples_ns":     nonNil(samples),
		"ops_per_sample": opsPerSample,
		"rss_kb":         rss,
		"rusage_measure": snap0.ru.delta(snap1.ru),
		"runtime":        runtimeDelta(snap0, snap1),
		"extra":          extra,
		"build":          buildInfo(),
	}
	if hist != nil {
		res["histogram"] = hist.export()
	}
	return res, nil
}

func nonNil(x []int64) []int64 {
	if x == nil {
		return []int64{}
	}
	return x
}
