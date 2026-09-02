#!/usr/bin/env bash
# Benchmark an experimental part_a.py/part_b.py variant against the Dockerized
# checker, WITHOUT permanently modifying the real submission file.
#
# Mechanism: back up the real file, copy the experiment over it, run
# scripts/run_checker.sh (same sandboxed, network-isolated invocation used
# for the real submission), then restore the original file no matter what
# (trap on EXIT) so part_a.py/part_b.py are never left mutated.
#
# Usage:
#   VARIANT=experiments/part_a_degree_heuristic.py TARGET=part_a.py \
#     PART=a TESTS=suite_002/test1.csv,suite_001/test25.csv JOBS=4 CPUS=6 \
#     ./scripts/bench_experiment.sh
#
# Required env vars: VARIANT (path to the experimental .py file), TARGET
# (part_a.py or part_b.py — which real file it stands in for).
# Other env vars (PART, TESTS, JOBS, CPUS, TIMEOUT, IMAGE) pass through to
# run_checker.sh unchanged.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

: "${VARIANT:?set VARIANT=path/to/experiments/variant.py}"
: "${TARGET:?set TARGET=part_a.py or part_b.py}"

if [[ ! -f "$VARIANT" ]]; then
    echo "error: VARIANT file not found: $VARIANT" >&2
    exit 1
fi
if [[ "$TARGET" != "part_a.py" && "$TARGET" != "part_b.py" ]]; then
    echo "error: TARGET must be part_a.py or part_b.py, got: $TARGET" >&2
    exit 1
fi

BACKUP="$(mktemp)"
cp "$TARGET" "$BACKUP"

restore() {
    cp "$BACKUP" "$TARGET"
    rm -f "$BACKUP"
    echo "[bench_experiment] restored original $TARGET" >&2
}
trap restore EXIT

cp "$VARIANT" "$TARGET"
echo "[bench_experiment] running $VARIANT as $TARGET" >&2

# run_checker.sh itself exits non-zero when the checker reports any FAIL —
# that's an expected/informative outcome here, not a script bug, so don't
# let `set -e` abort before the restore trap runs.
./scripts/run_checker.sh || true
