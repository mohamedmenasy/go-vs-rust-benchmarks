package harness

import (
	"strconv"
	"testing"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
)

func TestHistogramBucketsGolden(t *testing.T) {
	var g struct {
		Histogram []struct {
			Value  string `json:"value"`
			Bucket int    `json:"bucket"`
		} `json:"histogram"`
	}
	if err := common.LoadGolden(&g); err != nil {
		t.Fatal(err)
	}
	if len(g.Histogram) == 0 {
		t.Fatal("no golden histogram entries")
	}
	for _, c := range g.Histogram {
		v, err := strconv.ParseUint(c.Value, 16, 64)
		if err != nil {
			t.Fatal(err)
		}
		if got := HistBucket(v); got != c.Bucket {
			t.Fatalf("bucket(%d) = %d want %d", v, got, c.Bucket)
		}
		if got := HistBucket(v); got >= histBuckets {
			t.Fatalf("bucket(%d) = %d out of range", v, got)
		}
	}
}

func TestHistogramRecord(t *testing.T) {
	var h Histogram
	for _, v := range []uint64{5, 1000, 70, 5} {
		h.Record(v)
	}
	if h.count != 4 || h.min != 5 || h.max != 1000 || h.sum != 1080 {
		t.Fatalf("unexpected summary: %+v", h)
	}
	if h.counts[5] != 2 {
		t.Fatalf("exact bucket 5 count = %d", h.counts[5])
	}
}
