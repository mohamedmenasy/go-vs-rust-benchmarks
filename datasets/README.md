# Datasets

Generated deterministically by `scripts/bench datasets` (see
`scripts/benchctl/datasets.py`). Only `manifest.json` is tracked in git. It pins
the size and SHA-256 of every file, so a machine that generates different bytes
is refused rather than silently benchmarked on different input.

```bash
scripts/bench datasets --profile standard   # what a profile needs
scripts/bench datasets --all-profiles       # everything, including the 1 GiB files
```
