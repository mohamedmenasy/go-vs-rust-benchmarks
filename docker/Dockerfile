# syntax=docker/dockerfile:1.7
# Containerized benchmark image: the same toolchains, tools and Python stack as
# a native `make setup`, installed by the same script (scripts/setup.sh).
#
#   docker build -f docker/Dockerfile -t go-vs-rust-bench .
#   docker/run.sh [quick|standard|full]
#
# BASE_IMAGE can point at a mirror of the official image (e.g.
# mirror.gcr.io/library/ubuntu:24.04) when Docker Hub rate-limits.
# Behind a TLS-intercepting proxy, pass its CA as a build secret:
#   docker build --secret id=extra_ca,src=/path/ca.crt ...
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    PATH=/root/.cargo/bin:/root/go/bin:/usr/local/go/bin:$PATH \
    GOTOOLCHAIN=go1.27.1

WORKDIR /bench

# Bootstrap Go (any Go >= 1.21 fetches the pinned go1.27.1 via GOTOOLCHAIN).
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then mkdir -p /usr/local/share/ca-certificates && cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra_ca.crt; fi && \
    apt-get update -qq && apt-get install -y -qq --no-install-recommends ca-certificates golang-go sudo >/dev/null && \
    update-ca-certificates >/dev/null && rm -rf /var/lib/apt/lists/*

COPY . .
RUN --mount=type=secret,id=extra_ca,required=false \
    export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt CARGO_HTTP_CAINFO=/etc/ssl/certs/ca-certificates.crt \
           PIP_CERT=/etc/ssl/certs/ca-certificates.crt && \
    scripts/setup.sh && make build && rm -f /usr/local/share/ca-certificates/extra_ca.crt && update-ca-certificates >/dev/null

# Results are written to the bind-mounted /bench/results (see run.sh).
CMD ["make", "benchmark", "MODE=container"]
