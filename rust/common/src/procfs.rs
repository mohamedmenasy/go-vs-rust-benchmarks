//! Process statistics, read exactly like go/internal/harness/procfs.go.

use std::fs;

fn status_field(text: &str, key: &str) -> i64 {
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix(key) {
            return rest.split_whitespace().next().and_then(|v| v.parse().ok()).unwrap_or(-1);
        }
    }
    -1
}

/// (VmRSS, VmHWM) in KiB from /proc/self/status.
pub fn mem_status() -> (i64, i64) {
    match fs::read_to_string("/proc/self/status") {
        Ok(t) => (status_field(&t, "VmRSS:"), status_field(&t, "VmHWM:")),
        Err(_) => (-1, -1),
    }
}

/// Number of OS threads in this process.
pub fn thread_count() -> i64 {
    match fs::read_to_string("/proc/self/status") {
        Ok(t) => status_field(&t, "Threads:"),
        Err(_) => -1,
    }
}

#[derive(Clone, Copy, Default, Debug)]
pub struct Rusage {
    pub utime_ns: i64,
    pub stime_ns: i64,
    pub minflt: i64,
    pub majflt: i64,
    pub nvcsw: i64,
    pub nivcsw: i64,
}

pub fn rusage() -> Rusage {
    // SAFETY: getrusage only writes into the zero-initialised struct we own.
    unsafe {
        let mut ru: libc::rusage = std::mem::zeroed();
        if libc::getrusage(libc::RUSAGE_SELF, &mut ru) != 0 {
            return Rusage::default();
        }
        Rusage {
            utime_ns: ru.ru_utime.tv_sec * 1_000_000_000 + ru.ru_utime.tv_usec * 1_000,
            stime_ns: ru.ru_stime.tv_sec * 1_000_000_000 + ru.ru_stime.tv_usec * 1_000,
            minflt: ru.ru_minflt,
            majflt: ru.ru_majflt,
            nvcsw: ru.ru_nvcsw,
            nivcsw: ru.ru_nivcsw,
        }
    }
}

impl Rusage {
    pub fn delta_json(&self, b: &Rusage) -> serde_json::Value {
        serde_json::json!({
            "utime_ns": b.utime_ns - self.utime_ns,
            "stime_ns": b.stime_ns - self.stime_ns,
            "minflt": b.minflt - self.minflt,
            "majflt": b.majflt - self.majflt,
            "nvcsw": b.nvcsw - self.nvcsw,
            "nivcsw": b.nivcsw - self.nivcsw,
        })
    }
}
