package main

import (
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// mandelbrot: escape-time iteration (max 50) over a w x w grid covering
// [-1.5, 0.5] x [-1, 1], packed one bit per pixel (Benchmarks Game layout).
type mandelbrotW struct {
	w      int
	bitmap []byte
}

const mandelMaxIter = 50

func (m *mandelbrotW) Run() uint64 {
	w, h := m.w, m.w
	rowBytes := (w + 7) / 8
	count := 0
	for y := 0; y < h; y++ {
		ci := 2.0*float64(y)/float64(h) - 1.0
		for xb := 0; xb < rowBytes; xb++ {
			var bits byte
			for bit := 0; bit < 8; bit++ {
				x := xb*8 + bit
				inside := false
				if x < w {
					cr := 2.0*float64(x)/float64(w) - 1.5
					var zr, zi, tr, ti float64
					for i := 0; i < mandelMaxIter && tr+ti <= 4.0; i++ {
						zi = 2.0*zr*zi + ci
						zr = tr - ti + cr
						tr = zr * zr
						ti = zi * zi
					}
					inside = tr+ti <= 4.0
				}
				bits <<= 1
				if inside {
					bits |= 1
					count++
				}
			}
			m.bitmap[y*rowBytes+xb] = bits
		}
	}
	return uint64(count)
}

func (m *mandelbrotW) Check() uint64 { return common.Fnv1a64(m.bitmap) }

func setupMandelbrot(p harness.Params) (harness.Instance, harness.Work, error) {
	w := int(p.Int("w", 4000))
	return &mandelbrotW{w: w, bitmap: make([]byte, (w+7)/8*w)}, harness.Work{Unit: "pixels", PerRun: float64(w) * float64(w)}, nil
}
