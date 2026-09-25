# Go vs Rust benchmark suite.
#
#   make setup       install tools, pinned toolchains and the Python venv
#   make benchmark   build -> datasets -> validate -> env -> run all -> process -> charts
#   make report      process raw results, draw charts, refresh REPORT.md tables
#
# Knobs: PROFILE=quick|standard|full  MODE=native|container  RUN_ID=<id>
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PROFILE ?= standard
MODE ?= native
ifeq ($(origin RUN_ID), undefined)
RUN_ID := $(shell date -u +%Y%m%dT%H%M%SZ)-$(MODE)-$(shell hostname | tr -cd 'A-Za-z0-9' | cut -c1-16)
endif
export PROFILE MODE RUN_ID

GO_VERSION := 1.27.1
export GOTOOLCHAIN := go$(GO_VERSION)
GO_ENV := CGO_ENABLED=0 GOAMD64=v1
GO_BUILD := go build -trimpath -buildvcs=false
CARGO := cargo

BENCH := scripts/bench

# Programs built for both languages (directory under go/ == Rust [[bin]] name).
BINS := selftest cpu
HARNESS_CATEGORIES := cpu memory json concurrency io strings collections
SPECIAL_CATEGORIES := http startup binsize compile
CATEGORIES := $(HARNESS_CATEGORIES) $(SPECIAL_CATEGORIES)

.PHONY: help setup build build-go build-rust test test-go test-rust test-python lint fmt datasets validate env \
	benchmark process charts report docs plan clean clean-results docker-build docker-benchmark \
	$(addprefix benchmark-,$(CATEGORIES))

help: ## show this help
	@grep -E '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

setup: ## install benchmark tools, pinned toolchains and the Python venv
	scripts/setup.sh

# --------------------------------------------------------------------------- build
build: build-go build-rust ## build all Go and Rust programs (production settings)

build-go: ## CGO_ENABLED=0 GOAMD64=v1 go build -trimpath -buildvcs=false
	scripts/build.sh go $(BINS)

build-rust: ## cargo build --release --locked (+ allocstats / tuned / mimalloc flavours)
	scripts/build.sh rust $(BINS)

# --------------------------------------------------------------------------- quality
test: test-go test-rust test-python ## unit tests in all three languages (incl. golden values)

test-go:
	cd go && $(GO_ENV) go test ./...

test-rust:
	cd rust && $(CARGO) test --release --locked --workspace

test-python:
	PYTHONPATH=scripts .venv/bin/python -m unittest discover -s scripts/tests -t scripts

lint: ## gofmt/vet, rustfmt/clippy
	cd go && test -z "$$(gofmt -l .)" && go vet ./...
	cd rust && $(CARGO) fmt --check && $(CARGO) clippy --release --locked --workspace --all-targets -- -D warnings

fmt: ## format Go and Rust sources
	cd go && gofmt -w .
	cd rust && $(CARGO) fmt

# --------------------------------------------------------------------------- data + correctness
datasets: ## generate/verify the datasets used by PROFILE
	$(BENCH) datasets --profile $(PROFILE)

validate: build ## Go and Rust must produce identical results (PROFILE sizes)
	$(BENCH) datasets --profile $(PROFILE) --fast
	$(BENCH) validate --profile $(PROFILE) --skip-datasets

env: ## print the captured environment
	$(BENCH) env --mode $(MODE)

docs: ## regenerate docs/BENCHMARKS.md from bench.toml
	$(BENCH) docs

plan: ## estimate the runtime of PROFILE
	$(BENCH) plan --profile $(PROFILE)

# --------------------------------------------------------------------------- benchmarks
benchmark: build ## full pipeline for PROFILE (all categories, one RUN_ID)
	$(BENCH) datasets --profile $(PROFILE)
	$(BENCH) validate --profile $(PROFILE) --skip-datasets
	$(BENCH) run --profile $(PROFILE) --mode $(MODE) --run-id $(RUN_ID) $(addprefix -c ,$(CATEGORIES))
	$(BENCH) process --run-id $(RUN_ID) --mode $(MODE)
	$(BENCH) charts --mode $(MODE)
	@echo "raw results: results/raw/$(RUN_ID)"

$(addprefix benchmark-,$(CATEGORIES)): benchmark-%: build ## run one category (e.g. make benchmark-cpu)
	$(BENCH) datasets --profile $(PROFILE) -c $*
	$(BENCH) validate --profile $(PROFILE) -c $* --skip-datasets
	$(BENCH) run --profile $(PROFILE) --mode $(MODE) --run-id $(RUN_ID) -c $*
	@echo "raw results: results/raw/$(RUN_ID)"

process: ## raw -> processed CSV/JSON (latest run per category)
	$(BENCH) process --mode $(MODE)

charts: ## draw charts from processed results
	$(BENCH) charts --mode $(MODE)

report: process charts ## refresh REPORT.md tables from processed results
	$(BENCH) report --mode $(MODE)

# --------------------------------------------------------------------------- docker
docker-build: ## build the containerized benchmark image
	docker build -f docker/Dockerfile -t go-vs-rust-bench:latest .

docker-benchmark: ## run `make benchmark MODE=container` inside the image
	docker/run.sh $(PROFILE)

# --------------------------------------------------------------------------- housekeeping
clean: ## remove build outputs and scratch space
	rm -rf bin scratch
	cd rust && $(CARGO) clean

clean-results: ## remove ALL raw/processed results and charts (asks first)
	@read -p "Delete results/raw, results/processed and charts? [y/N] " a && [ "$$a" = y ]
	rm -rf results/raw/* results/processed/* charts/*
