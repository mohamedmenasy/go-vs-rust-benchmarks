//! File I/O workloads, mirroring go/io. Opening, reading or writing, and
//! closing the file are all timed; the page cache is warm unless a workload
//! asks to drop it (drop_caches=1, requires root).

use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Read, Write};
use std::path::PathBuf;

use bench_common::{Digest, Instance, Mode, Params, Work, Workload, random_bytes};

const RAW_CHUNK: usize = 1 << 20; // raw read/write syscall size
const BUF_SIZE: usize = 64 << 10; // buffered reader/writer capacity (explicit in both languages)
const APP_READ: usize = 512; // application read size through the buffered reader
const REC_SIZE: usize = 100; // record size for buffered writes
const PAGE: u64 = 4096; // sampling stride of the content digest

/// One byte per 4 KiB page, weighted by page index, plus the total length
/// (identical to go/io/io.go `pageSampler`).
#[derive(Default)]
struct PageSampler {
    off: u64,
    acc: u64,
}

impl PageSampler {
    #[inline]
    fn feed(&mut self, b: &[u8]) {
        let first = (self.off + PAGE - 1) & !(PAGE - 1);
        let end = self.off + b.len() as u64;
        let mut p = first;
        while p < end {
            self.acc = self.acc.wrapping_add(b[(p - self.off) as usize] as u64 * (p / PAGE + 1));
            p += PAGE;
        }
        self.off = end;
    }
    fn sum(&self) -> u64 {
        let mut d = Digest::new();
        d.add(self.off);
        d.add(self.acc);
        d.sum()
    }
}

fn drop_caches() {
    fs::write("/proc/sys/vm/drop_caches", "1").unwrap_or_else(|e| panic!("drop_caches (needs root): {e}"));
}

fn file_size(path: &str) -> Result<u64, String> {
    fs::metadata(path).map(|m| m.len()).map_err(|e| format!("{path}: {e}"))
}

// ---------------------------------------------------------------- reads

struct ReadW {
    path: String,
    buf: Vec<u8>,
    buffered: bool,
    cold: bool,
}

impl Instance for ReadW {
    fn prepare(&mut self) {
        if self.cold {
            drop_caches();
        }
    }
    fn run(&mut self) -> u64 {
        let f = File::open(&self.path).expect("open");
        let mut s = PageSampler::default();
        if self.buffered {
            let mut r = BufReader::with_capacity(BUF_SIZE, f);
            let chunk = &mut self.buf[..APP_READ];
            loop {
                let n = r.read(chunk).expect("read");
                if n == 0 {
                    break;
                }
                s.feed(&chunk[..n]);
            }
        } else {
            let mut f = f;
            loop {
                let n = f.read(&mut self.buf).expect("read");
                if n == 0 {
                    break;
                }
                s.feed(&self.buf[..n]);
            }
        }
        s.sum()
    }
}

fn new_read(p: &Params, buffered: bool) -> Result<(Box<dyn Instance>, Work), String> {
    let path = p.must_str("input");
    let n = file_size(&path)?;
    Ok((
        Box::new(ReadW { path, buf: vec![0; RAW_CHUNK], buffered, cold: p.bool("drop_caches", false) }),
        Work { unit: "bytes", per_run: n as f64, input_bytes: n },
    ))
}

fn setup_read_seq(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    new_read(p, false)
}

fn setup_read_buffered(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    new_read(p, true)
}

// ---------------------------------------------------------------- writes

struct WriteW {
    path: PathBuf,
    total: u64,
    block: Vec<u8>,
    buffered: bool,
    fsync: bool,
}

