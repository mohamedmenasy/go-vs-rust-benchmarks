//! The Benchmarks Game planetary simulation (simple, non-SIMD formulation),
//! identical operation order to go/cpu/nbody.go.

use std::f64::consts::PI;

use bench_common::{Digest, Instance, Params, Work};

#[derive(Clone, Copy)]
struct Body {
    x: f64,
    y: f64,
    z: f64,
    vx: f64,
    vy: f64,
    vz: f64,
    mass: f64,
}

// Evaluated with IEEE rounding after each operation (Rust const evaluation
// follows run-time semantics); go/cpu/nbody.go uses run-time float64
// variables to get the same bits.
const SOLAR_MASS: f64 = 4.0 * PI * PI;
const DAYS_PER_YEAR: f64 = 365.24;

#[rustfmt::skip]
#[allow(clippy::excessive_precision)] // literals kept verbatim from the Benchmarks Game (same as Go/Python)
fn initial() -> [Body; 5] {
    let dpy = DAYS_PER_YEAR;
    let mut bs = [
        Body { x: 0.0, y: 0.0, z: 0.0, vx: 0.0, vy: 0.0, vz: 0.0, mass: SOLAR_MASS },
        Body { x: 4.84143144246472090e+00, y: -1.16032004402742839e+00, z: -1.03622044471123109e-01,
               vx: 1.66007664274403694e-03 * dpy, vy: 7.69901118419740425e-03 * dpy, vz: -6.90460016972063023e-05 * dpy,
               mass: 9.54791938424326609e-04 * SOLAR_MASS },
        Body { x: 8.34336671824457987e+00, y: 4.12479856412430479e+00, z: -4.03523417114321381e-01,
               vx: -2.76742510726862411e-03 * dpy, vy: 4.99852801234917238e-03 * dpy, vz: 2.30417297573763929e-05 * dpy,
               mass: 2.85885980666130812e-04 * SOLAR_MASS },
        Body { x: 1.28943695621391310e+01, y: -1.51111514016986312e+01, z: -2.23307578892655734e-01,
               vx: 2.96460137564761618e-03 * dpy, vy: 2.37847173959480950e-03 * dpy, vz: -2.96589568540237556e-05 * dpy,
               mass: 4.36624404335156298e-05 * SOLAR_MASS },
        Body { x: 1.53796971148509165e+01, y: -2.59193146099879641e+01, z: 1.79258772950371181e-01,
               vx: 2.68067772490389322e-03 * dpy, vy: 1.62824170038242295e-03 * dpy, vz: -9.51592254519715870e-05 * dpy,
               mass: 5.15138902046611451e-05 * SOLAR_MASS },
    ];
    let (mut px, mut py, mut pz) = (0.0, 0.0, 0.0);
    for b in &bs {
        px += b.vx * b.mass;
        py += b.vy * b.mass;
        pz += b.vz * b.mass;
    }
    bs[0].vx = -px / SOLAR_MASS;
    bs[0].vy = -py / SOLAR_MASS;
    bs[0].vz = -pz / SOLAR_MASS;
    bs
}

fn energy(bs: &[Body; 5]) -> f64 {
    let mut e = 0.0;
    for i in 0..bs.len() {
        let b = &bs[i];
        e += 0.5 * b.mass * (b.vx * b.vx + b.vy * b.vy + b.vz * b.vz);
        for b2 in &bs[i + 1..] {
            let dx = b.x - b2.x;
            let dy = b.y - b2.y;
            let dz = b.z - b2.z;
            e -= (b.mass * b2.mass) / (dx * dx + dy * dy + dz * dz).sqrt();
        }
    }
    e
}

fn advance(bs: &mut [Body; 5], dt: f64) {
    for i in 0..bs.len() {
        let (left, right) = bs.split_at_mut(i + 1);
        let bi = &mut left[i];
        for bj in right.iter_mut() {
            let dx = bi.x - bj.x;
            let dy = bi.y - bj.y;
            let dz = bi.z - bj.z;
            let dsq = dx * dx + dy * dy + dz * dz;
            let dist = dsq.sqrt();
            let mag = dt / (dsq * dist);
            bi.vx -= dx * bj.mass * mag;
            bi.vy -= dy * bj.mass * mag;
            bi.vz -= dz * bj.mass * mag;
            bj.vx += dx * bi.mass * mag;
            bj.vy += dy * bi.mass * mag;
            bj.vz += dz * bi.mass * mag;
        }
    }
    for b in bs.iter_mut() {
        b.x += dt * b.vx;
        b.y += dt * b.vy;
        b.z += dt * b.vz;
    }
}

struct NBody {
    steps: usize,
    initial: [Body; 5],
    bodies: [Body; 5],
}

impl Instance for NBody {
    fn prepare(&mut self) {
        self.bodies = self.initial;
    }
    fn run(&mut self) -> u64 {
        let e0 = energy(&self.bodies);
        for _ in 0..self.steps {
            advance(&mut self.bodies, 0.01);
        }
        let e1 = energy(&self.bodies);
        let mut d = Digest::new();
        d.add_f64(e0);
        d.add_f64(e1);
        d.sum()
    }
}

pub fn setup(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let steps = p.int("steps", 10_000_000) as usize;
    let init = initial();
    Ok((
        Box::new(NBody { steps, initial: init, bodies: init }),
        Work { unit: "steps", per_run: steps as f64, input_bytes: 0 },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{golden_cpu, params, run_once};
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let c = &golden_cpu()["nbody"];
        assert_eq!(energy(&initial()).to_bits(), golden_hex(&c["e0_bits"]));
        let (mut inst, _) = setup(&params(&[("steps", c["steps"].to_string())])).unwrap();
        assert_eq!(run_once(&mut inst).0, golden_hex(&c["digest"]));
    }
}
