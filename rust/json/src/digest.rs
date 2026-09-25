//! Digests of decoded documents, identical to go/json/digest.go. Computed
//! only in untimed checks.

use bench_common::{Digest, Unordered, fnv1a64};
use serde_json::Value;

use crate::types::{Response, User};

fn add_opt(d: &mut Digest, s: &Option<String>) {
    match s {
        None => d.add(0),
        Some(s) => {
            d.add(1);
            d.add_str(s);
        }
    }
}

fn add_tags(d: &mut Digest, tags: &[String]) {
    d.add(tags.len() as u64);
    for t in tags {
        d.add_str(t);
    }
}

pub fn response(r: &Response) -> u64 {
    let mut d = Digest::new();
    d.add_str(&r.request_id);
    d.add_str(&r.status);
    d.add(r.page as u64);
    d.add(r.per_page as u64);
    d.add(r.total as u64);
    d.add_str(&r.generated_at);
    d.add(r.items.len() as u64);
    for it in &r.items {
        d.add(it.id as u64);
        d.add_str(&it.sku);
        d.add_str(&it.name);
        d.add_str(&it.description);
        d.add_f64(it.price);
        d.add(it.quantity as u64);
        d.add(it.in_stock as u64);
        d.add_f64(it.rating);
        add_tags(&mut d, &it.tags);
        d.add_f64(it.dimensions.width);
        d.add_f64(it.dimensions.height);
        d.add_f64(it.dimensions.depth);
        add_opt(&mut d, &it.supplier);
    }
    d.add_str(&r.meta.region);
    d.add(r.meta.cache_hit as u64);
    d.add_f64(r.meta.latency_ms);
    add_tags(&mut d, &r.meta.tags);
    d.sum()
}

pub fn users(us: &[User]) -> u64 {
    let mut d = Digest::new();
    d.add(us.len() as u64);
    for u in us {
        d.add(u.id as u64);
        d.add_str(&u.username);
        d.add_str(&u.email);
        d.add(u.age as u64);
        d.add_f64(u.score);
        d.add(u.active as u64);
        add_tags(&mut d, &u.roles);
        d.add_str(&u.address.street);
        d.add_str(&u.address.city);
        d.add_str(&u.address.zip);
        d.add_f64(u.address.geo.lat);
        d.add_f64(u.address.geo.lng);
        d.add_str(&u.created_at);
        add_opt(&mut d, &u.bio);
    }
    d.sum()
}

const TAG_OBJ: u64 = 1 << 56;
const TAG_ARR: u64 = 2 << 56;
const TAG_KEY: u64 = 3 << 56;
const TAG_STR: u64 = 4 << 56;
const TAG_NUM: u64 = 5 << 56;
const TAG_TRUE: u64 = 6 << 56;
const TAG_FALSE: u64 = 7 << 56;
const TAG_NULL: u64 = 8 << 56;

/// Order-independent structural digest; numbers are compared as f64 because
/// Go's `any` decoding produces float64 for every number.
pub fn dynamic(v: &Value) -> u64 {
    fn walk(u: &mut Unordered, x: &Value) {
        match x {
            Value::Object(m) => {
                u.add(TAG_OBJ ^ m.len() as u64);
                for (k, val) in m {
                    u.add(TAG_KEY ^ fnv1a64(k.as_bytes()));
                    walk(u, val);
                }
            }
            Value::Array(a) => {
                u.add(TAG_ARR ^ a.len() as u64);
                for val in a {
                    walk(u, val);
                }
            }
            Value::String(s) => u.add(TAG_STR ^ fnv1a64(s.as_bytes())),
            Value::Number(n) => u.add(TAG_NUM ^ n.as_f64().expect("finite number").to_bits()),
            Value::Bool(true) => u.add(TAG_TRUE),
            Value::Bool(false) => u.add(TAG_FALSE),
            Value::Null => u.add(TAG_NULL),
        }
    }
    let mut u = Unordered::new();
    walk(&mut u, v);
    u.sum()
}
