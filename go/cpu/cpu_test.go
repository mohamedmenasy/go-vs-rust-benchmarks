package main

import (
	"encoding/hex"
	"os"
	"path/filepath"
	"strconv"
	"testing"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

type cpuGolden struct {
	CPU struct {
		RandomBytes struct {
			Seed       uint64 `json:"seed"`
			N          int    `json:"n"`
			Fnv        string `json:"fnv1a64"`
			First16Hex string `json:"first16_hex"`
		} `json:"random_bytes"`
		Fib []struct {
			N     uint64 `json:"n"`
			Value uint64 `json:"value"`
		} `json:"fib"`
		Sieve []struct {
			N      int    `json:"n"`
			Digest string `json:"digest"`
		} `json:"sieve"`
		SHA256 []struct {
			Input      *string `json:"input"`
			RandomSeed uint64  `json:"random_seed"`
			N          int     `json:"n"`
			Hex        string  `json:"hex"`
			First8     string  `json:"first8"`
		} `json:"sha256"`
		SortU64 struct {
			N, Seed    int
			Run, Check string
		} `json:"sort_u64"`
		SortStable struct {
			N, Seed    int
			Run, Check string
		} `json:"sort_stable"`
		Matmul struct {
			N, Seed    int
			Run, Check string
		} `json:"matmul"`
		Nbody struct {
			Steps  int    `json:"steps"`
			E0Bits string `json:"e0_bits"`
			E1Bits string `json:"e1_bits"`
			Digest string `json:"digest"`
		} `json:"nbody"`
		Mandelbrot struct {
			W     int    `json:"w"`
			Count uint64 `json:"count"`
			Fnv   string `json:"fnv1a64"`
		} `json:"mandelbrot"`
		CSVParse struct {
			Fixture string `json:"fixture"`
			Digest  string `json:"digest"`
		} `json:"csvparse"`
	} `json:"cpu"`
}

func golden(t *testing.T) cpuGolden {
	t.Helper()
	var g cpuGolden
	if err := common.LoadGolden(&g); err != nil {
		t.Fatal(err)
	}
	return g
}

func hx(t *testing.T, s string) uint64 {
	t.Helper()
	v, err := strconv.ParseUint(s, 16, 64)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

// runOnce drives an instance exactly like the harness does for one iteration.
func runOnce(t *testing.T, inst harness.Instance) (uint64, uint64) {
	t.Helper()
	if p, ok := inst.(harness.Preparer); ok {
		p.Prepare()
	}
	r := inst.Run()
	var c uint64
	if ch, ok := inst.(harness.Checker); ok {
		c = ch.Check()
	}
	// A second iteration must reproduce the same digests.
	if p, ok := inst.(harness.Preparer); ok {
		p.Prepare()
	}
	if r2 := inst.Run(); r2 != r {
		t.Fatalf("non-deterministic run digest %x != %x", r2, r)
	}
	return r, c
}

func params(kv ...string) harness.Params {
	p := harness.Params{}
	for i := 0; i+1 < len(kv); i += 2 {
		p[kv[i]] = kv[i+1]
	}
	return p
}

func TestRandomBytes(t *testing.T) {
	g := golden(t).CPU.RandomBytes
	b := common.RandomBytes(g.Seed, g.N)
	if len(b) != g.N || common.Hex(common.Fnv1a64(b)) != g.Fnv || hex.EncodeToString(b[:16]) != g.First16Hex {
		t.Fatalf("random bytes mismatch")
	}
}

func TestFib(t *testing.T) {
	for _, c := range golden(t).CPU.Fib {
		if got := fib(c.N); got != c.Value {
			t.Fatalf("fib(%d)=%d want %d", c.N, got, c.Value)
		}
	}
}

func TestSieve(t *testing.T) {
	for _, c := range golden(t).CPU.Sieve {
		inst, _, _ := setupSieve(params("n", strconv.Itoa(c.N)))
		if r, _ := runOnce(t, inst); r != hx(t, c.Digest) {
			t.Fatalf("sieve(%d) digest %x want %s", c.N, r, c.Digest)
		}
	}
}

func TestSHA256(t *testing.T) {
	for _, c := range golden(t).CPU.SHA256 {
		var data []byte
		if c.Input != nil {
			data = []byte(*c.Input)
		} else {
			data = common.RandomBytes(c.RandomSeed, c.N)
		}
		s := sha256Portable(data)
		if hex.EncodeToString(s[:]) != c.Hex {
			t.Fatalf("portable sha256 of %d bytes = %x want %s", len(data), s, c.Hex)
		}
		lib := &shaLib{data: data}
		port := &shaPortable{data: data}
		if lib.Run() != hx(t, c.First8) || port.Run() != hx(t, c.First8) {
			t.Fatalf("first8 mismatch for %d bytes", len(data))
		}
	}
}

func TestSorts(t *testing.T) {
	g := golden(t).CPU
	inst, _, _ := setupSortU64(params("n", strconv.Itoa(g.SortU64.N), "seed", strconv.Itoa(g.SortU64.Seed)))
	if r, c := runOnce(t, inst); r != hx(t, g.SortU64.Run) || c != hx(t, g.SortU64.Check) {
		t.Fatalf("sort-u64 digests %x/%x", r, c)
	}
	inst, _, _ = setupSortStable(params("n", strconv.Itoa(g.SortStable.N), "seed", strconv.Itoa(g.SortStable.Seed)))
	if r, c := runOnce(t, inst); r != hx(t, g.SortStable.Run) || c != hx(t, g.SortStable.Check) {
		t.Fatalf("sort-stable digests %x/%x", r, c)
	}
}

func TestMatmul(t *testing.T) {
	g := golden(t).CPU.Matmul
	for _, setup := range []func(harness.Params) (harness.Instance, harness.Work, error){setupMatmul, setupMatmulRows} {
		inst, _, _ := setup(params("n", strconv.Itoa(g.N), "seed", strconv.Itoa(g.Seed)))
		if r, c := runOnce(t, inst); r != hx(t, g.Run) || c != hx(t, g.Check) {
			t.Fatalf("matmul digests %x/%x", r, c)
		}
	}
}

func TestNbody(t *testing.T) {
	g := golden(t).CPU.Nbody
	inst, _, _ := setupNbody(params("steps", strconv.Itoa(g.Steps)))
	if r, _ := runOnce(t, inst); r != hx(t, g.Digest) {
		t.Fatalf("nbody digest %x want %s", r, g.Digest)
	}
	bs := nbodyInitial()
	if e0 := nbodyEnergy(&bs); common.F64Bits(e0) != hx(t, g.E0Bits) {
		t.Fatalf("initial energy %v bits %x want %s", e0, common.F64Bits(e0), g.E0Bits)
	}
}

func TestMandelbrot(t *testing.T) {
	g := golden(t).CPU.Mandelbrot
	inst, _, _ := setupMandelbrot(params("w", strconv.Itoa(g.W)))
	if r, c := runOnce(t, inst); r != g.Count || c != hx(t, g.Fnv) {
		t.Fatalf("mandelbrot count %d fnv %x", r, c)
	}
}

func TestCSVParse(t *testing.T) {
	g := golden(t).CPU.CSVParse
	root, _ := common.RepoRoot()
	path := filepath.Join(root, g.Fixture)
	if _, err := os.Stat(path); err != nil {
		t.Fatal(err)
	}
	inst, _, err := setupCSVParse(params("input", path))
	if err != nil {
		t.Fatal(err)
	}
	if r, _ := runOnce(t, inst); r != hx(t, g.Digest) {
		t.Fatalf("csvparse digest %x want %s", r, g.Digest)
	}
}
