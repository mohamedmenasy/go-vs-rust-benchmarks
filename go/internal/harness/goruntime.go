package harness

import (
	"math"
	"os"
	"runtime"
	"runtime/debug"
	"runtime/metrics"
)

// Go runtime metrics sampled around the measured phase. Names that the
// running toolchain does not support are reported as absent, never guessed.
var metricNames = []string{
	"/gc/cycles/total:gc-cycles",
	"/cpu/classes/gc/total:cpu-seconds",
	"/cpu/classes/total:cpu-seconds",
	"/cpu/classes/user:cpu-seconds",
	"/cpu/classes/scavenge/total:cpu-seconds",
	"/gc/heap/allocs:bytes",
	"/gc/heap/allocs:objects",
	"/sched/pauses/total/gc:seconds",
}

type rtSnapshot struct {
	ms  runtime.MemStats
	met []metrics.Sample
	ru  rusage
}

func snapshotRuntime() rtSnapshot {
	var s rtSnapshot
	s.met = make([]metrics.Sample, len(metricNames))
	for i, n := range metricNames {
		s.met[i].Name = n
	}
	metrics.Read(s.met)
	runtime.ReadMemStats(&s.ms)
	s.ru = getRusage()
	return s
}

func metricFloat(s metrics.Sample) (float64, bool) {
	switch s.Value.Kind() {
	case metrics.KindFloat64:
		return s.Value.Float64(), true
	case metrics.KindUint64:
		return float64(s.Value.Uint64()), true
	}
	return 0, false
}

// runtimeDelta reports GC and allocation activity between two snapshots.
func runtimeDelta(a, b rtSnapshot) map[string]any {
	out := map[string]any{
		"runtime":           "go",
		"go_version":        runtime.Version(),
		"gomaxprocs":        runtime.GOMAXPROCS(0),
		"gogc_env":          os.Getenv("GOGC"),
		"gomemlimit_bytes":  memLimit(),
		"gc_cycles":         b.ms.NumGC - a.ms.NumGC,
		"gc_forced":         b.ms.NumForcedGC - a.ms.NumForcedGC,
		"gc_pause_total_ns": b.ms.PauseTotalNs - a.ms.PauseTotalNs,
		"alloc_bytes":       b.ms.TotalAlloc - a.ms.TotalAlloc,
		"alloc_objects":     b.ms.Mallocs - a.ms.Mallocs,
		"free_objects":      b.ms.Frees - a.ms.Frees,
		"heap_alloc_end":    b.ms.HeapAlloc,
		"heap_inuse_end":    b.ms.HeapInuse,
		"heap_sys_end":      b.ms.HeapSys,
		"heap_released_end": b.ms.HeapReleased,
		"sys_end":           b.ms.Sys,
		"next_gc_end":       b.ms.NextGC,
		"threads_end":       ThreadCount(),
	}
	// Exact max pause from the 256-entry ring buffer when it covers the window.
	cycles := b.ms.NumGC - a.ms.NumGC
	if cycles > 0 {
		var maxPause uint64
		n := cycles
		if n > 256 {
			n = 256
			out["gc_pause_max_partial"] = true
		}
		for k := uint32(0); k < n; k++ {
			idx := (b.ms.NumGC - k + 255) % 256
			if p := b.ms.PauseNs[idx]; p > maxPause {
				maxPause = p
			}
		}
		out["gc_pause_max_ns"] = maxPause
	} else {
		out["gc_pause_max_ns"] = uint64(0)
	}
	for i := range a.met {
		name := a.met[i].Name
		if a.met[i].Value.Kind() == metrics.KindFloat64Histogram {
			ha, hb := a.met[i].Value.Float64Histogram(), b.met[i].Value.Float64Histogram()
			var n uint64
			for j := range hb.Counts {
				n += hb.Counts[j] - ha.Counts[j]
			}
			out["metric:"+name+":count"] = n
			continue
		}
		va, okA := metricFloat(a.met[i])
		vb, okB := metricFloat(b.met[i])
		if okA && okB {
			out["metric:"+name] = vb - va
		}
	}
	gcCPU, ok1 := out["metric:/cpu/classes/gc/total:cpu-seconds"].(float64)
	totCPU, ok2 := out["metric:/cpu/classes/total:cpu-seconds"].(float64)
	if ok1 && ok2 && totCPU > 0 {
		out["gc_cpu_fraction"] = gcCPU / totCPU
	}
	return out
}

func memLimit() int64 {
	l := debug.SetMemoryLimit(-1)
	if l == math.MaxInt64 {
		return -1
	}
	return l
}

func buildInfo() map[string]any {
	out := map[string]any{"go_version": runtime.Version(), "goarch": runtime.GOARCH, "goos": runtime.GOOS}
	if bi, ok := debug.ReadBuildInfo(); ok {
		settings := map[string]string{}
		for _, s := range bi.Settings {
			settings[s.Key] = s.Value
		}
		out["settings"] = settings
	}
	return out
}
