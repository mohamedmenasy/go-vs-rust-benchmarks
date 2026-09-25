//! Cross-language primitives must match spec/golden.json exactly.

use bench_common::{Digest, SplitMix64, Unordered, fnv1a64, golden_hex, hist, load_golden, mix64};

#[test]
fn splitmix64_matches_golden() {
    let g = load_golden();
    let sm = &g["splitmix64"];
    let streams = sm["streams"].as_array().unwrap();
    assert!(!streams.is_empty());
    for s in streams {
        let mut r = SplitMix64::new(golden_hex(&s["seed"]));
        for want in s["next"].as_array().unwrap() {
            assert_eq!(r.next_u64(), golden_hex(want), "seed {}", s["seed"]);
        }
    }
    for b in sm["below"].as_array().unwrap() {
        let mut r = SplitMix64::new(golden_hex(&b["seed"]));
        let n = b["n"].as_u64().unwrap();
        for want in b["values"].as_array().unwrap() {
            assert_eq!(r.below(n), want.as_u64().unwrap());
        }
    }
    for f in sm["float64"].as_array().unwrap() {
        let mut r = SplitMix64::new(golden_hex(&f["seed"]));
        for want in f["bits"].as_array().unwrap() {
            assert_eq!(r.float64().to_bits(), golden_hex(want));
        }
    }
}

#[test]
fn digests_match_golden() {
    let g = load_golden();
    let d = &g["digest"];
    for c in d["fnv1a64"].as_array().unwrap() {
        let input = c["input"].as_str().unwrap();
        assert_eq!(fnv1a64(input.as_bytes()), golden_hex(&c["hash"]), "{input:?}");
    }
    for c in d["mix64"].as_array().unwrap() {
        assert_eq!(mix64(golden_hex(&c["in"])), golden_hex(&c["out"]));
    }
    for c in d["ordered"].as_array().unwrap() {
        let mut dg = Digest::new();
        for w in c["words"].as_array().unwrap() {
            dg.add(golden_hex(w));
        }
        assert_eq!(dg.sum(), golden_hex(&c["sum"]));
    }
    for c in d["unordered"].as_array().unwrap() {
        let mut u = Unordered::new();
        for w in c["words"].as_array().unwrap().iter().rev() {
            u.add(golden_hex(w));
        }
        assert_eq!(u.sum(), golden_hex(&c["sum"]));
    }
}

#[test]
fn histogram_buckets_match_golden() {
    let g = load_golden();
    let cases = g["histogram"].as_array().unwrap();
    assert!(!cases.is_empty());
    for c in cases {
        let v = golden_hex(&c["value"]);
        let b = hist::bucket(v);
        assert_eq!(b as u64, c["bucket"].as_u64().unwrap(), "value {v}");
        assert!(b < hist::BUCKETS);
    }
}
