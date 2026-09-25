//! Global allocator selection and (optional) allocation counting.
//!
//! * default build: the system allocator (glibc malloc), untouched.
//! * `mimalloc` feature: mimalloc (tuned track).
//! * `alloc-stats` feature: wraps whichever allocator is active and counts
//!   every allocation. This adds atomic operations to every malloc/free, so it
//!   is only used by the separate allocation-profile pass, never for timing.
//!
//! Counting semantics mirror Go's MemStats: a `realloc` is counted as a new
//! allocation of the new size plus a free of the old one (Go's `append`
//! allocates a new backing array the same way).

use serde_json::{Value, json};

#[cfg(feature = "alloc-stats")]
mod counting {
    use std::alloc::{GlobalAlloc, Layout};
    use std::sync::atomic::{AtomicI64, AtomicU64, Ordering::Relaxed};

    pub static ALLOCS: AtomicU64 = AtomicU64::new(0);
    pub static DEALLOCS: AtomicU64 = AtomicU64::new(0);
    pub static REALLOCS: AtomicU64 = AtomicU64::new(0);
    pub static ALLOC_BYTES: AtomicU64 = AtomicU64::new(0);
    pub static DEALLOC_BYTES: AtomicU64 = AtomicU64::new(0);
    pub static LIVE: AtomicI64 = AtomicI64::new(0);
    pub static PEAK: AtomicI64 = AtomicI64::new(0);

    pub struct Counting<A>(pub A);

    #[inline]
    fn grew(n: usize) {
        let live = LIVE.fetch_add(n as i64, Relaxed) + n as i64;
        PEAK.fetch_max(live, Relaxed);
    }

    unsafe impl<A: GlobalAlloc> GlobalAlloc for Counting<A> {
        unsafe fn alloc(&self, l: Layout) -> *mut u8 {
            let p = unsafe { self.0.alloc(l) };
            if !p.is_null() {
                ALLOCS.fetch_add(1, Relaxed);
                ALLOC_BYTES.fetch_add(l.size() as u64, Relaxed);
                grew(l.size());
            }
            p
        }
        unsafe fn alloc_zeroed(&self, l: Layout) -> *mut u8 {
            let p = unsafe { self.0.alloc_zeroed(l) };
            if !p.is_null() {
                ALLOCS.fetch_add(1, Relaxed);
                ALLOC_BYTES.fetch_add(l.size() as u64, Relaxed);
                grew(l.size());
            }
            p
        }
        unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
            unsafe { self.0.dealloc(p, l) };
            DEALLOCS.fetch_add(1, Relaxed);
            DEALLOC_BYTES.fetch_add(l.size() as u64, Relaxed);
            LIVE.fetch_sub(l.size() as i64, Relaxed);
        }
        unsafe fn realloc(&self, p: *mut u8, l: Layout, new_size: usize) -> *mut u8 {
            let q = unsafe { self.0.realloc(p, l, new_size) };
            if !q.is_null() {
                REALLOCS.fetch_add(1, Relaxed);
                ALLOC_BYTES.fetch_add(new_size as u64, Relaxed);
                DEALLOC_BYTES.fetch_add(l.size() as u64, Relaxed);
                LIVE.fetch_sub(l.size() as i64, Relaxed);
                grew(new_size);
            }
            q
        }
    }
}

#[cfg(all(feature = "alloc-stats", not(feature = "mimalloc")))]
#[global_allocator]
static GLOBAL: counting::Counting<std::alloc::System> = counting::Counting(std::alloc::System);

#[cfg(all(feature = "alloc-stats", feature = "mimalloc"))]
#[global_allocator]
static GLOBAL: counting::Counting<mimalloc::MiMalloc> = counting::Counting(mimalloc::MiMalloc);

#[cfg(all(not(feature = "alloc-stats"), feature = "mimalloc"))]
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

pub fn allocator_name() -> &'static str {
    if cfg!(feature = "mimalloc") { "mimalloc" } else { "system (glibc malloc)" }
}

pub fn counting_enabled() -> bool {
    cfg!(feature = "alloc-stats")
}

#[derive(Clone, Copy, Default, Debug)]
pub struct Snapshot {
    pub allocs: u64,
    pub deallocs: u64,
    pub reallocs: u64,
    pub alloc_bytes: u64,
    pub dealloc_bytes: u64,
    pub live: i64,
}

/// Current counters (all zero when counting is disabled).
pub fn snapshot() -> Snapshot {
    #[cfg(feature = "alloc-stats")]
    {
        use std::sync::atomic::Ordering::Relaxed;
        Snapshot {
            allocs: counting::ALLOCS.load(Relaxed),
            deallocs: counting::DEALLOCS.load(Relaxed),
            reallocs: counting::REALLOCS.load(Relaxed),
            alloc_bytes: counting::ALLOC_BYTES.load(Relaxed),
            dealloc_bytes: counting::DEALLOC_BYTES.load(Relaxed),
            live: counting::LIVE.load(Relaxed),
        }
    }
    #[cfg(not(feature = "alloc-stats"))]
    {
        Snapshot::default()
    }
}

/// Restart peak tracking from the current live size.
pub fn reset_peak() {
    #[cfg(feature = "alloc-stats")]
    {
        use std::sync::atomic::Ordering::Relaxed;
        counting::PEAK.store(counting::LIVE.load(Relaxed), Relaxed);
    }
}

fn peak() -> i64 {
    #[cfg(feature = "alloc-stats")]
    {
        counting::PEAK.load(std::sync::atomic::Ordering::Relaxed)
    }
    #[cfg(not(feature = "alloc-stats"))]
    {
        0
    }
}

/// Allocation activity between two snapshots, in the same vocabulary the Go
/// harness uses for MemStats deltas.
pub fn delta_json(a: &Snapshot, b: &Snapshot) -> Value {
    if !counting_enabled() {
        return json!({ "runtime": "rust", "allocator": allocator_name(), "alloc_stats": false });
    }
    json!({
        "runtime": "rust",
        "allocator": allocator_name(),
        "alloc_stats": true,
        "alloc_calls": b.allocs - a.allocs,
        "realloc_calls": b.reallocs - a.reallocs,
        "dealloc_calls": b.deallocs - a.deallocs,
        "alloc_objects": (b.allocs - a.allocs) + (b.reallocs - a.reallocs),
        "free_objects": (b.deallocs - a.deallocs) + (b.reallocs - a.reallocs),
        "alloc_bytes": b.alloc_bytes - a.alloc_bytes,
        "dealloc_bytes": b.dealloc_bytes - a.dealloc_bytes,
        "live_bytes_start": a.live,
        "live_bytes_end": b.live,
        "peak_live_bytes": peak(),
    })
}
