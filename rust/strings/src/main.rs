//! String processing on the shared text corpus, mirroring go/strings. The
//! corpus is read and UTF-8 validated in untimed setup.

use std::fmt::Write as _;

use bench_common::{Digest, Instance, Mode, Params, SplitMix64, Work, Workload, fnv1a64};
use regex::Regex;

type SetupResult = Result<(Box<dyn Instance>, Work), String>;

fn corpus(p: &Params) -> Result<(String, Work), String> {
    let path = p.must_str("input");
    let bytes = std::fs::read(&path).map_err(|e| format!("read {path}: {e}"))?;
    let n = bytes.len();
    let text = String::from_utf8(bytes).map_err(|e| e.to_string())?;
    Ok((text, Work { unit: "bytes", per_run: n as f64, input_bytes: n as u64 }))
}

// ---------------------------------------------------------------- concat

/// Append every token plus a separator to a String with no preallocation.
struct Concat {
    tokens: Vec<&'static str>,
    out: String,
}

impl Instance for Concat {
    fn run(&mut self) -> u64 {
        let mut b = String::new();
        for t in &self.tokens {
            b.push_str(t);
            b.push(';');
        }
        self.out = b;
        self.out.len() as u64
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        fnv1a64(self.out.as_bytes())
    }
}

fn setup_concat(p: &Params) -> SetupResult {
    let (text, work) = corpus(p)?;
    // Tokens are views into the corpus, exactly like Go's strings.Fields
    // substrings (the corpus is leaked to get 'static borrows; the process
    // exits after one run). Only the appends are timed.
    let text: &'static str = Box::leak(text.into_boxed_str());
    let tokens = text.split_whitespace().collect();
    Ok((Box::new(Concat { tokens, out: String::new() }), work))
}

// ---------------------------------------------------------------- format

const NAMES: [&str; 10] =
    ["alice", "bob", "carol", "dmitri", "eve", "françois", "gustav", "hiroshi", "ingrid", "jürgen"];

struct Format {
    n: usize,
    out: String,
}

impl Instance for Format {
    fn run(&mut self) -> u64 {
        let mut b = String::new();
        let mut r = SplitMix64::new(10);
        for i in 0..self.n {
            let score = r.below(1_000_000) as f64 / 7.0;
            writeln!(
                b,
                "id={} name={} score={:.2} active={}",
                r.next_u64(),
                NAMES[i % NAMES.len()],
                score,
                i % 3 == 0
            )
            .unwrap();
        }
        self.out = b;
        self.out.len() as u64
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        fnv1a64(self.out.as_bytes())
    }
}

fn setup_format(p: &Params) -> SetupResult {
    let n = p.int("records", 1_000_000) as usize;
    Ok((
        Box::new(Format { n, out: String::new() }),
        Work { unit: "records", per_run: n as f64, input_bytes: 0 },
    ))
}

// ---------------------------------------------------------------- search

const SEARCH_PATTERNS: [&str; 3] = [" the ", "benchmark", "λόγος"];

struct Search {
    text: String,
}

impl Instance for Search {
    fn run(&mut self) -> u64 {
        let mut d = Digest::new();
        for p in SEARCH_PATTERNS {
            d.add(self.text.matches(p).count() as u64);
        }
        d.sum()
    }
}

fn setup_search(p: &Params) -> SetupResult {
    let (text, work) = corpus(p)?;
    Ok((Box::new(Search { text }), work))
}

// ---------------------------------------------------------------- split

/// Lines then words. `split` collects each level into a Vec<&str> (Go:
/// strings.Split); `split-lazy` uses the iterators directly (Go: SplitSeq).
struct Split {
    text: String,
    lazy: bool,
}

impl Instance for Split {
    fn run(&mut self) -> u64 {
        let (mut tokens, mut total) = (0u64, 0u64);
        if self.lazy {
            for line in self.text.split('\n') {
                for word in line.split(' ') {
                    tokens += 1;
                    total += word.len() as u64;
                }
            }
        } else {
            let lines: Vec<&str> = self.text.split('\n').collect();
            for line in lines {
                let words: Vec<&str> = line.split(' ').collect();
                tokens += words.len() as u64;
                for word in &words {
                    total += word.len() as u64;
                }
            }
        }
        let mut d = Digest::new();
        d.add(tokens);
        d.add(total);
        d.sum()
    }
}

fn setup_split(p: &Params) -> SetupResult {
    let (text, work) = corpus(p)?;
    Ok((Box::new(Split { text, lazy: false }), work))
}

fn setup_split_lazy(p: &Params) -> SetupResult {
    let (text, work) = corpus(p)?;
    Ok((Box::new(Split { text, lazy: true }), work))
}

// ---------------------------------------------------------------- regex

