package common

import (
	"strconv"
	"testing"
)

type golden struct {
	SplitMix64 struct {
		Streams []struct {
			Seed string   `json:"seed"`
			Next []string `json:"next"`
		} `json:"streams"`
		Below []struct {
			Seed   string   `json:"seed"`
			N      uint64   `json:"n"`
			Values []uint64 `json:"values"`
		} `json:"below"`
		Float64 []struct {
			Seed string   `json:"seed"`
			Bits []string `json:"bits"`
		} `json:"float64"`
	} `json:"splitmix64"`
	Digest struct {
		Fnv1a64 []struct {
			Input string `json:"input"`
			Hash  string `json:"hash"`
		} `json:"fnv1a64"`
		Mix64 []struct {
			In  string `json:"in"`
			Out string `json:"out"`
		} `json:"mix64"`
		Ordered []struct {
			Words []string `json:"words"`
			Sum   string   `json:"sum"`
		} `json:"ordered"`
		Unordered []struct {
			Words []string `json:"words"`
			Sum   string   `json:"sum"`
		} `json:"unordered"`
	} `json:"digest"`
}

func hex(t *testing.T, s string) uint64 {
	t.Helper()
	v, err := strconv.ParseUint(s, 16, 64)
	if err != nil {
		t.Fatalf("bad hex %q: %v", s, err)
	}
	return v
}

func loadGolden(t *testing.T) golden {
	t.Helper()
	var g golden
	if err := LoadGolden(&g); err != nil {
		t.Fatalf("load golden: %v", err)
	}
	return g
}

func TestSplitMix64Golden(t *testing.T) {
	g := loadGolden(t)
	if len(g.SplitMix64.Streams) == 0 {
		t.Fatal("no golden streams")
	}
	for _, s := range g.SplitMix64.Streams {
		r := NewSplitMix64(hex(t, s.Seed))
		for i, want := range s.Next {
			if got := r.Next(); got != hex(t, want) {
				t.Fatalf("seed %s output %d: got %016x want %s", s.Seed, i, got, want)
			}
		}
	}
	for _, b := range g.SplitMix64.Below {
		r := NewSplitMix64(hex(t, b.Seed))
		for i, want := range b.Values {
			if got := r.Below(b.N); got != want {
				t.Fatalf("below seed %s n %d #%d: got %d want %d", b.Seed, b.N, i, got, want)
			}
		}
	}
	for _, f := range g.SplitMix64.Float64 {
		r := NewSplitMix64(hex(t, f.Seed))
		for i, want := range f.Bits {
			if got := F64Bits(r.Float64()); got != hex(t, want) {
				t.Fatalf("float seed %s #%d: got %016x want %s", f.Seed, i, got, want)
			}
		}
	}
}

func TestDigestGolden(t *testing.T) {
	g := loadGolden(t)
	for _, c := range g.Digest.Fnv1a64 {
		if got := Fnv1a64([]byte(c.Input)); got != hex(t, c.Hash) {
			t.Fatalf("fnv1a64(%q) = %016x want %s", c.Input, got, c.Hash)
		}
		if got := Fnv1a64String(c.Input); got != hex(t, c.Hash) {
			t.Fatalf("fnv1a64String(%q) = %016x want %s", c.Input, got, c.Hash)
		}
	}
	for _, c := range g.Digest.Mix64 {
		if got := Mix64(hex(t, c.In)); got != hex(t, c.Out) {
			t.Fatalf("mix64(%s) = %016x want %s", c.In, got, c.Out)
		}
	}
	for _, c := range g.Digest.Ordered {
		d := NewDigest()
		for _, w := range c.Words {
			d.Add(hex(t, w))
		}
		if d.Sum() != hex(t, c.Sum) {
			t.Fatalf("ordered digest %v = %016x want %s", c.Words, d.Sum(), c.Sum)
		}
	}
	for _, c := range g.Digest.Unordered {
		var u Unordered
		for i := len(c.Words) - 1; i >= 0; i-- { // reversed on purpose
			u.Add(hex(t, c.Words[i]))
		}
		if u.Sum() != hex(t, c.Sum) {
			t.Fatalf("unordered digest %v = %016x want %s", c.Words, u.Sum(), c.Sum)
		}
	}
}
