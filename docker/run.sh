#!/usr/bin/env bash
# Run the suite inside the container, with results written to the host's
# results/ directory and tagged mode=container (never mixed with native runs).
#
#   docker/run.sh [PROFILE] [make target]      (defaults: standard benchmark)
#
# Settings mirror the native runs: all host CPUs visible to the container
# (--cpuset-cpus; the in-container taskset layout from bench.toml applies),
# host networking (no NAT/bridge in the HTTP path), raised fd limit.
# `docker stats` is sampled from the host side into the run directory.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-standard}"
TARGET="${2:-benchmark}"
IMAGE="${IMAGE:-go-vs-rust-bench:latest}"
CPUS="${CPUS:-0-$(($(nproc) - 1))}"
NAME="gvr-bench-$$"
NOFILE="${NOFILE:-$(ulimit -Hn)}" # same fd limit as native runs (cannot exceed the host hard limit)
mkdir -p "$ROOT/results"
STATS="$ROOT/results/docker-stats-$(date -u +%Y%m%dT%H%M%SZ).jsonl"

docker run -d --name "$NAME" \
	--cpuset-cpus "$CPUS" --network host \
	--ulimit "nofile=$NOFILE:$NOFILE" --security-opt seccomp=unconfined \
	-v "$ROOT/results:/bench/results" \
	"$IMAGE" make "$TARGET" "PROFILE=$PROFILE" MODE=container >/dev/null

( while docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null | grep -q true; do
	docker stats --no-stream --format '{{json .}}' "$NAME" 2>/dev/null |
		sed "s/^/{\"t\":\"$(date -u +%FT%TZ)\",\"s\":/; s/\$/}/" >>"$STATS"
	sleep 5
done ) &
docker logs -f "$NAME"
code="$(docker wait "$NAME")"
docker rm "$NAME" >/dev/null
wait || true
echo "container exited with $code; host-side docker stats: $STATS"
exit "$code"
