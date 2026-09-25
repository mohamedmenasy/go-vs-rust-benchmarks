//! Escape-time Mandelbrot (max 50 iterations) over a w x w grid covering
//! [-1.5, 0.5] x [-1, 1], packed one bit per pixel (mirror of go/cpu).

use bench_common::{Instance, Params, Work, fnv1a64};

const MAX_ITER: u32 = 50;

struct Mandelbrot {
    w: usize,
    bitmap: Vec<u8>,
}

impl Instance for Mandelbrot {
    fn run(&mut self) -> u64 {
        let (w, h) = (self.w, self.w);
        let row_bytes = w.div_ceil(8);
        let mut count = 0u64;
        for y in 0..h {
            let ci = 2.0 * y as f64 / h as f64 - 1.0;
            for xb in 0..row_bytes {
                let mut bits: u8 = 0;
                for bit in 0..8 {
                    let x = xb * 8 + bit;
                    let mut inside = false;
                    if x < w {
                        let cr = 2.0 * x as f64 / w as f64 - 1.5;
                        let (mut zr, mut zi, mut tr, mut ti) = (0.0f64, 0.0f64, 0.0f64, 0.0f64);
                        let mut i = 0;
                        while i < MAX_ITER && tr + ti <= 4.0 {
                            zi = 2.0 * zr * zi + ci;
                            zr = tr - ti + cr;
                            tr = zr * zr;
                            ti = zi * zi;
                            i += 1;
                        }
                        inside = tr + ti <= 4.0;
                    }
                    bits <<= 1;
                    if inside {
                        bits |= 1;
                        count += 1;
                    }
                }
                self.bitmap[y * row_bytes + xb] = bits;
            }
        }
        count
    }
    fn has_check(&self) -> bool {
        true
    }
    fn check(&mut self) -> u64 {
        fnv1a64(&self.bitmap)
    }
}

pub fn setup(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let w = p.int("w", 4000) as usize;
    Ok((
        Box::new(Mandelbrot { w, bitmap: vec![0; w.div_ceil(8) * w] }),
        Work { unit: "pixels", per_run: (w * w) as f64, input_bytes: 0 },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{golden_cpu, params, run_once};
    use bench_common::golden_hex;

    #[test]
    fn matches_golden() {
        let c = &golden_cpu()["mandelbrot"];
        let (mut inst, _) = setup(&params(&[("w", c["w"].to_string())])).unwrap();
        let (r, ch) = run_once(&mut inst);
        assert_eq!(r, c["count"].as_u64().unwrap());
        assert_eq!(ch, golden_hex(&c["fnv1a64"]));
    }
}