impl Instance for WriteW {
    fn prepare(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
    fn run(&mut self) -> u64 {
        let f = File::create(&self.path).expect("create");
        let mut s = PageSampler::default();
        let step = if self.buffered { REC_SIZE as u64 } else { RAW_CHUNK as u64 };
        let blen = self.block.len() as u64;
        let mut written = 0u64;
        let mut emit = |out: &mut dyn Write, written: &mut u64| {
            while *written < self.total {
                let mut n = step.min(self.total - *written);
                let o = *written % blen;
                if o + n > blen {
                    n = blen - o;
                }
                let b = &self.block[o as usize..(o + n) as usize];
                out.write_all(b).expect("write");
                s.feed(b);
                *written += n;
            }
        };
        let f = if self.buffered {
            let mut bw = BufWriter::with_capacity(BUF_SIZE, f);
            emit(&mut bw, &mut written);
            bw.into_inner().expect("flush")
        } else {
            let mut f = f;
            emit(&mut f, &mut written);
            f
        };
        if self.fsync {
            f.sync_all().expect("fsync");
        }
        drop(f);
        s.sum()
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        fs::metadata(&self.path).expect("stat").len()
    }
    fn has_teardown(&self) -> bool {
        true
    }
    fn teardown(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

fn new_write(p: &Params, buffered: bool) -> Result<(Box<dyn Instance>, Work), String> {
    let total = p.int("bytes", 100 << 20) as u64;
    let dir = PathBuf::from(p.str_or("dir", "scratch/io"));
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let w = WriteW {
        path: dir.join(format!("rust-{}.dat", std::process::id())),
        total,
        block: random_bytes(p.int("seed", 8) as u64, RAW_CHUNK),
        buffered,
        fsync: p.bool("fsync", false),
    };
    Ok((Box::new(w), Work { unit: "bytes", per_run: total as f64, input_bytes: 0 }))
}

fn setup_write_seq(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    new_write(p, false)
}

fn setup_write_buffered(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    new_write(p, true)
}

// ---------------------------------------------------------------- lines

struct LinesW {
    path: String,
    idiomatic: bool,
    cold: bool,
}

fn parse_uint(b: &[u8]) -> u64 {
    let mut v = 0u64;
    for &c in b {
        v = v * 10 + (c - b'0') as u64;
    }
    v
}

/// The i-th comma-separated field of `line`.
fn field(line: &[u8], mut i: usize) -> &[u8] {
    let mut start = 0;
    for (k, &c) in line.iter().enumerate() {
        if c == b',' {
            if i == 0 {
                return &line[start..k];
            }
            i -= 1;
            start = k + 1;
        }
    }
    &line[start..]
}

#[derive(Default)]
struct LineAgg {
    lines: u64,
    bytes: u64,
    n5xx: u64,
}

impl LineAgg {
    fn add(&mut self, status: u64, size: u64) {
        self.lines += 1;
        self.bytes += size;
        if status >= 500 {
            self.n5xx += 1;
        }
    }
    fn sum(&self) -> u64 {
        let mut d = Digest::new();
        d.add(self.lines);
        d.add(self.bytes);
        d.add(self.n5xx);
        d.sum()
    }
}

impl Instance for LinesW {
    fn prepare(&mut self) {
        if self.cold {
            drop_caches();
        }
    }
    fn run(&mut self) -> u64 {
        let f = File::open(&self.path).expect("open");
        let mut r = BufReader::with_capacity(BUF_SIZE, f);
        let mut agg = LineAgg::default();
        if !self.idiomatic {
            // One reused line buffer (Go: bufio.Scanner.Bytes).
            let mut line = Vec::with_capacity(256);
            r.read_until(b'\n', &mut line).expect("header");
            loop {
                line.clear();
                if r.read_until(b'\n', &mut line).expect("read") == 0 {
                    break;
                }
                let l = line.strip_suffix(b"\n").unwrap_or(&line);
                if l.is_empty() {
                    continue;
                }
                agg.add(parse_uint(field(l, 3)), parse_uint(field(l, 5)));
            }
        } else {
            // Idiomatic: BufRead::lines (a String per line, UTF-8 checked),
            // split(',').collect(), str::parse.
            for line in r.lines().skip(1) {
                let line = line.expect("read");
                let parts: Vec<&str> = line.split(',').collect();
                let status: u64 = parts[3].parse().expect("status");
                let size: u64 = parts[5].parse().expect("bytes");
                agg.add(status, size);
            }
        }
        agg.sum()
    }
}

fn new_lines(p: &Params, idiomatic: bool) -> Result<(Box<dyn Instance>, Work), String> {
    let path = p.must_str("input");
    let n = file_size(&path)?;
    Ok((
        Box::new(LinesW { path, idiomatic, cold: p.bool("drop_caches", false) }),
        Work { unit: "bytes", per_run: n as f64, input_bytes: n },
    ))
}

fn setup_lines(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    new_lines(p, false)
}

fn setup_lines_idiomatic(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    new_lines(p, true)
}

fn main() {
    bench_common::main(
        "io",
        &[
            Workload { name: "read-seq", mode: Mode::Iter, setup: setup_read_seq },
            Workload { name: "read-buffered", mode: Mode::Iter, setup: setup_read_buffered },
            Workload { name: "write-seq", mode: Mode::Iter, setup: setup_write_seq },
            Workload { name: "write-buffered", mode: Mode::Iter, setup: setup_write_buffered },
            Workload { name: "lines", mode: Mode::Iter, setup: setup_lines },
            Workload { name: "lines-idiomatic", mode: Mode::Iter, setup: setup_lines_idiomatic },
        ],
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use bench_common::golden_hex;

    fn params(kv: &[(&str, String)]) -> Params {
        let mut p = Params::default();
        for (k, v) in kv {
            p.0.insert(k.to_string(), v.clone());
        }
        p
    }

    #[test]
    fn matches_golden() {
        let g = bench_common::load_golden()["io"].clone();
        let dir = std::env::temp_dir().join(format!("bench-io-test-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let input = dir.join("in.bin");
        let rd = &g["read"];
        fs::write(&input, random_bytes(rd["seed"].as_u64().unwrap(), rd["n"].as_u64().unwrap() as usize))
            .unwrap();
        for setup in [setup_read_seq as bench_common::harness::SetupFn, setup_read_buffered] {
            let (mut inst, _) = setup(&params(&[("input", input.display().to_string())])).unwrap();
            assert_eq!(inst.run(), golden_hex(&rd["digest"]));
        }
        let wr = &g["write"];
        for setup in [setup_write_seq as bench_common::harness::SetupFn, setup_write_buffered] {
            let (mut inst, _) = setup(&params(&[
                ("bytes", wr["bytes"].to_string()),
                ("seed", wr["seed"].to_string()),
                ("dir", dir.display().to_string()),
            ]))
            .unwrap();
            inst.prepare();
            assert_eq!(inst.run(), golden_hex(&wr["digest"]));
            assert_eq!(inst.check(), wr["bytes"].as_u64().unwrap());
            inst.teardown();
        }
        let ln = &g["lines"];
        let fixture = bench_common::repo_root().join(ln["fixture"].as_str().unwrap());
        for setup in [setup_lines as bench_common::harness::SetupFn, setup_lines_idiomatic] {
            let (mut inst, _) = setup(&params(&[("input", fixture.display().to_string())])).unwrap();
            assert_eq!(inst.run(), golden_hex(&ln["digest"]));
        }
        fs::remove_dir_all(&dir).unwrap();
    }
}
