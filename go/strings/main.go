// Command strings benchmarks string processing on the shared text corpus
// (mirror of rust/strings). The corpus is loaded in untimed setup; every
// operation below works on the in-memory text.
package main

import (
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

func main() {
	harness.Main("strings", []harness.Workload{
		{Name: "concat", Mode: harness.ModeIter, Setup: withCorpus(newConcat)},
		{Name: "format", Mode: harness.ModeIter, Setup: setupFormat},
		{Name: "search", Mode: harness.ModeIter, Setup: withCorpus(newSearch)},
		{Name: "split", Mode: harness.ModeIter, Setup: withCorpus(newSplit(false))},
		{Name: "split-lazy", Mode: harness.ModeIter, Setup: withCorpus(newSplit(true))},
		{Name: "regex", Mode: harness.ModeIter, Setup: withCorpus(newRegex)},
		{Name: "parse-numbers", Mode: harness.ModeIter, Setup: withCorpus(newParse)},
		{Name: "unicode-count", Mode: harness.ModeIter, Setup: withCorpus(newRuneCount)},
		{Name: "upper", Mode: harness.ModeIter, Setup: withCorpus(newUpper)},
	})
}

func withCorpus(f func(text string, p harness.Params) harness.Instance) func(harness.Params) (harness.Instance, harness.Work, error) {
	return func(p harness.Params) (harness.Instance, harness.Work, error) {
		path := p.MustStr("input")
		b, err := os.ReadFile(path)
		if err != nil {
			return nil, harness.Work{}, err
		}
		text := string(b)
		return f(text, p), harness.Work{Unit: "bytes", PerRun: float64(len(text)), InputBytes: int64(len(text))}, nil
	}
}

// ---------------------------------------------------------------- concat

// concatW appends every token of the corpus plus a separator to a
// strings.Builder with no preallocation (amortized doubling growth).
type concatW struct {
	tokens []string
	out    string
}

func (w *concatW) Run() uint64 {
	var b strings.Builder
	for _, t := range w.tokens {
		b.WriteString(t)
		b.WriteByte(';')
	}
	w.out = b.String()
	return uint64(len(w.out))
}

func (w *concatW) Check() uint64 { return common.Fnv1a64String(w.out) }

func newConcat(text string, _ harness.Params) harness.Instance {
	return &concatW{tokens: strings.Fields(text)}
}

// ---------------------------------------------------------------- format

// formatW formats records with fmt (Fprintf into a Builder) vs write!(String).
type formatW struct {
	n     int
	names []string
	out   string
}

func (w *formatW) Run() uint64 {
	var b strings.Builder
	r := common.NewSplitMix64(10)
	for i := 0; i < w.n; i++ {
		score := float64(r.Below(1_000_000)) / 7.0
		fmt.Fprintf(&b, "id=%d name=%s score=%.2f active=%t\n", r.Next(), w.names[i%len(w.names)], score, i%3 == 0)
	}
	w.out = b.String()
	return uint64(len(w.out))
}

func (w *formatW) Check() uint64 { return common.Fnv1a64String(w.out) }

func setupFormat(p harness.Params) (harness.Instance, harness.Work, error) {
	n := int(p.Int("records", 1_000_000))
	names := []string{"alice", "bob", "carol", "dmitri", "eve", "françois", "gustav", "hiroshi", "ingrid", "jürgen"}
	return &formatW{n: n, names: names}, harness.Work{Unit: "records", PerRun: float64(n)}, nil
}

// ---------------------------------------------------------------- search

var searchPatterns = []string{" the ", "benchmark", "λόγος"}

type searchW struct{ text string }

func (w *searchW) Run() uint64 {
	d := common.NewDigest()
	for _, p := range searchPatterns {
		d.Add(uint64(strings.Count(w.text, p)))
	}
	return d.Sum()
}

func newSearch(text string, _ harness.Params) harness.Instance { return &searchW{text: text} }

// ---------------------------------------------------------------- split

// splitW splits the corpus into lines and each line into words.
//   - split (baseline): strings.Split, which collects []string for every level
//     (Rust: split(..).collect::<Vec<&str>>()); substrings are not copied
//   - split-lazy (idiomatic): strings.SplitSeq iterators (Go 1.24+) vs Rust's
//     lazy split iterators; nothing is collected
type splitW struct {
	text string
	lazy bool
}

func (w *splitW) Run() uint64 {
	var tokens, total uint64
	if w.lazy {
		for line := range strings.SplitSeq(w.text, "\n") {
			for word := range strings.SplitSeq(line, " ") {
				tokens++
				total += uint64(len(word))
			}
		}
	} else {
		for _, line := range strings.Split(w.text, "\n") {
			words := strings.Split(line, " ")
			tokens += uint64(len(words))
			for _, word := range words {
				total += uint64(len(word))
			}
		}
	}
	d := common.NewDigest()
	d.Add(tokens)
	d.Add(total)
	return d.Sum()
}

func newSplit(lazy bool) func(string, harness.Params) harness.Instance {
	return func(text string, _ harness.Params) harness.Instance { return &splitW{text: text, lazy: lazy} }
}

// ---------------------------------------------------------------- regex

// Explicit ASCII classes: Go's \d \w \b are ASCII-only, Rust's are Unicode.
var regexPatterns = []string{
	`[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}`,
	`[0-9]{4}-[0-9]{2}-[0-9]{2}`,
	`(?:foo|bar|baz|qux)[0-9]+`,
}

type regexW struct {
	text string
	res  []*regexp.Regexp
}

func (w *regexW) Run() uint64 {
	d := common.NewDigest()
	for _, re := range w.res {
		var n, starts uint64
		for _, m := range re.FindAllStringIndex(w.text, -1) {
			n++
			starts += uint64(m[0])
		}
		d.Add(n)
		d.Add(starts)
	}
	return d.Sum()
}

func newRegex(text string, _ harness.Params) harness.Instance {
	w := &regexW{text: text}
	for _, p := range regexPatterns {
		w.res = append(w.res, regexp.MustCompile(p)) // compiled in untimed setup
	}
	return w
}

// ---------------------------------------------------------------- parse-numbers

// parseW parses every integer and decimal token of the corpus (extracted in
// setup) with strconv vs str::parse; both are correctly rounded.
type parseW struct{ ints, floats []string }

func (w *parseW) Run() uint64 {
	var isum uint64
	for _, s := range w.ints {
		v, err := strconv.ParseInt(s, 10, 64)
		if err != nil {
			panic(err)
		}
		isum += uint64(v)
	}
	var fsum float64
	for _, s := range w.floats {
		v, err := strconv.ParseFloat(s, 64)
		if err != nil {
			panic(err)
		}
		fsum += v
	}
	d := common.NewDigest()
	d.Add(uint64(len(w.ints)))
	d.Add(isum)
	d.Add(uint64(len(w.floats)))
	d.AddF64(fsum)
	return d.Sum()
}

func isInt(s string) bool {
	if strings.HasPrefix(s, "-") {
		s = s[1:]
	}
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

func isDecimal(s string) bool {
	ip, fp, ok := strings.Cut(s, ".")
	return ok && isInt(ip) && ip[0] != '-' && isInt(fp) && fp[0] != '-'
}

func newParse(text string, _ harness.Params) harness.Instance {
	w := &parseW{}
	for _, t := range strings.Fields(text) {
		if isInt(t) {
			w.ints = append(w.ints, t)
		} else if isDecimal(t) {
			w.floats = append(w.floats, t)
		}
	}
	return w
}

// ---------------------------------------------------------------- unicode

type runeCountW struct{ text string }

func (w *runeCountW) Run() uint64 { return uint64(utf8.RuneCountInString(w.text)) }

func newRuneCount(text string, _ harness.Params) harness.Instance { return &runeCountW{text: text} }

// upperW upper-cases the whole corpus (Unicode-aware). The corpus contains no
// characters with SpecialCasing mappings, so Go and Rust must agree exactly.
type upperW struct {
	text, out string
}

func (w *upperW) Run() uint64 {
	w.out = strings.ToUpper(w.text)
	return uint64(len(w.out))
}

func (w *upperW) Check() uint64 { return common.Fnv1a64String(w.out) }

func newUpper(text string, _ harness.Params) harness.Instance { return &upperW{text: text} }
