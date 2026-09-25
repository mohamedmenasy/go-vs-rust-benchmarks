#!/usr/bin/env bash
# Install everything needed to build and run the suite on Ubuntu/Debian.
#
#   * system tools: hyperfine, wrk, nginx, sysstat (pidstat), GNU time, build tools
#   * wrk2 built from a pinned commit (tools/bin/wrk2)
#   * Go 1.27.1   - any Go >= 1.21 bootstraps it via GOTOOLCHAIN (go.mod pins it)
#   * Rust 1.98.1 - rustup installs it from rust/rust-toolchain.toml
#   * Python venv (.venv) with pinned numpy/pandas/matplotlib/scipy
#   * pre-fetched Go and Rust dependencies (builds can then run offline)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\n==> %s\n' "$*"; }
SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null; then SUDO="sudo"; fi

if command -v apt-get >/dev/null; then
	say "Installing system packages (apt)"
	$SUDO apt-get update -qq
	DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq --no-install-recommends \
		build-essential git curl ca-certificates jq unzip \
		hyperfine wrk nginx sysstat time \
		libssl-dev zlib1g-dev python3 python3-venv >/dev/null
	# perf is optional: hardware counters are often unavailable in VMs.
	DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq --no-install-recommends linux-tools-generic >/dev/null 2>&1 ||
		echo "   (linux-tools-generic unavailable; perf stat will be skipped)"
else
	echo "apt-get not found: install hyperfine, wrk, nginx, sysstat, GNU time, a C toolchain and python3-venv manually." >&2
fi

say "Building wrk2 (pinned commit)"
scripts/build_wrk2.sh

say "Go toolchain (pinned by go/go.mod + GOTOOLCHAIN)"
if ! command -v go >/dev/null; then
	echo "Go is not installed. Install any Go >= 1.21 (https://go.dev/dl/); it will fetch go1.27.1 automatically." >&2
	exit 1
fi
(cd go && GOTOOLCHAIN=go1.27.1 go version && GOTOOLCHAIN=go1.27.1 go mod download)

say "Rust toolchain (pinned by rust/rust-toolchain.toml)"
if ! command -v rustup >/dev/null; then
	curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain none
	# shellcheck disable=SC1091
	. "$HOME/.cargo/env"
fi
(cd rust && rustup show active-toolchain >/dev/null 2>&1 || rustup toolchain install "$(sed -n 's/^channel = "\(.*\)"/\1/p' rust-toolchain.toml)" --profile minimal -c rustfmt -c clippy)
(cd rust && rustc -V && cargo fetch --locked)

say "Python virtualenv (.venv)"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r scripts/requirements.txt
.venv/bin/python -c "import numpy, pandas, matplotlib, scipy; print('numpy', numpy.__version__, 'pandas', pandas.__version__)"

say "Done. Next: make build && make validate PROFILE=quick"
