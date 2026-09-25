package harness

import "math/bits"

// Histogram is a log-linear latency histogram ("loglin6"): values below 64 get
// exact buckets; above that every power of two is split into 64 linear
// sub-buckets, bounding the relative bucket width at 1/64 (~1.6%). The Rust
// harness implements the identical scheme; scripts/benchctl decodes it.
type Histogram struct {
	counts        [histBuckets]uint64
	count         uint64
	sum, min, max uint64
}

const (
	histSubBits = 6
	histSub     = 1 << histSubBits
	histBuckets = (64 - histSubBits + 1) * histSub // 3776
)

// HistBucket returns the bucket index of v.
func HistBucket(v uint64) int {
	if v < histSub {
		return int(v)
	}
	e := 63 - bits.LeadingZeros64(v) // >= histSubBits
	m := (v >> uint(e-histSubBits)) & (histSub - 1)
	return (e-histSubBits+1)*histSub + int(m)
}

// Record adds one observation (nanoseconds).
func (h *Histogram) Record(v uint64) {
	h.counts[HistBucket(v)]++
	if h.count == 0 || v < h.min {
		h.min = v
	}
	if v > h.max {
		h.max = v
	}
	h.count++
	h.sum += v
}

func (h *Histogram) export() map[string]any {
	buckets := make([][2]uint64, 0, 64)
	for i, c := range h.counts {
		if c != 0 {
			buckets = append(buckets, [2]uint64{uint64(i), c})
		}
	}
	return map[string]any{
		"scheme":  "loglin6",
		"count":   h.count,
		"sum_ns":  h.sum,
		"min_ns":  h.min,
		"max_ns":  h.max,
		"buckets": buckets,
	}
}
