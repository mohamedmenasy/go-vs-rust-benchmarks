//! Tokio tasks + async channels, mirroring go/concurrency (goroutines +
//! channels). A multi-threaded Tokio runtime is built during setup with
//! worker_threads = $BENCH_THREADS (the pinned cores; Go uses GOMAXPROCS).
//! Every workload's coordinating logic runs inside a spawned task, like the
//! Go side's `inTask`, never on the non-worker main thread.
//!
//! Channels: tokio::sync::mpsc where one consumer suffices, async-channel
//! (MPMC, like Go channels) where several consumers share a channel.

use std::future::Future;
use std::time::{Duration, Instant};

use bench_common::serde_json::{Value, json};
use bench_common::{Instance, Mode, Params, Work, Workload, mix64};
use tokio::runtime::Runtime;
use tokio::sync::mpsc;

fn runtime() -> Result<Runtime, String> {
    let threads = std::env::var("BENCH_THREADS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or_else(|| std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1));
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(threads)
        .enable_all()
        .build()
        .map_err(|e| e.to_string())
}

/// Run `f` as a spawned task and wait for it (Go: `inTask`).
fn in_task<T: Send + 'static>(rt: &Runtime, f: impl Future<Output = T> + Send + 'static) -> T {
    rt.block_on(async move { tokio::spawn(f).await.expect("task panicked") })
}

fn spin(seed: u64, rounds: u64) -> u64 {
    let mut x = seed;
    for _ in 0..rounds {
        x = mix64(x);
    }
    x
}

fn chunk(total: u64, n: usize, i: usize) -> u64 {
    let (base, rem) = (total / n as u64, total % n as u64);
    if (i as u64) < rem { base + 1 } else { base }
}

// ---------------------------------------------------------------- spawn-join

struct Spawn {
    rt: Runtime,
    n: usize,
    reps: usize,
}

impl Instance for Spawn {
    /// `reps` repeats spawn+join inside one task (see go/concurrency/tasks.go).
    fn run(&mut self) -> u64 {
        let (n, reps) = (self.n, self.reps);
        in_task(&self.rt, async move {
            let mut total = 0u64;
            let mut handles = Vec::with_capacity(n);
            for _ in 0..reps {
                for i in 0..n {
                    handles.push(tokio::spawn(async move { mix64(i as u64) }));
                }
                for h in handles.drain(..) {
                    total = total.wrapping_add(h.await.unwrap());
                }
            }
            total
        })
    }
}

fn setup_spawn(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("tasks", 10_000) as usize;
    let reps = p.int("reps", 1) as usize;
    Ok((
        Box::new(Spawn { rt: runtime()?, n, reps }),
        Work { unit: "tasks", per_run: (n * reps) as f64, input_bytes: 0 },
    ))
}

// ---------------------------------------------------------------- sleep

struct Sleep {
    rt: Runtime,
    n: usize,
    d: Duration,
    lateness: Vec<i64>,
}

impl Instance for Sleep {
    fn run(&mut self) -> u64 {
        let (n, d) = (self.n, self.d);
        let late = in_task(&self.rt, async move {
            let mut handles = Vec::with_capacity(n);
            for _ in 0..n {
                handles.push(tokio::spawn(async move {
                    let t0 = Instant::now();
                    tokio::time::sleep(d).await;
                    t0.elapsed().as_nanos() as i64 - d.as_nanos() as i64
                }));
            }
            let mut late = Vec::with_capacity(n);
            for h in handles {
                late.push(h.await.unwrap());
            }
            late
        });
        self.lateness = late;
        n as u64
    }
    fn extra(&mut self) -> Option<Value> {
        if self.lateness.is_empty() {
            return None;
        }
        let mut s = self.lateness.clone();
        s.sort_unstable();
        let q = |p: f64| s[(p * (s.len() - 1) as f64) as usize];
        Some(json!({
            "wake_late_p50_ns": q(0.50), "wake_late_p90_ns": q(0.90), "wake_late_p99_ns": q(0.99),
            "wake_late_max_ns": s[s.len() - 1], "wake_late_min_ns": s[0],
        }))
    }
}

fn setup_sleep(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("tasks", 10_000) as usize;
    let d = Duration::from_millis(p.int("sleep_ms", 10) as u64);
    Ok((
        Box::new(Sleep { rt: runtime()?, n, d, lateness: Vec::new() }),
        Work { unit: "tasks", per_run: n as f64, input_bytes: 0 },
    ))
}

// ---------------------------------------------------------------- cpu-split

struct CpuSplit {
    rt: Runtime,
    n: usize,
    total: u64,
}

impl Instance for CpuSplit {
    fn run(&mut self) -> u64 {
        let (n, total) = (self.n, self.total);
        in_task(&self.rt, async move {
            let mut handles = Vec::with_capacity(n);
            for i in 0..n {
                handles.push(tokio::spawn(async move { spin(i as u64, chunk(total, n, i)) }));
            }
            let mut sum = 0u64;
            for h in handles {
                sum = sum.wrapping_add(h.await.unwrap());
            }
            sum
        })
    }
}

