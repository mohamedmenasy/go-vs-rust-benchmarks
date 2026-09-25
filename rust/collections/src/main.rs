//! Standard collections, mirroring go/collections: Vec vs slices, std
//! HashMap/HashSet with the default SipHash-1-3 hasher (baseline) vs Go's
//! built-in maps, VecDeque vs the Go slice-queue idiom, BinaryHeap vs
//! container/heap, sort_unstable_by vs slices.SortFunc. The `-foldhash`
//! workloads swap in the foldhash hasher (tuned track).

use std::cmp::Reverse;
use std::collections::hash_map::RandomState;
use std::collections::{BinaryHeap, HashMap, HashSet, VecDeque};
use std::hash::BuildHasher;

use bench_common::{Digest, Instance, Mode, Params, SplitMix64, Unordered, Work, Workload, fnv1a64, mix64};

type SetupResult = Result<(Box<dyn Instance>, Work), String>;
type Fold = foldhash::fast::RandomState;

fn stream(seed: u64, n: usize) -> Vec<u64> {
    let mut r = SplitMix64::new(seed);
    (0..n).map(|_| r.next_u64()).collect()
}

fn work(n: usize) -> Work {
    Work { unit: "elements", per_run: n as f64, input_bytes: 0 }
}

fn size(p: &Params) -> usize {
    p.int("n", 1_000_000) as usize
}

// ---------------------------------------------------------------- vec-push

struct VecPush {
    vals: Vec<u64>,
}

impl Instance for VecPush {
    fn run(&mut self) -> u64 {
        let mut s: Vec<u64> = Vec::new();
        for &v in &self.vals {
            s.push(v);
        }
        let sum = s.iter().fold(0u64, |a, &v| a.wrapping_add(v));
        sum ^ s.len() as u64
    }
}

fn setup_vec_push(p: &Params) -> SetupResult {
    let n = size(p);
    Ok((Box::new(VecPush { vals: stream(11, n) }), work(n)))
}

// ---------------------------------------------------------------- vec-random-read

struct VecRead {
    data: Vec<u64>,
    idx: Vec<u32>,
}

impl Instance for VecRead {
    fn run(&mut self) -> u64 {
        let mut sum = 0u64;
        for &i in &self.idx {
            sum = sum.wrapping_add(self.data[i as usize]);
        }
        sum
    }
}

fn setup_vec_read(p: &Params) -> SetupResult {
    let n = size(p);
    let mut r = SplitMix64::new(13);
    let idx = (0..n).map(|_| r.below(n as u64) as u32).collect();
    Ok((Box::new(VecRead { data: stream(12, n), idx }), work(n)))
}

// ---------------------------------------------------------------- maps (generic over the hasher)

struct MapInsert<S: BuildHasher + Default> {
    keys: Vec<u64>,
    m: HashMap<u64, u64, S>,
}

impl<S: BuildHasher + Default> Instance for MapInsert<S> {
    fn run(&mut self) -> u64 {
        let mut m: HashMap<u64, u64, S> = HashMap::default();
        for (i, &k) in self.keys.iter().enumerate() {
            m.insert(k, i as u64);
        }
        self.m = m;
        self.m.len() as u64
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        let mut u = Unordered::new();
        for (&k, &v) in &self.m {
            u.add(mix64(k) ^ v);
        }
        u.sum()
    }
}

fn map_insert<S: BuildHasher + Default + 'static>(p: &Params) -> SetupResult {
    let n = size(p);
    Ok((Box::new(MapInsert::<S> { keys: stream(14, n), m: HashMap::default() }), work(n)))
}

struct MapLookup<S: BuildHasher> {
    m: HashMap<u64, u64, S>,
    probes: Vec<u64>,
}

impl<S: BuildHasher> Instance for MapLookup<S> {
    fn run(&mut self) -> u64 {
        let (mut hits, mut sum) = (0u64, 0u64);
        for k in &self.probes {
            if let Some(&v) = self.m.get(k) {
                hits += 1;
                sum = sum.wrapping_add(v);
            }
        }
        (hits << 40) ^ sum
    }
}

fn map_lookup<S: BuildHasher + Default + 'static>(p: &Params) -> SetupResult {
    let n = size(p);
    let keys = stream(14, n);
    let mut m: HashMap<u64, u64, S> = HashMap::with_capacity_and_hasher(n, S::default());
    for (i, &k) in keys.iter().enumerate() {
        m.insert(k, i as u64);
    }
    let mut r = SplitMix64::new(15);
    let probes =
        (0..n).map(|i| if i % 2 == 0 { keys[r.below(n as u64) as usize] } else { r.next_u64() }).collect();
    Ok((Box::new(MapLookup { m, probes }), work(n)))
}

