package harness

import (
	"fmt"
	"strconv"
	"strings"
)

// Params holds the --param key=value pairs passed by the orchestrator.
// Sizes arrive already converted to plain integers (bytes, elements, ...).
type Params map[string]string

// Str returns a string parameter or def when absent.
func (p Params) Str(key, def string) string {
	if v, ok := p[key]; ok {
		return v
	}
	return def
}

// Int returns an integer parameter or def when absent. It panics on a
// malformed value: a bad parameter is a harness bug, never a data point.
func (p Params) Int(key string, def int64) int64 {
	v, ok := p[key]
	if !ok {
		return def
	}
	n, err := strconv.ParseInt(strings.ReplaceAll(v, "_", ""), 10, 64)
	if err != nil {
		panic(fmt.Sprintf("param %s=%q: %v", key, v, err))
	}
	return n
}

// Float returns a float parameter or def when absent.
func (p Params) Float(key string, def float64) float64 {
	v, ok := p[key]
	if !ok {
		return def
	}
	f, err := strconv.ParseFloat(v, 64)
	if err != nil {
		panic(fmt.Sprintf("param %s=%q: %v", key, v, err))
	}
	return f
}

// Bool returns a boolean parameter or def when absent.
func (p Params) Bool(key string, def bool) bool {
	v, ok := p[key]
	if !ok {
		return def
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		panic(fmt.Sprintf("param %s=%q: %v", key, v, err))
	}
	return b
}

// MustStr returns a required string parameter.
func (p Params) MustStr(key string) string {
	v, ok := p[key]
	if !ok || v == "" {
		panic(fmt.Sprintf("missing required param %q", key))
	}
	return v
}

// paramFlag implements flag.Value for repeatable --param key=value flags.
type paramFlag Params

func (f paramFlag) String() string { return "" }

func (f paramFlag) Set(s string) error {
	k, v, ok := strings.Cut(s, "=")
	if !ok || k == "" {
		return fmt.Errorf("want key=value, got %q", s)
	}
	f[k] = v
	return nil
}
