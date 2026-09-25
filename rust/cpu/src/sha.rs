//! SHA-256, two ways:
//! * `sha256-lib`: the de-facto crate (`sha2`), an ecosystem comparison
//!   against Go's assembly implementation;
//! * `sha256-portable`: a straightforward FIPS 180-4 implementation written
//!   identically in go/cpu/sha.go, comparing the compilers on the same code.

use bench_common::rng::random_bytes;
use bench_common::{Instance, Params, Work};
use sha2::{Digest as _, Sha256};

struct ShaLib {
    data: Vec<u8>,
}

impl Instance for ShaLib {
    fn run(&mut self) -> u64 {
        let s = Sha256::digest(&self.data);
        u64::from_be_bytes(s[..8].try_into().unwrap())
    }
}

struct ShaPortable {
    data: Vec<u8>,
}

impl Instance for ShaPortable {
    fn run(&mut self) -> u64 {
        let s = sha256_portable(&self.data);
        u64::from_be_bytes(s[..8].try_into().unwrap())
    }
}

fn input(p: &Params) -> (Vec<u8>, Work) {
    let n = p.int("bytes", 64 << 20) as usize;
    let data = random_bytes(p.int("seed", 4) as u64, n);
    (data, Work { unit: "bytes", per_run: n as f64, input_bytes: n as u64 })
}

pub fn setup_lib(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let (data, work) = input(p);
    Ok((Box::new(ShaLib { data }), work))
}

pub fn setup_portable(p: &Params) -> Result<(Box<dyn Instance>, Work), String> {
    let (data, work) = input(p);
    Ok((Box::new(ShaPortable { data }), work))
}

const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

/// Process whole 64-byte blocks of `p`.
fn sha256_block(h: &mut [u32; 8], mut p: &[u8]) {
    let mut w = [0u32; 64];
    while p.len() >= 64 {
        for i in 0..16 {
            w[i] = u32::from_be_bytes([p[4 * i], p[4 * i + 1], p[4 * i + 2], p[4 * i + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = *h;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t1 = hh.wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
        p = &p[64..];
    }
}

pub fn sha256_portable(data: &[u8]) -> [u8; 32] {
    let mut h: [u32; 8] =
        [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    let full = data.len() & !63;
    sha256_block(&mut h, &data[..full]);
    let mut tail = [0u8; 128];
    let rem = data.len() - full;
    tail[..rem].copy_from_slice(&data[full..]);
    tail[rem] = 0x80;
    let tail_len = if rem >= 56 { 128 } else { 64 };
    tail[tail_len - 8..tail_len].copy_from_slice(&((data.len() as u64) * 8).to_be_bytes());
    sha256_block(&mut h, &tail[..tail_len]);
    let mut out = [0u8; 32];
    for (i, v) in h.iter().enumerate() {
        out[4 * i..4 * i + 4].copy_from_slice(&v.to_be_bytes());
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::golden_cpu;
    use bench_common::golden_hex;

    fn hex(b: &[u8]) -> String {
        b.iter().map(|x| format!("{x:02x}")).collect()
    }

    #[test]
    fn matches_golden() {
        for c in golden_cpu()["sha256"].as_array().unwrap() {
            let data = match c["input"].as_str() {
                Some(s) => s.as_bytes().to_vec(),
                None => random_bytes(c["random_seed"].as_u64().unwrap(), c["n"].as_u64().unwrap() as usize),
            };
            assert_eq!(hex(&sha256_portable(&data)), c["hex"].as_str().unwrap());
            assert_eq!(hex(&Sha256::digest(&data)), c["hex"].as_str().unwrap());
            let want = golden_hex(&c["first8"]);
            assert_eq!(ShaLib { data: data.clone() }.run(), want);
            assert_eq!(ShaPortable { data }.run(), want);
        }
    }
}
