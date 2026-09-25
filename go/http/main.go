// Command http is the baseline Go HTTP server: the standard library's
// net/http with the Go 1.22+ ServeMux patterns. Mirrors rust/http-axum.
//
//	GET /users/{id}  parse id, 1000 mixing rounds, build + JSON-encode a user
//	GET /health      "ok"
//
// No logging, no middleware. net.Listen uses somaxconn as the backlog and
// accepted TCP connections have TCP_NODELAY set (Go's default), keep-alive on.
package main

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"runtime"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/api"
)

func users(w http.ResponseWriter, r *http.Request) {
	h := w.Header()
	h.Set("Content-Type", "application/json")
	u, ok := api.BuildUser(r.PathValue("id"))
	if !ok {
		w.WriteHeader(http.StatusBadRequest)
		w.Write(api.ErrorBody)
		return
	}
	w.Write(api.Marshal(u))
}

func health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain")
	w.Write([]byte("ok"))
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /users/{id}", users)
	mux.HandleFunc("GET /health", health)
	addr := api.Addr(os.Args[1:])
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		fmt.Fprintln(os.Stderr, "listen:", err)
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "listening %s (net/http, GOMAXPROCS=%d)\n", ln.Addr(), runtime.GOMAXPROCS(0))
	if err := (&http.Server{Handler: mux}).Serve(ln); err != nil {
		fmt.Fprintln(os.Stderr, "serve:", err)
		os.Exit(1)
	}
}
