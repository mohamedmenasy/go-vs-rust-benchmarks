package main

import (
	"sync"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// ---------------------------------------------------------------- pingpong

// pingPongW bounces a counter between two goroutines over two channels of
// capacity 1 (Rust: two tokio::sync::mpsc channels of capacity 1).
type pingPongW struct{ msgs int }

func (w *pingPongW) Run() uint64 {
	return inTask(func() uint64 {
		ping := make(chan uint64, 1)
		pong := make(chan uint64, 1)
		go func() {
			for v := range ping {
				pong <- v + 1
			}
		}()
		var sum uint64
		for k := 0; k < w.msgs; k++ {
			ping <- uint64(k)
			sum += <-pong
		}
		close(ping)
		return sum
	})
}

func setupPingPong(p harness.Params) (harness.Instance, harness.Work, error) {
	m := int(p.Int("msgs", 1_000_000))
	return &pingPongW{msgs: m}, harness.Work{Unit: "round_trips", PerRun: float64(m)}, nil
}

// ---------------------------------------------------------------- prodcons

// prodConsW: P producers send disjoint ranges of integers through one bounded
// channel; C consumers sum what they receive. Go channels are MPMC for every
// topology; Rust uses tokio::sync::mpsc when C == 1 and async-channel (MPMC)
// when C > 1.
type prodConsW struct{ producers, consumers, msgs, capacity int }

func (w *prodConsW) Run() uint64 {
	return inTask(func() uint64 {
		ch := make(chan uint64, w.capacity)
		var pwg sync.WaitGroup
		pwg.Add(w.producers)
		for p := 0; p < w.producers; p++ {
			lo, hi := p*w.msgs/w.producers, (p+1)*w.msgs/w.producers
			go func() {
				for v := lo; v < hi; v++ {
					ch <- uint64(v)
				}
				pwg.Done()
			}()
		}
		go func() {
			pwg.Wait()
			close(ch)
		}()
		sums := make(chan uint64, w.consumers)
		for c := 0; c < w.consumers; c++ {
			go func() {
				var s uint64
				for v := range ch {
					s += v
				}
				sums <- s
			}()
		}
		var total uint64
		for c := 0; c < w.consumers; c++ {
			total += <-sums
		}
		return total
	})
}

func setupProdCons(p harness.Params) (harness.Instance, harness.Work, error) {
	w := &prodConsW{
		producers: int(p.Int("producers", 1)),
		consumers: int(p.Int("consumers", 1)),
		msgs:      int(p.Int("msgs", 1_000_000)),
		capacity:  int(p.Int("cap", 1024)),
	}
	return w, harness.Work{Unit: "messages", PerRun: float64(w.msgs)}, nil
}

// ---------------------------------------------------------------- fanout

// fanoutW: a dispatcher sends J jobs to N workers over a bounded job channel;
// each worker computes 100 mixing rounds per job and sends the result to a
// bounded results channel that one collector sums (fan-out / fan-in).
type fanoutW struct{ workers, jobs, capacity int }

func (w *fanoutW) Run() uint64 {
	return inTask(func() uint64 {
		jobs := make(chan uint64, w.capacity)
		results := make(chan uint64, w.capacity)
		var wg sync.WaitGroup
		wg.Add(w.workers)
		for i := 0; i < w.workers; i++ {
			go func() {
				for j := range jobs {
					results <- spin(j, 100)
				}
				wg.Done()
			}()
		}
		go func() {
			for j := 0; j < w.jobs; j++ {
				jobs <- uint64(j)
			}
			close(jobs)
		}()
		go func() {
			wg.Wait()
			close(results)
		}()
		var sum uint64
		for r := range results {
			sum += r
		}
		return sum
	})
}

func setupFanout(p harness.Params) (harness.Instance, harness.Work, error) {
	w := &fanoutW{workers: int(p.Int("tasks", 100)), jobs: int(p.Int("jobs", 200_000)), capacity: int(p.Int("cap", 1024))}
	return w, harness.Work{Unit: "jobs", PerRun: float64(w.jobs)}, nil
}