struct MapString<S: BuildHasher + Default> {
    tokens: Vec<&'static str>,
    m: HashMap<&'static str, u64, S>,
}

impl<S: BuildHasher + Default> Instance for MapString<S> {
    fn run(&mut self) -> u64 {
        let mut m: HashMap<&'static str, u64, S> = HashMap::default();
        for &t in &self.tokens {
            *m.entry(t).or_insert(0) += 1;
        }
        self.m = m;
        self.m.len() as u64
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        let mut u = Unordered::new();
        for (k, &v) in &self.m {
            u.add(fnv1a64(k.as_bytes()) ^ mix64(v));
        }
        u.sum()
    }
}

fn map_string<S: BuildHasher + Default + 'static>(p: &Params) -> SetupResult {
    let path = p.must_str("input");
    let text = std::fs::read_to_string(&path).map_err(|e| format!("{path}: {e}"))?;
    // Keys are views into the corpus, like Go's strings.Fields substrings.
    let text: &'static str = Box::leak(text.into_boxed_str());
    let tokens: Vec<&'static str> = text.split_whitespace().take(size(p)).collect();
    let n = tokens.len();
    Ok((Box::new(MapString::<S> { tokens, m: HashMap::default() }), work(n)))
}

struct SetOps<S: BuildHasher + Default> {
    a: Vec<u64>,
    b: Vec<u64>,
    _s: std::marker::PhantomData<S>,
}

impl<S: BuildHasher + Default> Instance for SetOps<S> {
    fn run(&mut self) -> u64 {
        let mut sa: HashSet<u64, S> = HashSet::default();
        for &k in &self.a {
            sa.insert(k);
        }
        let mut sb: HashSet<u64, S> = HashSet::default();
        for &k in &self.b {
            sb.insert(k);
        }
        let (small, large) = if sa.len() <= sb.len() { (&sa, &sb) } else { (&sb, &sa) };
        let inter = small.iter().filter(|k| large.contains(k)).count() as u64;
        (inter << 40) ^ ((sa.len() as u64) << 20) ^ sb.len() as u64
    }
}

fn set_ops<S: BuildHasher + Default + 'static>(p: &Params) -> SetupResult {
    let n = size(p);
    let draw = |seed| {
        let mut r = SplitMix64::new(seed);
        (0..n).map(|_| r.below(2 * n as u64)).collect::<Vec<u64>>()
    };
    Ok((Box::new(SetOps::<S> { a: draw(16), b: draw(17), _s: std::marker::PhantomData }), work(2 * n)))
}

// ---------------------------------------------------------------- queue

const QUEUE_WINDOW: usize = 1024;

struct Queue {
    n: usize,
}

impl Instance for Queue {
    fn run(&mut self) -> u64 {
        let mut q: VecDeque<u64> = VecDeque::new();
        let mut sum = 0u64;
        for i in 0..self.n {
            q.push_back(i as u64);
            if q.len() > QUEUE_WINDOW {
                sum = sum.wrapping_add(q.pop_front().unwrap());
            }
        }
        while let Some(x) = q.pop_front() {
            sum = sum.wrapping_add(x * 3);
        }
        sum
    }
}

fn setup_queue(p: &Params) -> SetupResult {
    let n = size(p);
    Ok((Box::new(Queue { n }), work(n)))
}

// ---------------------------------------------------------------- priority-queue

struct Pq {
    vals: Vec<u64>,
}

impl Instance for Pq {
    fn run(&mut self) -> u64 {
        let mut h: BinaryHeap<Reverse<u64>> = BinaryHeap::new();
        for &v in &self.vals {
            h.push(Reverse(v));
        }
        let mut d = Digest::new();
        while let Some(Reverse(v)) = h.pop() {
            d.add(v);
        }
        d.sum()
    }
}

fn setup_pq(p: &Params) -> SetupResult {
    let n = size(p);
    Ok((Box::new(Pq { vals: stream(18, n) }), work(n)))
}

// ---------------------------------------------------------------- sort-structs

#[derive(Clone, Copy, Default)]
struct Record {
    a: u64,
    b: u64,
    _c: u64,
    _d: u64,
}

struct SortStructs {
    orig: Vec<Record>,
    work: Vec<Record>,
}

