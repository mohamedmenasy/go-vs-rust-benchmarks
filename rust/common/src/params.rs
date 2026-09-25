//! `--param key=value` pairs, mirroring go/internal/harness/params.go.

use std::collections::BTreeMap;

#[derive(Clone, Debug, Default)]
pub struct Params(pub BTreeMap<String, String>);

impl Params {
    pub fn str_or(&self, key: &str, def: &str) -> String {
        self.0.get(key).cloned().unwrap_or_else(|| def.to_string())
    }

    /// A required string parameter.
    pub fn must_str(&self, key: &str) -> String {
        match self.0.get(key) {
            Some(v) if !v.is_empty() => v.clone(),
            _ => panic!("missing required param {key:?}"),
        }
    }

    /// An integer parameter (underscores allowed). Panics when malformed: a
    /// bad parameter is a harness bug, never a data point.
    pub fn int(&self, key: &str, def: i64) -> i64 {
        match self.0.get(key) {
            None => def,
            Some(v) => v.replace('_', "").parse().unwrap_or_else(|e| panic!("param {key}={v:?}: {e}")),
        }
    }

    pub fn float(&self, key: &str, def: f64) -> f64 {
        match self.0.get(key) {
            None => def,
            Some(v) => v.parse().unwrap_or_else(|e| panic!("param {key}={v:?}: {e}")),
        }
    }

    pub fn bool(&self, key: &str, def: bool) -> bool {
        match self.0.get(key).map(|s| s.as_str()) {
            None => def,
            Some("1" | "t" | "T" | "true" | "TRUE" | "True") => true,
            Some("0" | "f" | "F" | "false" | "FALSE" | "False") => false,
            Some(v) => panic!("param {key}={v:?}: invalid bool"),
        }
    }
}
