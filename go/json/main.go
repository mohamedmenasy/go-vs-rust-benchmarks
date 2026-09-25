// Command json benchmarks encoding/json against serde_json (rust/json) on
// the same documents. Every operation is timed individually (op mode) so the
// histograms give per-document latency percentiles. The "-fast" workloads
// use an optimized third-party library (goccy/go-json vs sonic-rs): tuned track.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"

	gojson "github.com/goccy/go-json"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

type codec struct {
	marshal   func(any) ([]byte, error)
	unmarshal func([]byte, any) error
}

var (
	stdCodec  = codec{json.Marshal, json.Unmarshal}
	fastCodec = codec{gojson.Marshal, gojson.Unmarshal}
)

func main() {
	harness.Main("json", []harness.Workload{
		{Name: "decode", Mode: harness.ModeOp, Setup: setupDecode(stdCodec)},
		{Name: "encode", Mode: harness.ModeOp, Setup: setupEncode(stdCodec)},
		{Name: "decode-dynamic", Mode: harness.ModeOp, Setup: setupDynamic},
		{Name: "decode-fast", Mode: harness.ModeOp, Setup: setupDecode(fastCodec)},
		{Name: "encode-fast", Mode: harness.ModeOp, Setup: setupEncode(fastCodec)},
	})
}

type doc struct {
	data   []byte
	schema string // "object" (Response) or "array" ([]User)
}

func loadDoc(p harness.Params) (doc, harness.Work, error) {
	path := p.MustStr("input")
	b, err := os.ReadFile(path)
	if err != nil {
		return doc{}, harness.Work{}, fmt.Errorf("read %s: %w", path, err)
	}
	schema := p.Str("schema", "object")
	if schema != "object" && schema != "array" {
		return doc{}, harness.Work{}, fmt.Errorf("unknown schema %q", schema)
	}
	return doc{data: b, schema: schema}, harness.Work{Unit: "bytes", PerRun: float64(len(b)), InputBytes: int64(len(b))}, nil
}

// ---------------------------------------------------------------- decode (typed)

type decodeW struct {
	doc
	codec
	obj *Response
	arr []User
}

func (w *decodeW) Run() uint64 {
	if w.schema == "object" {
		var v Response
		if err := w.unmarshal(w.data, &v); err != nil {
			panic(err)
		}
		w.obj = &v
		return uint64(len(v.Items))<<32 ^ uint64(v.Total)
	}
	var v []User
	if err := w.unmarshal(w.data, &v); err != nil {
		panic(err)
	}
	w.arr = v
	return uint64(len(v))<<32 ^ uint64(v[len(v)-1].ID)
}

// Check re-encodes the decoded value (it must reproduce the input exactly)
// and digests every field.
func (w *decodeW) Check() uint64 {
	var out []byte
	var err error
	var dg uint64
	if w.schema == "object" {
		out, err = w.marshal(w.obj)
		dg = digestResponse(w.obj)
	} else {
		out, err = w.marshal(w.arr)
		dg = digestUsers(w.arr)
	}
	if err != nil {
		panic(err)
	}
	if !bytes.Equal(out, w.data) {
		panic("re-encoded document differs from the input")
	}
	return dg
}

func setupDecode(c codec) func(harness.Params) (harness.Instance, harness.Work, error) {
	return func(p harness.Params) (harness.Instance, harness.Work, error) {
		d, work, err := loadDoc(p)
		return &decodeW{doc: d, codec: c}, work, err
	}
}

// ---------------------------------------------------------------- encode (typed)

type encodeW struct {
	doc
	codec
	obj *Response
	arr []User
	out []byte
}

func (w *encodeW) Run() uint64 {
	var out []byte
	var err error
	if w.schema == "object" {
		out, err = w.marshal(w.obj)
	} else {
		out, err = w.marshal(w.arr)
	}
	if err != nil {
		panic(err)
	}
	w.out = out
	return uint64(len(out))
}

func (w *encodeW) Check() uint64 {
	if !bytes.Equal(w.out, w.data) {
		panic("encoded document differs from the input")
	}
	return common.Fnv1a64(w.out)
}

func setupEncode(c codec) func(harness.Params) (harness.Instance, harness.Work, error) {
	return func(p harness.Params) (harness.Instance, harness.Work, error) {
		d, work, err := loadDoc(p)
		if err != nil {
			return nil, work, err
		}
		w := &encodeW{doc: d, codec: c}
		if d.schema == "object" {
			w.obj = &Response{}
			err = json.Unmarshal(d.data, w.obj)
		} else {
			err = json.Unmarshal(d.data, &w.arr)
		}
		return w, work, err
	}
}

// ---------------------------------------------------------------- decode-dynamic

type dynamicW struct {
	doc
	last any
}

func (w *dynamicW) Run() uint64 {
	var v any
	if err := json.Unmarshal(w.data, &v); err != nil {
		panic(err)
	}
	w.last = v
	switch t := v.(type) {
	case map[string]any:
		return uint64(len(t))
	case []any:
		return uint64(len(t))
	}
	return 0
}

func (w *dynamicW) Check() uint64 { return digestDynamic(w.last) }

func setupDynamic(p harness.Params) (harness.Instance, harness.Work, error) {
	d, work, err := loadDoc(p)
	return &dynamicW{doc: d}, work, err
}
