package main

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

const (
	rawChunk  = 1 << 20  // raw read/write syscall size
	bufSize   = 64 << 10 // buffered reader/writer capacity (set explicitly in both languages)
	appRead   = 512      // application read size through the buffered reader
	recSize   = 100      // record size for buffered writes
	pageBytes = 4096     // sampling stride of the content digest
)

// pageSampler digests a byte stream cheaply: one byte per 4 KiB page,
// weighted by page index, plus the total length. It touches every page the
// kernel copied without turning the benchmark into a CPU-bound fold.
type pageSampler struct {
	off int64
	acc uint64
}

func (s *pageSampler) feed(b []byte) {
	first := (s.off + pageBytes - 1) &^ (pageBytes - 1)
	for p := first; p < s.off+int64(len(b)); p += pageBytes {
		s.acc += uint64(b[p-s.off]) * uint64(p/pageBytes+1)
	}
	s.off += int64(len(b))
}

func (s *pageSampler) sum() uint64 {
	d := common.NewDigest()
	d.Add(uint64(s.off))
	d.Add(s.acc)
	return d.Sum()
}

// dropCaches writes back and evicts the page cache (cold-cache variants).
func dropCaches() {
	if err := os.WriteFile("/proc/sys/vm/drop_caches", []byte("1"), 0); err != nil {
		panic(fmt.Sprintf("drop_caches (needs root): %v", err))
	}
}

func fileSize(path string) (int64, error) {
	st, err := os.Stat(path)
	if err != nil {
		return 0, err
	}
	return st.Size(), nil
}

// ---------------------------------------------------------------- reads

type readW struct {
	path     string
	buf      []byte
	buffered bool
	cold     bool
}

func (w *readW) Prepare() {
	if w.cold {
		dropCaches()
	}
}

func (w *readW) Run() uint64 {
	f, err := os.Open(w.path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	var s pageSampler
	var r io.Reader = f
	chunk := w.buf
	if w.buffered {
		r = bufio.NewReaderSize(f, bufSize)
		chunk = w.buf[:appRead]
	}
	for {
		n, err := r.Read(chunk)
		if n > 0 {
			s.feed(chunk[:n])
		}
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			panic(err)
		}
	}
	return s.sum()
}

func newRead(p harness.Params, buffered bool) (harness.Instance, harness.Work, error) {
	path := p.MustStr("input")
	n, err := fileSize(path)
	if err != nil {
		return nil, harness.Work{}, err
	}
	w := &readW{path: path, buf: make([]byte, rawChunk), buffered: buffered, cold: p.Bool("drop_caches", false)}
	return w, harness.Work{Unit: "bytes", PerRun: float64(n), InputBytes: n}, nil
}

func setupReadSeq(p harness.Params) (harness.Instance, harness.Work, error) { return newRead(p, false) }

func setupReadBuffered(p harness.Params) (harness.Instance, harness.Work, error) {
	return newRead(p, true)
}

// ---------------------------------------------------------------- writes

type writeW struct {
	path     string
	total    int64
	block    []byte // 1 MiB of deterministic content, written repeatedly
	buffered bool
	fsync    bool
}

func (w *writeW) Prepare() { _ = os.Remove(w.path) }

func (w *writeW) Run() uint64 {
	f, err := os.Create(w.path)
	if err != nil {
		panic(err)
	}
	var s pageSampler
	var out io.Writer = f
	var bw *bufio.Writer
	if w.buffered {
		bw = bufio.NewWriterSize(f, bufSize)
		out = bw
	}
	step := int64(rawChunk)
	if w.buffered {
		step = recSize
	}
	var written int64
	for written < w.total {
		n := min(step, w.total-written)
		o := written % int64(len(w.block))
		if o+n > int64(len(w.block)) {
			n = int64(len(w.block)) - o
		}
		b := w.block[o : o+n]
		if _, err := out.Write(b); err != nil {
			panic(err)
		}
		s.feed(b)
		written += n
	}
	if bw != nil {
		if err := bw.Flush(); err != nil {
			panic(err)
		}
	}
	if w.fsync {
		if err := f.Sync(); err != nil {
			panic(err)
		}
	}
	if err := f.Close(); err != nil {
		panic(err)
	}
	return s.sum()
}