fn setup_cpu_split(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let n = p.int("tasks", 1000) as usize;
    let total = p.int("rounds", 1 << 25) as u64;
    Ok((
        Box::new(CpuSplit { rt: runtime()?, n, total }),
        Work { unit: "mix_rounds", per_run: total as f64, input_bytes: 0 },
    ))
}

// ---------------------------------------------------------------- pingpong

struct PingPong {
    rt: Runtime,
    msgs: u64,
}

impl Instance for PingPong {
    fn run(&mut self) -> u64 {
        let m = self.msgs;
        in_task(&self.rt, async move {
            let (ping_tx, mut ping_rx) = mpsc::channel::<u64>(1);
            let (pong_tx, mut pong_rx) = mpsc::channel::<u64>(1);
            tokio::spawn(async move {
                while let Some(v) = ping_rx.recv().await {
                    if pong_tx.send(v + 1).await.is_err() {
                        break;
                    }
                }
            });
            let mut sum = 0u64;
            for k in 0..m {
                ping_tx.send(k).await.unwrap();
                sum = sum.wrapping_add(pong_rx.recv().await.unwrap());
            }
            sum
        })
    }
}

fn setup_pingpong(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let msgs = p.int("msgs", 1_000_000) as u64;
    Ok((
        Box::new(PingPong { rt: runtime()?, msgs }),
        Work { unit: "round_trips", per_run: msgs as f64, input_bytes: 0 },
    ))
}

// ---------------------------------------------------------------- prodcons

struct ProdCons {
    rt: Runtime,
    producers: usize,
    consumers: usize,
    msgs: usize,
    cap: usize,
}

impl Instance for ProdCons {
    fn run(&mut self) -> u64 {
        let (np, nc, m, cap) = (self.producers, self.consumers, self.msgs, self.cap);
        in_task(&self.rt, async move {
            let mut consumers = Vec::with_capacity(nc);
            if nc == 1 {
                // multi-producer, single-consumer: tokio::sync::mpsc
                let (tx, mut rx) = mpsc::channel::<u64>(cap);
                for p in 0..np {
                    let tx = tx.clone();
                    let (lo, hi) = (p * m / np, (p + 1) * m / np);
                    tokio::spawn(async move {
                        for v in lo..hi {
                            tx.send(v as u64).await.unwrap();
                        }
                    });
                }
                drop(tx);
                consumers.push(tokio::spawn(async move {
                    let mut s = 0u64;
                    while let Some(v) = rx.recv().await {
                        s = s.wrapping_add(v);
                    }
                    s
                }));
            } else {
                // multiple consumers: async-channel (MPMC, like a Go channel)
                let (tx, rx) = async_channel::bounded::<u64>(cap);
                for p in 0..np {
                    let tx = tx.clone();
                    let (lo, hi) = (p * m / np, (p + 1) * m / np);
                    tokio::spawn(async move {
                        for v in lo..hi {
                            tx.send(v as u64).await.unwrap();
                        }
                    });
                }
                drop(tx);
                for _ in 0..nc {
                    let rx = rx.clone();
                    consumers.push(tokio::spawn(async move {
                        let mut s = 0u64;
                        while let Ok(v) = rx.recv().await {
                            s = s.wrapping_add(v);
                        }
                        s
                    }));
                }
            }
            let mut total = 0u64;
            for c in consumers {
                total = total.wrapping_add(c.await.unwrap());
            }
            total
        })
    }
}

fn setup_prodcons(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let w = ProdCons {
        rt: runtime()?,
        producers: p.int("producers", 1) as usize,
        consumers: p.int("consumers", 1) as usize,
        msgs: p.int("msgs", 1_000_000) as usize,
        cap: p.int("cap", 1024) as usize,
    };
    let msgs = w.msgs as f64;
    Ok((Box::new(w), Work { unit: "messages", per_run: msgs, input_bytes: 0 }))
}

// ---------------------------------------------------------------- fanout

struct Fanout {
    rt: Runtime,
    workers: usize,
    jobs: u64,
    cap: usize,
}

impl Instance for Fanout {
    fn run(&mut self) -> u64 {
        let (nw, nj, cap) = (self.workers, self.jobs, self.cap);
        in_task(&self.rt, async move {
            let (job_tx, job_rx) = async_channel::bounded::<u64>(cap);
            let (res_tx, mut res_rx) = mpsc::channel::<u64>(cap);
            for _ in 0..nw {
                let (job_rx, res_tx) = (job_rx.clone(), res_tx.clone());
                tokio::spawn(async move {
                    while let Ok(j) = job_rx.recv().await {
                        res_tx.send(spin(j, 100)).await.unwrap();
                    }
                });
            }
            drop((job_rx, res_tx));
            tokio::spawn(async move {
                for j in 0..nj {
                    job_tx.send(j).await.unwrap();
                }
            });
            let mut sum = 0u64;
            while let Some(r) = res_rx.recv().await {
                sum = sum.wrapping_add(r);
            }
            sum
        })
    }
}