/// Explicit ASCII classes: Rust's \d \w \b are Unicode-aware, Go's are ASCII.
const REGEX_PATTERNS: [&str; 3] =
    [r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", r"[0-9]{4}-[0-9]{2}-[0-9]{2}", r"(?:foo|bar|baz|qux)[0-9]+"];

struct Regexes {
    text: String,
    res: Vec<Regex>,
}

impl Instance for Regexes {
    fn run(&mut self) -> u64 {
        let mut d = Digest::new();
        for re in &self.res {
            let (mut n, mut starts) = (0u64, 0u64);
            for m in re.find_iter(&self.text) {
                n += 1;
                starts = starts.wrapping_add(m.start() as u64);
            }
            d.add(n);
            d.add(starts);
        }
        d.sum()
    }
}

fn setup_regex(p: &Params) -> SetupResult {
    let (text, work) = corpus(p)?;
    let res =
        REGEX_PATTERNS.iter().map(|p| Regex::new(p).map_err(|e| e.to_string())).collect::<Result<_, _>>()?;
    Ok((Box::new(Regexes { text, res }), work))
}

// ---------------------------------------------------------------- parse-numbers

struct ParseNumbers {
    ints: Vec<&'static str>,
    floats: Vec<&'static str>,
}

impl Instance for ParseNumbers {
    fn run(&mut self) -> u64 {
        let mut isum = 0u64;
        for s in &self.ints {
            isum = isum.wrapping_add(s.parse::<i64>().expect("int") as u64);
        }
        let mut fsum = 0.0f64;
        for s in &self.floats {
            fsum += s.parse::<f64>().expect("float");
        }
        let mut d = Digest::new();
        d.add(self.ints.len() as u64);
        d.add(isum);
        d.add(self.floats.len() as u64);
        d.add_f64(fsum);
        d.sum()
    }
}

fn is_int(s: &str) -> bool {
    let t = s.strip_prefix('-').unwrap_or(s);
    !t.is_empty() && t.bytes().all(|c| c.is_ascii_digit())
}

fn is_decimal(s: &str) -> bool {
    match s.split_once('.') {
        Some((ip, fp)) => is_int(ip) && !ip.starts_with('-') && is_int(fp) && !fp.starts_with('-'),
        None => false,
    }
}

fn setup_parse(p: &Params) -> SetupResult {
    let (text, work) = corpus(p)?;
    let text: &'static str = Box::leak(text.into_boxed_str()); // views, like Go substrings
    let (mut ints, mut floats) = (Vec::new(), Vec::new());
    for t in text.split_whitespace() {
        if is_int(t) {
            ints.push(t);
        } else if is_decimal(t) {
            floats.push(t);
        }
    }
    Ok((Box::new(ParseNumbers { ints, floats }), work))
}

// ---------------------------------------------------------------- unicode

struct CharCount {
    text: String,
}

impl Instance for CharCount {
    fn run(&mut self) -> u64 {
        self.text.chars().count() as u64
    }
}

fn setup_char_count(p: &Params) -> SetupResult {
    let (text, work) = corpus(p)?;
    Ok((Box::new(CharCount { text }), work))
}

/// Unicode upper-casing of the whole corpus (no SpecialCasing characters in
/// the corpus, so the result must equal Go's strings.ToUpper).
struct Upper {
    text: String,
    out: String,
}

impl Instance for Upper {
    fn run(&mut self) -> u64 {
        self.out = self.text.to_uppercase();
        self.out.len() as u64
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        fnv1a64(self.out.as_bytes())
    }
}

fn setup_upper(p: &Params) -> SetupResult {
    let (text, work) = corpus(p)?;
    Ok((Box::new(Upper { text, out: String::new() }), work))
}

fn main() {
    bench_common::main(
        "strings",
        &[
            Workload { name: "concat", mode: Mode::Iter, setup: setup_concat },
            Workload { name: "format", mode: Mode::Iter, setup: setup_format },
            Workload { name: "search", mode: Mode::Iter, setup: setup_search },
            Workload { name: "split", mode: Mode::Iter, setup: setup_split },
            Workload { name: "split-lazy", mode: Mode::Iter, setup: setup_split_lazy },
            Workload { name: "regex", mode: Mode::Iter, setup: setup_regex },
            Workload { name: "parse-numbers", mode: Mode::Iter, setup: setup_parse },
            Workload { name: "unicode-count", mode: Mode::Iter, setup: setup_char_count },
            Workload { name: "upper", mode: Mode::Iter, setup: setup_upper },
        ],
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let g = bench_common::load_golden()["strings"].clone();
        let mut p = Params::default();
        p.0.insert(
            "input".into(),
            bench_common::repo_root().join(g["fixture"].as_str().unwrap()).display().to_string(),
        );
        let run = |setup: bench_common::harness::SetupFn, p: &Params| {
            let (mut inst, _) = setup(p).unwrap();
            let r = inst.run();
            assert_eq!(inst.run(), r, "non-deterministic");
            let c = if inst.has_check() { inst.check() } else { 0 };
            (r, c)
        };
        let (r, c) = run(setup_concat, &p);
        assert_eq!((r, c), (g["concat"]["len"].as_u64().unwrap(), golden_hex(&g["concat"]["fnv1a64"])));
        let mut fp = Params::default();
        fp.0.insert("records".into(), g["format"]["records"].to_string());
        let (r, c) = run(setup_format, &fp);
        assert_eq!((r, c), (g["format"]["len"].as_u64().unwrap(), golden_hex(&g["format"]["fnv1a64"])));
        assert_eq!(run(setup_search, &p).0, golden_hex(&g["search"]));
        assert_eq!(run(setup_split, &p).0, golden_hex(&g["split"]));
        assert_eq!(run(setup_split_lazy, &p).0, golden_hex(&g["split"]));
        assert_eq!(run(setup_regex, &p).0, golden_hex(&g["regex"]));
        assert_eq!(run(setup_parse, &p).0, golden_hex(&g["parse_numbers"]));
        assert_eq!(run(setup_char_count, &p).0, g["unicode_count"].as_u64().unwrap());
        let (r, c) = run(setup_upper, &p);
        assert_eq!((r, c), (g["upper"]["len"].as_u64().unwrap(), golden_hex(&g["upper"]["fnv1a64"])));
    }
}