func (w *writeW) Check() uint64 {
	n, err := fileSize(w.path)
	if err != nil {
		panic(err)
	}
	return uint64(n)
}

func (w *writeW) Teardown() { _ = os.Remove(w.path) }

func newWrite(p harness.Params, buffered bool) (harness.Instance, harness.Work, error) {
	total := p.Int("bytes", 100<<20)
	dir := p.Str("dir", "scratch/io")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, harness.Work{}, err
	}
	w := &writeW{
		path:     filepath.Join(dir, fmt.Sprintf("go-%d.dat", os.Getpid())),
		total:    total,
		block:    common.RandomBytes(uint64(p.Int("seed", 8)), rawChunk),
		buffered: buffered,
		fsync:    p.Bool("fsync", false),
	}
	return w, harness.Work{Unit: "bytes", PerRun: float64(total)}, nil
}

func setupWriteSeq(p harness.Params) (harness.Instance, harness.Work, error) {
	return newWrite(p, false)
}

func setupWriteBuffered(p harness.Params) (harness.Instance, harness.Work, error) {
	return newWrite(p, true)
}

// ---------------------------------------------------------------- lines

// linesW streams the request-log CSV line by line through a 64 KiB buffered
// reader, re-using one line buffer, and aggregates two integer fields with a
// hand-written digit parser (identical in Rust): the I/O + scanning cost.
type linesW struct {
	path      string
	idiomatic bool
	cold      bool
}

func (w *linesW) Prepare() {
	if w.cold {
		dropCaches()
	}
}

func parseUint(b []byte) uint64 {
	var v uint64
	for _, c := range b {
		v = v*10 + uint64(c-'0')
	}
	return v
}

// field returns the i-th comma-separated field of line.
func field(line []byte, i int) []byte {
	start := 0
	for k := 0; k < len(line); k++ {
		if line[k] == ',' {
			if i == 0 {
				return line[start:k]
			}
			i--
			start = k + 1
		}
	}
	return line[start:]
}

type lineAgg struct{ lines, bytes, n5xx uint64 }

func (a *lineAgg) add(status, size uint64) {
	a.lines++
	a.bytes += size
	if status >= 500 {
		a.n5xx++
	}
}

func (a *lineAgg) sum() uint64 {
	d := common.NewDigest()
	d.Add(a.lines)
	d.Add(a.bytes)
	d.Add(a.n5xx)
	return d.Sum()
}

func (w *linesW) Run() uint64 {
	f, err := os.Open(w.path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, bufSize), bufSize)
	sc.Scan() // header
	var agg lineAgg
	if !w.idiomatic {
		for sc.Scan() {
			line := sc.Bytes()
			agg.add(parseUint(field(line, 3)), parseUint(field(line, 5)))
		}
	} else {
		// Idiomatic: a string per line, strings.Split, strconv.Atoi.
		for sc.Scan() {
			parts := strings.Split(sc.Text(), ",")
			status, err1 := strconv.Atoi(parts[3])
			size, err2 := strconv.Atoi(parts[5])
			if err1 != nil || err2 != nil {
				panic("bad line")
			}
			agg.add(uint64(status), uint64(size))
		}
	}
	if err := sc.Err(); err != nil {
		panic(err)
	}
	return agg.sum()
}

func newLines(p harness.Params, idiomatic bool) (harness.Instance, harness.Work, error) {
	path := p.MustStr("input")
	n, err := fileSize(path)
	if err != nil {
		return nil, harness.Work{}, err
	}
	return &linesW{path: path, idiomatic: idiomatic, cold: p.Bool("drop_caches", false)},
		harness.Work{Unit: "bytes", PerRun: float64(n), InputBytes: n}, nil
}

func setupLines(p harness.Params) (harness.Instance, harness.Work, error) { return newLines(p, false) }

func setupLinesIdiomatic(p harness.Params) (harness.Instance, harness.Work, error) {
	return newLines(p, true)
}
