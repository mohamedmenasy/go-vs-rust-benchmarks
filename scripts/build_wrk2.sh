#!/usr/bin/env bash
# Build wrk2 (constant-throughput, coordinated-omission-corrected load
# generator) from a pinned commit into tools/bin/wrk2.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRK2_REPO="https://github.com/giltene/wrk2"
WRK2_COMMIT="44a94c17d8e6a0bac8559b53da76848e430cb7a7"
SRC="$ROOT/tools/src/wrk2"
mkdir -p "$ROOT/tools/src" "$ROOT/tools/bin"
if [ -x "$ROOT/tools/bin/wrk2" ]; then
	echo "wrk2 already built: $ROOT/tools/bin/wrk2"
	exit 0
fi
if [ ! -d "$SRC/.git" ]; then
	git clone --quiet "$WRK2_REPO" "$SRC"
fi
git -C "$SRC" fetch --quiet origin "$WRK2_COMMIT" 2>/dev/null || true
git -C "$SRC" checkout --quiet "$WRK2_COMMIT"
make -C "$SRC" -j"$(nproc)" >"$SRC/build.log" 2>&1 || {
	tail -30 "$SRC/build.log" >&2
	exit 1
}
cp "$SRC/wrk" "$ROOT/tools/bin/wrk2"
echo "built wrk2 @ $WRK2_COMMIT -> $ROOT/tools/bin/wrk2"
