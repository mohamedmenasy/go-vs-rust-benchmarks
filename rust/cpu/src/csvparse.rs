//! Parse an in-memory request log (ts,user_id,endpoint,status,latency_ms,
//! bytes) and aggregate per endpoint (mirror of go/cpu/csvparse.go). The file
//! is read and UTF-8 validated during setup; the timed work is scanning lines
//! and fields, parsing integers and decimals, and updating a string-keyed map
//! (std HashMap with its default SipHash-1-3 hasher: the baseline).

use std::collections::HashMap;

use bench_common::{Digest, Instance, Params, Work};

#[derive(Default)]
struct Agg {
    count: u64,
    lat_sum: f64,
    lat_max: f64,
    bytes: u64,
    n4xx: u64,
    n5xx: u64,
}

fn int(s: &str) -> i64 {
    s.parse().expect("integer field")
}

pub fn aggregate(data: &str) -> u64 {
    let mut aggs: HashMap<String, Agg> = HashMap::new();
    let mut rows = 0u64;
    let rest = data.split_once('\n').map_or("", |(_, r)| r); // header
    for line in rest.split('\n') {
        if line.is_empty() {
            continue;
        }
        let mut f = line.split(',');
        let (ts, user, ep, status, lat, size) = (
            f.next().unwrap(),
            f.next().unwrap(),
            f.next().unwrap(),
            f.next().unwrap(),
            f.next().unwrap(),
            f.next().unwrap(),
        );
        let _ = int(ts);
        let _ = int(user);
        let status = int(status);
        let lat: f64 = lat.parse().expect("decimal field");
        let size = int(size);
        let update = |a: &mut Agg| {
            a.count += 1;
            a.lat_sum += lat;
            if lat > a.lat_max {
                a.lat_max = lat;
            }
            a.bytes += size as u64;
            if (400..500).contains(&status) {
                a.n4xx += 1;
            } else if status >= 500 {
                a.n5xx += 1;
            }
        };
        // One hash lookup on the hit path, like Go's `aggs[ep]`; the key is
        // only allocated the first time an endpoint is seen.
        if let Some(a) = aggs.get_mut(ep) {
            update(a);
        } else {
            let mut a = Agg::default();
            update(&mut a);
            aggs.insert(ep.to_string(), a);
        }
        rows += 1;
    }
    let mut keys: Vec<&String> = aggs.keys().collect();
    keys.sort();
    let mut d = Digest::new();
    for k in keys {
        let a = &aggs[k];
        d.add_str(k);
        d.add(a.count);
        d.add_f64(a.lat_sum);
        d.add_f64(a.lat_max);
        d.add(a.bytes);
        d.add(a.n4xx);
        d.add(a.n5xx);
    }
    d.add(rows);
    d.sum()
}

struct CsvParse {
    data: String,
}

impl Instance for CsvParse {
    fn run(&mut self) -> u64 {
        aggregate(&self.data)
    }
}

pub fn setup(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let path = p.must_str("input");
    let bytes = std::fs::read(&path).map_err(|e| format!("read {path}: {e}"))?;
    let n = bytes.len();
    let data = String::from_utf8(bytes).map_err(|e| format!("{path}: {e}"))?;
    Ok((Box::new(CsvParse { data }), Work { unit: "bytes", per_run: n as f64, input_bytes: n as u64 }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{golden_cpu, params, run_once};
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let c = &golden_cpu()["csvparse"];
        let path = bench_common::repo_root().join(c["fixture"].as_str().unwrap());
        let (mut inst, _) = setup(&params(&[("input", path.display().to_string())])).unwrap();
        assert_eq!(run_once(&mut inst).0, golden_hex(&c["digest"]));
    }
}