fn setup_fanout(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let w = Fanout {
        rt: runtime()?,
        workers: p.int("tasks", 100) as usize,
        jobs: p.int("jobs", 200_000) as u64,
        cap: p.int("cap", 1024) as usize,
    };
    let jobs = w.jobs as f64;
    Ok((Box::new(w), Work { unit: "jobs", per_run: jobs, input_bytes: 0 }))
}

// ---------------------------------------------------------------- http-client

struct HttpClient {
    rt: Runtime,
    client: reqwest::Client,
    conns: usize,
    requests: usize,
    url: String,
}

impl Instance for HttpClient {
    fn run(&mut self) -> u64 {
        let (conns, reqs) = (self.conns, self.requests);
        let (client, url) = (self.client.clone(), self.url.clone());
        in_task(&self.rt, async move {
            let mut handles = Vec::with_capacity(conns);
            for c in 0..conns {
                let n = reqs / conns + usize::from(c < reqs % conns);
                let (client, url) = (client.clone(), url.clone());
                handles.push(tokio::spawn(async move {
                    let (mut bytes, mut failures) = (0u64, 0u64);
                    for _ in 0..n {
                        match client.get(&url).send().await {
                            Ok(resp) if resp.status().is_success() => match resp.bytes().await {
                                Ok(b) => bytes += b.len() as u64,
                                Err(_) => failures += 1,
                            },
                            _ => failures += 1,
                        }
                    }
                    (bytes, failures)
                }));
            }
            let (mut bytes, mut failures) = (0u64, 0u64);
            for h in handles {
                let (b, f) = h.await.unwrap();
                bytes += b;
                failures += f;
            }
            assert!(failures == 0, "{failures} failed requests");
            bytes
        })
    }
}

fn setup_http_client(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let conns = p.int("conns", 100) as usize;
    let requests = p.int("requests", 100_000) as usize;
    let rt = runtime()?;
    let client = {
        let _guard = rt.enter();
        reqwest::Client::builder()
            .pool_max_idle_per_host(conns)
            .pool_idle_timeout(Duration::from_secs(120))
            .build()
            .map_err(|e| e.to_string())?
    };
    Ok((
        Box::new(HttpClient { rt, client, conns, requests, url: p.must_str("url") }),
        Work { unit: "requests", per_run: requests as f64, input_bytes: 0 },
    ))
}

fn main() {
    bench_common::main(
        "concurrency",
        &[
            Workload { name: "spawn-join", mode: Mode::Iter, setup: setup_spawn },
            Workload { name: "sleep", mode: Mode::Iter, setup: setup_sleep },
            Workload { name: "cpu-split", mode: Mode::Iter, setup: setup_cpu_split },
            Workload { name: "pingpong", mode: Mode::Iter, setup: setup_pingpong },
            Workload { name: "prodcons", mode: Mode::Iter, setup: setup_prodcons },
            Workload { name: "fanout", mode: Mode::Iter, setup: setup_fanout },
            Workload { name: "http-client", mode: Mode::Iter, setup: setup_http_client },
        ],
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use bench_common::golden_hex;

    fn params(v: &Value, extra: &[(&str, &str)]) -> Params {
        let mut p = Params::default();
        for (k, x) in v.as_object().unwrap() {
            if k != "run" {
                p.0.insert(k.clone(), x.to_string());
            }
        }
        for (k, x) in extra {
            p.0.insert(k.to_string(), x.to_string());
        }
        p
    }

    #[test]
    fn matches_golden() {
        let g = bench_common::load_golden()["concurrency"].clone();
        let setups: [(&str, bench_common::harness::SetupFn); 5] = [
            ("spawn_join", setup_spawn),
            ("cpu_split", setup_cpu_split),
            ("pingpong", setup_pingpong),
            ("prodcons", setup_prodcons),
            ("fanout", setup_fanout),
        ];
        for (name, setup) in setups {
            for c in g[name].as_array().unwrap() {
                let want = golden_hex(&c["run"]);
                let topologies: &[&[(&str, &str)]] = if name == "prodcons" {
                    &[
                        &[("producers", "1"), ("consumers", "1")],
                        &[("producers", "4"), ("consumers", "1")],
                        &[("producers", "1"), ("consumers", "4")],
                        &[("producers", "4"), ("consumers", "4")],
                    ]
                } else {
                    &[&[]]
                };
                for extra in topologies {
                    let (mut inst, _) = setup(&params(c, extra)).unwrap();
                    assert_eq!(inst.run(), want, "{name} {c} {extra:?}");
                }
            }
        }
        let mut p = Params::default();
        p.0.insert("tasks".into(), "1000".into());
        p.0.insert("sleep_ms".into(), "2".into());
        let (mut inst, _) = setup_sleep(&p).unwrap();
        assert_eq!(inst.run(), 1000);
        assert!(inst.extra().unwrap()["wake_late_min_ns"].as_i64().unwrap() >= 0);
    }
}
