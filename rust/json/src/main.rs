//! serde / serde_json benchmarks on the same documents as go/json. Every
//! operation is timed individually (op mode) for per-document latency
//! percentiles. The "-fast" workloads use sonic-rs (SIMD, serde-compatible)
//! against Go's goccy/go-json: the tuned track.

mod digest;
mod types;

use bench_common::{Instance, Mode, Params, Work, Workload, fnv1a64};
use serde_json::Value;

use types::{Response, User};

#[derive(Clone, Copy, PartialEq, Eq)]
enum Schema {
    Object,
    Array,
}

struct Doc {
    data: Vec<u8>,
    schema: Schema,
}

/// Which library does the work: serde_json (baseline) or sonic-rs (tuned).
#[derive(Clone, Copy, PartialEq, Eq)]
enum Codec {
    Serde,
    Sonic,
}

fn from_slice<T: serde::de::DeserializeOwned>(c: Codec, data: &[u8]) -> T {
    match c {
        Codec::Serde => serde_json::from_slice(data).expect("decode"),
        Codec::Sonic => sonic_rs::from_slice(data).expect("decode"),
    }
}

fn to_vec<T: serde::Serialize>(c: Codec, v: &T) -> Vec<u8> {
    match c {
        Codec::Serde => serde_json::to_vec(v).expect("encode"),
        Codec::Sonic => sonic_rs::to_vec(v).expect("encode"),
    }
}

fn load_doc(p: &Params) -> Result<(Doc, Work), String> {
    let path = p.must_str("input");
    let data = std::fs::read(&path).map_err(|e| format!("read {path}: {e}"))?;
    let schema = match p.str_or("schema", "object").as_str() {
        "object" => Schema::Object,
        "array" => Schema::Array,
        other => return Err(format!("unknown schema {other:?}")),
    };
    let n = data.len();
    Ok((Doc { data, schema }, Work { unit: "bytes", per_run: n as f64, input_bytes: n as u64 }))
}

// ---------------------------------------------------------------- decode (typed)

struct Decode {
    doc: Doc,
    codec: Codec,
    obj: Option<Response>,
    arr: Option<Vec<User>>,
}

impl Instance for Decode {
    fn run(&mut self) -> u64 {
        match self.doc.schema {
            Schema::Object => {
                let v: Response = from_slice(self.codec, &self.doc.data);
                let r = ((v.items.len() as u64) << 32) ^ v.total as u64;
                self.obj = Some(v);
                r
            }
            Schema::Array => {
                let v: Vec<User> = from_slice(self.codec, &self.doc.data);
                let r = ((v.len() as u64) << 32) ^ v[v.len() - 1].id as u64;
                self.arr = Some(v);
                r
            }
        }
    }
    fn has_check(&self) -> bool {
        true
    }
    /// Re-encoding must reproduce the input exactly; then digest every field.
    fn check(&mut self) -> u64 {
        let (out, dg) = match self.doc.schema {
            Schema::Object => {
                let v = self.obj.as_ref().unwrap();
                (to_vec(self.codec, v), digest::response(v))
            }
            Schema::Array => {
                let v = self.arr.as_ref().unwrap();
                (to_vec(self.codec, v), digest::users(v))
            }
        };
        assert!(out == self.doc.data, "re-encoded document differs from the input");
        dg
    }
}

fn decode_with(p: &Params, codec: Codec) -> Result<(Box<dyn Instance>, Work), String> {
    let (doc, work) = load_doc(p)?;
    Ok((Box::new(Decode { doc, codec, obj: None, arr: None }), work))
}

fn setup_decode(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    decode_with(p, Codec::Serde)
}

fn setup_decode_fast(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    decode_with(p, Codec::Sonic)
}

// ---------------------------------------------------------------- encode (typed)

struct Encode {
    doc: Doc,
    codec: Codec,
    obj: Option<Response>,
    arr: Option<Vec<User>>,
    out: Vec<u8>,
}

impl Instance for Encode {
    fn run(&mut self) -> u64 {
        let out = match self.doc.schema {
            Schema::Object => to_vec(self.codec, self.obj.as_ref().unwrap()),
            Schema::Array => to_vec(self.codec, self.arr.as_ref().unwrap()),
        };
        let n = out.len() as u64;
        self.out = out;
        n
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        assert!(self.out == self.doc.data, "encoded document differs from the input");
        fnv1a64(&self.out)
    }
}

fn encode_with(p: &Params, codec: Codec) -> Result<(Box<dyn Instance>, Work), String> {
    let (doc, work) = load_doc(p)?;
    let (obj, arr) = match doc.schema {
        Schema::Object => (Some(serde_json::from_slice(&doc.data).map_err(|e| e.to_string())?), None),
        Schema::Array => (None, Some(serde_json::from_slice(&doc.data).map_err(|e| e.to_string())?)),
    };
    Ok((Box::new(Encode { doc, codec, obj, arr, out: Vec::new() }), work))
}

fn setup_encode(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    encode_with(p, Codec::Serde)
}

fn setup_encode_fast(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    encode_with(p, Codec::Sonic)
}

// ---------------------------------------------------------------- decode-dynamic

struct Dynamic {
    doc: Doc,
    last: Value,
}

impl Instance for Dynamic {
    fn run(&mut self) -> u64 {
        let v: Value = serde_json::from_slice(&self.doc.data).expect("decode");
        let n = match &v {
            Value::Object(m) => m.len() as u64,
            Value::Array(a) => a.len() as u64,
            _ => 0,
        };
        self.last = v;
        n
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        digest::dynamic(&self.last)
    }
}

fn setup_dynamic(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let (doc, work) = load_doc(p)?;
    Ok((Box::new(Dynamic { doc, last: Value::Null }), work))
}

fn main() {
    bench_common::main(
        "json",
        &[
            Workload { name: "decode", mode: Mode::Op, setup: setup_decode },
            Workload { name: "encode", mode: Mode::Op, setup: setup_encode },
            Workload { name: "decode-dynamic", mode: Mode::Op, setup: setup_dynamic },
            Workload { name: "decode-fast", mode: Mode::Op, setup: setup_decode_fast },
            Workload { name: "encode-fast", mode: Mode::Op, setup: setup_encode_fast },
        ],
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let g = bench_common::load_golden()["json"].clone();
        for (schema, c) in g.as_object().unwrap() {
            let path = bench_common::repo_root().join(c["fixture"].as_str().unwrap());
            let mut p = Params::default();
            p.0.insert("input".into(), path.display().to_string());
            p.0.insert("schema".into(), schema.clone());
            for (name, setup, want) in [
                ("decode", setup_decode as bench_common::harness::SetupFn, &c["typed_digest"]),
                ("encode", setup_encode, &c["fnv1a64"]),
                ("decode-dynamic", setup_dynamic, &c["dynamic_digest"]),
                ("decode-fast", setup_decode_fast, &c["typed_digest"]),
                ("encode-fast", setup_encode_fast, &c["fnv1a64"]),
            ] {
                let (mut inst, _) = setup(&p).unwrap();
                let r = inst.run();
                assert_eq!(inst.run(), r, "{schema}/{name}: non-deterministic");
                assert_eq!(inst.check(), golden_hex(want), "{schema}/{name}");
            }
        }
    }
}
