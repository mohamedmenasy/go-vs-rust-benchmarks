# Containerized runs

The image holds the same toolchains, tools and Python stack as a native
`make setup`, because it installs them with the same script (`scripts/setup.sh`):
Go 1.27.1, Rust 1.98.1, hyperfine, wrk, wrk2 (pinned commit), nginx,
sysstat and GNU time.

```sh
make docker-build                 # docker build -f docker/Dockerfile -t go-vs-rust-bench .
make docker-benchmark PROFILE=standard
docker/run.sh quick benchmark-cpu # one category
```

- **Base image mirror.** If Docker Hub rate-limits, build from a mirror of
  the same official image:
  `docker build --build-arg BASE_IMAGE=mirror.gcr.io/library/ubuntu:24.04 ...`
- **Proxy.** Behind a TLS-intercepting proxy, pass `HTTPS_PROXY` as a build
  arg and the proxy's CA as a BuildKit secret:
  `--secret id=extra_ca,src=/path/ca.crt`. The CA is used only while the
  image builds.

## What `run.sh` does

- **CPUs.** `--cpuset-cpus` gives the container the same CPUs as the host
  (override with `CPUS=`). Inside the container, the `taskset` layout from
  `bench.toml` applies exactly as it does natively.
- **Network.** `--network host` keeps Docker's bridge and NAT out of the
  HTTP path.
- **File descriptors.** `--ulimit nofile` is set to the host's hard limit,
  the same limit native runs get.
- **Seccomp.** `--security-opt seccomp=unconfined` removes the per-syscall
  seccomp filter. The filter would otherwise add a syscall-dependent cost
  that native runs don't pay.
- **Results.** `results/` is bind-mounted. Every run is tagged
  `mode=container`, and its run id ends in `-container-<host>`.
- **Host-side monitoring.** `docker stats` is sampled every 5 s into
  `results/docker-stats-<time>.jsonl`.

Container results are **never** mixed with native results: processing,
charts and `REPORT.md` group by `mode`. Use `make report MODE=container`.
