package main

import (
	"fmt"
	"os"
	"slices"
	"strconv"
	"strings"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// csvparse: parse an in-memory request log (ts,user_id,endpoint,status,
// latency_ms,bytes) and aggregate per endpoint. The file is read (and, for
// Rust, UTF-8 validated) during setup; the timed work is scanning lines and
// fields, parsing integers and decimals, and updating a string-keyed map.
type csvAgg struct {
	count             uint64
	latSum, latMax    float64
	bytes, n4xx, n5xx uint64
}

type csvParse struct{ data string }

func mustInt(s string) int64 {
	v, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		panic(err)
	}
	return v
}

func csvAggregate(data string) uint64 {
	aggs := make(map[string]*csvAgg)
	rows := uint64(0)
	_, rest, _ := strings.Cut(data, "\n") // header
	for len(rest) > 0 {
		var line string
		line, rest, _ = strings.Cut(rest, "\n")
		if line == "" {
			continue
		}
		tsS, r, _ := strings.Cut(line, ",")
		userS, r, _ := strings.Cut(r, ",")
		ep, r, _ := strings.Cut(r, ",")
		statusS, r, _ := strings.Cut(r, ",")
		latS, bytesS, _ := strings.Cut(r, ",")
		_ = mustInt(tsS)
		_ = mustInt(userS)
		status := mustInt(statusS)
		lat, err := strconv.ParseFloat(latS, 64)
		if err != nil {
			panic(err)
		}
		size := mustInt(bytesS)
		a := aggs[ep]
		if a == nil {
			a = &csvAgg{}
			aggs[ep] = a
		}
		a.count++
		a.latSum += lat
		if lat > a.latMax {
			a.latMax = lat
		}
		a.bytes += uint64(size)
		if status >= 400 && status < 500 {
			a.n4xx++
		} else if status >= 500 {
			a.n5xx++
		}
		rows++
	}
	keys := make([]string, 0, len(aggs))
	for k := range aggs {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	d := common.NewDigest()
	for _, k := range keys {
		a := aggs[k]
		d.AddString(k)
		d.Add(a.count)
		d.AddF64(a.latSum)
		d.AddF64(a.latMax)
		d.Add(a.bytes)
		d.Add(a.n4xx)
		d.Add(a.n5xx)
	}
	d.Add(rows)
	return d.Sum()
}

func (w *csvParse) Run() uint64 { return csvAggregate(w.data) }

func setupCSVParse(p harness.Params) (harness.Instance, harness.Work, error) {
	path := p.MustStr("input")
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, harness.Work{}, fmt.Errorf("read %s: %w", path, err)
	}
	return &csvParse{data: string(b)}, harness.Work{Unit: "bytes", PerRun: float64(len(b)), InputBytes: int64(len(b))}, nil
}
