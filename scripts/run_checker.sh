#!/usr/bin/env bash
# Run checker/check.py (untrusted, student-written test harness) inside a
# network-isolated Docker container against the repo's part_a.py/part_b.py.
#
# Usage:
#   PART=a TESTS=suite_002,suite_003,suite_004 JOBS=1 ./scripts/run_checker.sh
#   PART=both TESTS=suite_001 JOBS=2 TIMEOUT=30 ./scripts/run_checker.sh
#   ./scripts/run_checker.sh --list                 # extra args pass straight through to check.py
#
# Env vars (all optional):
#   PART      a | b | both            (default: a)
#   TESTS     suite_00X[,suite_00Y..] (default: all suites)
#   JOBS      number of parallel jobs (default: 1)
#   CPUS      docker --cpus limit, should be >= JOBS for realistic per-case
#             timing (default: 2)
#   TIMEOUT   hard wall-clock override in seconds (default: unset -> check.py uses T+2 per case)
#   IMAGE     docker image tag        (default: nurse-roster-checker:latest)
#
# The repo is mounted read-only; checker/check.py only writes to a temp dir
# by default, which is covered by the --tmpfs /tmp mount. Never pass
# --overwrite-models/--keep-outputs through here against this read-only
# mount -- if that's ever needed deliberately, do it manually with a
# separate, narrowly-scoped writable mount.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-nurse-roster-checker:latest}"
PART="${PART:-a}"
JOBS="${JOBS:-1}"

args=(checker/check.py --part "$PART" -j "$JOBS")
if [[ -n "${TESTS:-}" ]]; then
    args+=(--tests "$TESTS")
fi
if [[ -n "${TIMEOUT:-}" ]]; then
    args+=(--timeout "$TIMEOUT")
fi
args+=("$@")

exec docker run --rm \
    --network none \
    --cpus="${CPUS:-2}" --memory="4g" --pids-limit=512 \
    --read-only \
    --tmpfs /tmp:rw,size=512m \
    -v "$REPO_ROOT":/work:ro \
    -w /work \
    --user runner \
    "$IMAGE" \
    python3 "${args[@]}"