impl Instance for SortStructs {
    fn prepare(&mut self) {
        self.work.copy_from_slice(&self.orig);
    }
    fn run(&mut self) -> u64 {
        self.work.sort_unstable_by(|x, y| x.a.cmp(&y.a).then(x.b.cmp(&y.b)));
        let n = self.work.len();
        self.work[0].b ^ self.work[n / 2].b ^ self.work[n - 1].b
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        let mut d = Digest::new();
        for r in &self.work {
            d.add(r.a);
            d.add(r.b);
        }
        d.sum()
    }
}

fn setup_sort_structs(p: &Params) -> SetupResult {
    let n = size(p);
    let mut r = SplitMix64::new(19);
    let kmax = (n / 4).max(1) as u64;
    let orig: Vec<Record> = (0..n)
        .map(|i| Record { a: r.below(kmax), b: i as u64, _c: r.next_u64(), _d: mix64(i as u64) })
        .collect();
    Ok((Box::new(SortStructs { orig, work: vec![Record::default(); n] }), work(n)))
}

fn main() {
    bench_common::main(
        "collections",
        &[
            Workload { name: "vec-push", mode: Mode::Iter, setup: setup_vec_push },
            Workload { name: "vec-random-read", mode: Mode::Iter, setup: setup_vec_read },
            Workload { name: "map-insert", mode: Mode::Iter, setup: map_insert::<RandomState> },
            Workload { name: "map-lookup", mode: Mode::Iter, setup: map_lookup::<RandomState> },
            Workload { name: "map-string", mode: Mode::Iter, setup: map_string::<RandomState> },
            Workload { name: "set-ops", mode: Mode::Iter, setup: set_ops::<RandomState> },
            Workload { name: "queue", mode: Mode::Iter, setup: setup_queue },
            Workload { name: "priority-queue", mode: Mode::Iter, setup: setup_pq },
            Workload { name: "sort-structs", mode: Mode::Iter, setup: setup_sort_structs },
            Workload { name: "map-insert-foldhash", mode: Mode::Iter, setup: map_insert::<Fold> },
            Workload { name: "map-lookup-foldhash", mode: Mode::Iter, setup: map_lookup::<Fold> },
            Workload { name: "map-string-foldhash", mode: Mode::Iter, setup: map_string::<Fold> },
            Workload { name: "set-ops-foldhash", mode: Mode::Iter, setup: set_ops::<Fold> },
        ],
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let g = bench_common::load_golden()["collections"].clone();
        let mut p = Params::default();
        p.0.insert("n".into(), g["n"].to_string());
        let mut ps = p.clone();
        ps.0.insert(
            "input".into(),
            bench_common::repo_root()
                .join(g["map_string"]["fixture"].as_str().unwrap())
                .display()
                .to_string(),
        );
        let check = |name: &str,
                     setup: bench_common::harness::SetupFn,
                     p: &Params,
                     want: &bench_common::serde_json::Value| {
            let (mut inst, _) = setup(p).unwrap();
            inst.prepare();
            let (run, chk) =
                if want.is_object() { (&want["run"], Some(&want["check"])) } else { (want, None) };
            assert_eq!(inst.run(), golden_hex(run), "{name} run");
            if let Some(c) = chk {
                assert_eq!(inst.check(), golden_hex(c), "{name} check");
            }
        };
        check("vec-push", setup_vec_push, &p, &g["vec_push"]);
        check("vec-random-read", setup_vec_read, &p, &g["vec_random_read"]);
        check("map-insert", map_insert::<RandomState>, &p, &g["map_insert"]);
        check("map-insert-foldhash", map_insert::<Fold>, &p, &g["map_insert"]);
        check("map-lookup", map_lookup::<RandomState>, &p, &g["map_lookup"]);
        check("map-lookup-foldhash", map_lookup::<Fold>, &p, &g["map_lookup"]);
        check("map-string", map_string::<RandomState>, &ps, &g["map_string"]);
        check("map-string-foldhash", map_string::<Fold>, &ps, &g["map_string"]);
        check("set-ops", set_ops::<RandomState>, &p, &g["set_ops"]);
        check("set-ops-foldhash", set_ops::<Fold>, &p, &g["set_ops"]);
        check("queue", setup_queue, &p, &g["queue"]);
        check("priority-queue", setup_pq, &p, &g["priority_queue"]);
        check("sort-structs", setup_sort_structs, &p, &g["sort_structs"]);
    }
}
