// Package api holds the request logic shared by the Go HTTP servers (net/http
// and Gin). rust/http-common mirrors it exactly: same CPU work, same response
// bytes.
package api

import (
	"encoding/json"
	"os"
	"strconv"
	"strings"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
)

// ScoreRounds is the "small CPU operation" performed per request.
const ScoreRounds = 1000

// User is the response object of GET /users/{id}.
type User struct {
	ID     uint64   `json:"id"`
	Name   string   `json:"name"`
	Email  string   `json:"email"`
	Score  uint64   `json:"score"`
	Tags   []string `json:"tags"`
	Active bool     `json:"active"`
}

var tags = []string{"alpha", "beta", "gamma"}

// ErrorBody is returned with status 400 for a malformed id.
var ErrorBody = []byte(`{"error":"invalid id"}`)

// Score mixes the id ScoreRounds times (SplitMix64 finalizer).
func Score(id uint64) uint64 {
	x := id
	for i := 0; i < ScoreRounds; i++ {
		x = common.Mix64(x + 0x9E3779B97F4A7C15)
	}
	return x
}

// BuildUser parses the path parameter and builds the response object.
func BuildUser(raw string) (*User, bool) {
	id, err := strconv.ParseUint(raw, 10, 64)
	if err != nil {
		return nil, false
	}
	name := "user-" + strconv.FormatUint(id, 10)
	return &User{
		ID:     id,
		Name:   name,
		Email:  name + "@example.com",
		Score:  Score(id),
		Tags:   tags,
		Active: id%2 == 0,
	}, true
}

// Marshal serializes a user (encoding/json, no trailing newline).
func Marshal(u *User) []byte {
	b, err := json.Marshal(u)
	if err != nil {
		panic(err)
	}
	return b
}

// Addr returns the listen address from --addr or $BENCH_ADDR.
func Addr(args []string) string {
	for i, a := range args {
		if a == "--addr" && i+1 < len(args) {
			return args[i+1]
		}
		if v, ok := strings.CutPrefix(a, "--addr="); ok {
			return v
		}
	}
	if v := os.Getenv("BENCH_ADDR"); v != "" {
		return v
	}
	return "127.0.0.1:18080"
}
