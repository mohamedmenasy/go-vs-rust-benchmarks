//! Minimal CLI used for startup-time and binary-size measurements (mirror of
//! go/hello): idiomatic "print one line and exit".

/// The constant the compile benchmark toggles for its one-file-change rebuild.
const GREETING: &str = "hello";

fn main() {
    println!("{GREETING}");
}
