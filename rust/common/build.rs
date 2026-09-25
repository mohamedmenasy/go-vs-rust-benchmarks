//! Records how the benchmark binaries were built so every result carries its
//! own provenance (compiler version, optimisation level, target features).
use std::env;
use std::process::Command;

fn main() {
    let rustc = env::var("RUSTC").unwrap_or_else(|_| "rustc".to_string());
    let version = Command::new(&rustc)
        .arg("-V")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .unwrap_or_default();
    println!("cargo:rustc-env=BENCH_RUSTC_VERSION={}", version.trim());
    for key in ["PROFILE", "OPT_LEVEL", "DEBUG", "TARGET"] {
        println!(
            "cargo:rustc-env=BENCH_BUILD_{}={}",
            key,
            env::var(key).unwrap_or_default()
        );
    }
    println!(
        "cargo:rustc-env=BENCH_TARGET_FEATURES={}",
        env::var("CARGO_CFG_TARGET_FEATURE").unwrap_or_default()
    );
    println!("cargo:rerun-if-changed=build.rs");
}
