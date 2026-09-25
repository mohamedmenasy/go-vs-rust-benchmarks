#!/usr/bin/env bash
# Build every benchmark program with production settings.
#
#   scripts/build.sh go   <bin>...    -> bin/go/<bin>
#   scripts/build.sh rust <bin>...    -> bin/rust/<bin>, bin/rust-allocstats/<bin>,
#                                        bin/rust-tuned/<bin>, bin/rust-mimalloc/<bin>
#
# Go:   CGO_ENABLED=0 GOAMD64=v1 go build -trimpath -buildvcs=false
# Rust: cargo build --release --locked (profile.release in rust/Cargo.toml)
#       allocstats: + --features alloc-stats   (allocation-profile pass only)
#       tuned:      --profile release-tuned    (tuned track only)
#       mimalloc:   + --features mimalloc      (tuned track only)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lang="${1:?usage: build.sh go|rust <bin>...}"
shift
export GOTOOLCHAIN="${GOTOOLCHAIN:-go1.27.1}"

case "$lang" in
go)
	mkdir -p "$ROOT/bin/go"
	cd "$ROOT/go"
	for b in "$@"; do
		CGO_ENABLED=0 GOAMD64=v1 go build -trimpath -buildvcs=false -o "$ROOT/bin/go/$b" "./$b"
	done
	# Sensitivity flavours: Go 1.27 enables the jsonv2 and greenteagc
	# experiments by default; these builds switch them off for comparison.
	#   flavor | GOEXPERIMENT | programs
	go_flavors=(
		"legacyjson|nojsonv2|json"
		"nogreentea|nogreenteagc|memory"
	)
	for f in "${go_flavors[@]}"; do
		IFS='|' read -r flavor exp progs <<<"$f"
		for b in $progs; do
			case " $* " in *" $b "*) ;; *) continue ;; esac
			mkdir -p "$ROOT/bin/go-$flavor"
			GOEXPERIMENT="$exp" CGO_ENABLED=0 GOAMD64=v1 go build -trimpath -buildvcs=false -o "$ROOT/bin/go-$flavor/$b" "./$b"
		done
	done
	;;
rust)
	cd "$ROOT/rust"
	# flavor | cargo arguments | cargo output directory
	flavors=(
		"|--release|target/release"
		"allocstats|--release --features alloc-stats --target-dir target/flavor-allocstats|target/flavor-allocstats/release"
		"tuned|--profile release-tuned|target/release-tuned"
		"mimalloc|--release --features mimalloc --target-dir target/flavor-mimalloc|target/flavor-mimalloc/release"
	)
	for f in "${flavors[@]}"; do
		IFS='|' read -r flavor args outdir <<<"$f"
		# shellcheck disable=SC2086
		cargo build --locked --workspace $args
		dest="$ROOT/bin/rust${flavor:+-$flavor}"
		mkdir -p "$dest"
		for b in "$@"; do
			cp -f "$outdir/$b" "$dest/$b"
		done
	done
	;;
*)
	echo "unknown language: $lang" >&2
	exit 2
	;;
esac
