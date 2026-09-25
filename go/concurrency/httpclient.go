package main

import (
	"fmt"
	"io"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// httpClientW: N goroutines issue M GET requests in total (M/N each) against
// a neutral nginx server, reading every body, with a keep-alive pool of N
// connections (Rust: reqwest with the same pool size on Tokio).
type httpClientW struct {
	conns, requests int
	url             string
	client          *http.Client
}

func (w *httpClientW) Run() uint64 {
	return inTask(func() uint64 {
		var bytesRead, failures atomic.Uint64
		var wg sync.WaitGroup
		wg.Add(w.conns)
		for c := 0; c < w.conns; c++ {
			n := w.requests / w.conns
			if c < w.requests%w.conns {
				n++
			}
			go func(n int) {
				defer wg.Done()
				for i := 0; i < n; i++ {
					resp, err := w.client.Get(w.url)
					if err != nil {
						failures.Add(1)
						continue
					}
					b, err := io.ReadAll(resp.Body)
					resp.Body.Close()
					if err != nil || resp.StatusCode != http.StatusOK {
						failures.Add(1)
						continue
					}
					bytesRead.Add(uint64(len(b)))
				}
			}(n)
		}
		wg.Wait()
		if f := failures.Load(); f != 0 {
			panic(fmt.Sprintf("%d failed requests", f))
		}
		return bytesRead.Load()
	})
}

func setupHTTPClient(p harness.Params) (harness.Instance, harness.Work, error) {
	conns := int(p.Int("conns", 100))
	reqs := int(p.Int("requests", 100_000))
	tr := &http.Transport{
		MaxIdleConns:        conns,
		MaxIdleConnsPerHost: conns,
		IdleConnTimeout:     120 * time.Second,
		DisableCompression:  true,
	}
	w := &httpClientW{conns: conns, requests: reqs, url: p.MustStr("url"), client: &http.Client{Transport: tr}}
	return w, harness.Work{Unit: "requests", PerRun: float64(reqs)}, nil
}
