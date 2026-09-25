//! Benchmarks Game binary-trees, single-threaded (mirror of go/memory/trees.go).

use bench_common::{Digest, Instance, Params, Work};

use crate::release;

struct Node {
    left: Option<Box<Node>>,
    right: Option<Box<Node>>,
}

fn bottom_up(depth: u32) -> Box<Node> {
    if depth == 0 {
        Box::new(Node { left: None, right: None })
    } else {
        Box::new(Node { left: Some(bottom_up(depth - 1)), right: Some(bottom_up(depth - 1)) })
    }
}

impl Node {
    fn check(&self) -> u64 {
        match (&self.left, &self.right) {
            (Some(l), Some(r)) => 1 + l.check() + r.check(),
            _ => 1,
        }
    }
}

const MIN_DEPTH: u32 = 4;

struct Trees {
    depth: u32,
}

impl Instance for Trees {
    fn run(&mut self) -> u64 {
        let max_depth = self.depth;
        let mut d = Digest::new();
        d.add(bottom_up(max_depth + 1).check()); // stretch tree
        let long_lived = bottom_up(max_depth);
        let mut depth = MIN_DEPTH;
        while depth <= max_depth {
            let iters = 1u64 << (max_depth - depth + MIN_DEPTH);
            let mut check = 0u64;
            for _ in 0..iters {
                check += bottom_up(depth).check();
            }
            d.add(iters);
            d.add(depth as u64);
            d.add(check);
            depth += 2;
        }
        d.add(long_lived.check());
        d.sum()
    }
    fn has_teardown(&self) -> bool {
        true
    }
    fn teardown(&mut self) {
        release();
    }
}

fn tree_nodes(max_depth: u32) -> f64 {
    let nodes = |d: u32| ((1u64 << (d + 1)) - 1) as f64;
    let mut total = nodes(max_depth + 1) + nodes(max_depth);
    let mut depth = MIN_DEPTH;
    while depth <= max_depth {
        total += (1u64 << (max_depth - depth + MIN_DEPTH)) as f64 * nodes(depth);
        depth += 2;
    }
    total
}

pub fn setup(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let depth = p.int("depth", 18) as u32;
    Ok((Box::new(Trees { depth }), Work { unit: "nodes", per_run: tree_nodes(depth), input_bytes: 0 }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{golden_memory, params, run_twice};
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        for c in golden_memory()["binarytrees"].as_array().unwrap() {
            let (mut inst, _) = setup(&params(&[("depth", c["depth"].to_string())])).unwrap();
            assert_eq!(run_twice(&mut inst), golden_hex(&c["run"]));
        }
    }
}
