# Handoff: `experiments_llm` branch

This branch replaces the previous `part_a.py`/`part_b.py` on `main` with LLM-assisted, empirically
validated improvements. Everything is grounded in runs against the Dockerized, network-isolated
`checker/` harness (2034 bundled test cases with model solutions) — no claim below is asserted from
intuition alone. **Read this before merging to `main`** — it names what changed, what's proven, and
what's still open.

## What changed

### `part_a.py`
Same CSP backtracking core as before (MRV + forward checking, sound and unchanged), plus three
additive techniques:

1. **Randomized-restart fallback.** The deterministic, heuristic-guided first attempt is byte-identical
   to the original solver — already-fast instances are completely unaffected. Only when that attempt
   times out without a conclusion does the search fall back to short time-sliced restarts using
   **uniformly random value ordering** (not the heuristic scorer). This is the headline change — see
   "Why random ordering, not a refined heuristic?" below.
2. **Batched candidate-set updates** — a pure speed optimization (no behavioral change), ~50% more
   search nodes/second on the profiled worst case.
3. **A tighter, leave-aware infeasibility pre-check** — replaces the original `N*K` global capacity
   bound with a per-nurse, leave-aware bound. Provably never rejects a feasible instance (strictly
   tighter than, never looser than, the original), and detects true no-solution cases up to ~112x
   faster on a constructed counter-example.

### `part_b.py`
Was an unimplemented stub before this branch — **first working implementation**. Constructs an initial
valid roster via `part_a.solve` (inheriting all of the above), then hill-climbs the soft-constraint cost
via cross-nurse same-day shift swaps (headcount-preserving by construction, so hard constraints stay
satisfied automatically), with sideways moves and perturb-and-restart cycles using the remaining time
budget.

## Validated results

All numbers below come from running `checker/check.py` inside the Docker sandbox
(`docker/Dockerfile.checker`, `scripts/run_checker.sh` — `--network none`, read-only repo mount) against
the exact `part_a.py`/`part_b.py` now on this branch.

**Part A**, combined `suite_001` (1000 cases) + `suite_002` (24 cases) = 1024 cases:

| | pass rate | total checker wall time |
|---|---|---|
| previous implementation (main) | 953/1024 (93.1%) | 1223.1s |
| **this branch** | **1017/1024 (99.3%)** | **691.1s** |

**Zero regressions**: every one of the 7 remaining failures was already failing on `main`; no case
`main` solved is now failing. Also **43% less total wall time** despite solving 64 more cases.

**Part B**, `suite_002` + `suite_003` + `suite_004` = 34 cases, from the final combined `--part both` run
(both parts run together at `-j 8`, so timing reflects realistic contention rather than an isolated
best case): **28/34 produce a valid roster** (up from 0/34 — Part B was unimplemented before this
branch). Of those, 1 matched the bundled model's cost exactly (`suite_003/test9`), the rest are
`SUBOPTIMAL` — see "Known limitations" below for concrete cost-quality improvement ideas. The 6 failures
are `suite_002/test22` (inherited from Part A — see below) and `suite_003/test3`, `test5`, `test6`,
`test7`, `test8`. Note: `test7`/`test8` (T=30s budget) are borderline-timed — an earlier, less-loaded
standalone Part B benchmark run had them passing at ~20s; under this run's higher contention (both parts
+ all suites running together) they finished just over budget (~32s). Treat pass/fail on these two
specifically as timing-sensitive rather than a hard boundary.

## Why random ordering, not a refined heuristic?

This is the one genuinely surprising, worth-understanding finding from this work, and it should go in
`report.txt` if this branch is merged.

The existing value-ordering heuristic (`score_domain_value`) is not always helpful — on some instances
it actively steers the search into a bad region of the tree despite abundant valid solutions existing
nearby. Concretely: one instance (`suite_001/test25`, 80 variables, huge slack, many valid solutions)
made the heuristic-guided search thrash for ~27,000 wasted backtrack calls without ever finding a
solution in a 10-second budget. Replacing the heuristic with **uniformly random** value ordering solved
the same instance in ~1 second on the very first attempt. Randomizing only the *ties* on top of the
heuristic (keeping it "in charge") did **not** fix this case even after many restart attempts — the
heuristic itself, not just its tie-breaking, was the problem.

This led to trying a more "theoretically correct" improvement — a hybrid true-least-constraining-value
(LCV) computation, which independently fixed one specific hard case
(`suite_002/test22`) that random restarts alone don't solve. But a full-scale validation across all
1000 `suite_001` cases showed the LCV addition **introduced 4 new regressions** on cases the simpler
random-restart-only approach solves without issue — the "more correct" heuristic was worse in
aggregate. **This is why the merged `part_a.py` uses pure random-restart, not the LCV combination** —
it was the empirically stronger and strictly safer choice, confirmed by measurement rather than by
which idea sounded more sophisticated.

## Known limitations / open follow-ups

- **`suite_002/test22`** is not solved by `part_a.py` on this branch. Investigated: confirmed it's not
  simply "needs more time" (tested up to 90s against its 20s budget, still fails) — it structurally
  resists random-ordering restarts specifically. The LCV-based fix exists (`experiments/part_a_hybrid_lcv.py`)
  but was excluded for causing regressions elsewhere; a smarter, more selectively-gated version of that
  idea is the natural next step if this specific case matters.
- **6 further `suite_001` cases remain unsolved** (`test228`, `test332`, `test337`, `test635`, `test656`,
  `test84`) — all confirmed genuinely feasible (via bundled model solutions), and confirmed to remain
  unsolved even at 6x their original time budget (tested up to 60s against original 10s budgets) —
  i.e. these are not "nearly there," they're structurally resistant to the current approach. Candidates
  worth trying next: conflict-directed backjumping, AC-3/MAC constraint propagation, or a more
  sophisticated restart strategy (e.g. varying which heuristic/randomization mode each restart uses,
  rather than only alternating between "pure heuristic" and "pure random").
- **Part B's cost quality** has room to improve. The current move set (single cross-nurse same-day
  swaps) is narrow; richer moves (working↔resting swaps, multi-nurse cyclic exchanges, a cost-aware
  constructive warm start) were identified but not implemented — see
  `NOTES_experiment_results.md` / `NOTES_competitive_optimization.md`.
- **Part B's time-budget split** (30% construction / 70% optimization, fixed) isn't adaptive. Three of
  the hardest `suite_003` instances (T=600s) fail because construction alone needs more than its
  reserved 30% share for those specific cases. Worth making this split adaptive to how long construction
  is actually taking.
- **`suite_003` full sweep** for Part A (the six T=600s cases) and the full `suite_001` sweep for Part B
  were not both completed in this pass, due to the wall-clock cost of repeated 600s-budget runs during
  iteration — the numbers above are what was actually measured; anything not explicitly stated as
  measured should be treated as untested, not assumed to hold.

## How to reproduce / keep validating

This branch does **not** include `checker/`, `Slides/`, or the assignment PDF — they're course
materials / a separate unofficial third-party repo, not meant for version control here. Get the checker
first (matches its own README's instructions):

```bash
git clone https://github.com/AbhinavPJ/COL333-A1-CHECKER.git checker
docker build -t nurse-roster-checker -f docker/Dockerfile.checker .
PART=both TESTS=suite_002,suite_003,suite_004 JOBS=8 CPUS=10 ./scripts/run_checker.sh
```

`scripts/bench_experiment.sh` and `experiments/bench.py` remain available for testing any further
experimental variant against the real files without risk (they back up and restore automatically).

## Where everything lives

- `NOTES_correctness_and_approaches.md` — original correctness audit + candidate-approach menu.
- `NOTES_experiment_results.md` — first round of prototyped-and-benchmarked results.
- `NOTES_competitive_optimization.md` — the competitive push: data-structure experiments, the
  infeasibility-pruning counter-example, and the full random-restart story.
- `experiments/` — every prototyped variant, kept for reference (including the ones *not* merged, like
  `part_a_hybrid_lcv.py` and `part_a_restart_lcv.py`, which are useful starting points for the
  `test22`/6-remaining-cases follow-up above).
- `docker/`, `scripts/` — the sandboxed checker harness.

## A note on process

This branch was produced with an LLM (Claude) doing the exploration, implementation, and benchmarking,
under human direction and review at each major decision point (scope of work, merge policy, which
techniques to pursue). Every performance/correctness claim in this document and in `part_a.py`/`part_b.py`'s
own docstrings is backed by an actual checker run, not by design intuition — where a technique looked
promising but the numbers didn't support it (the LCV combination), it was dropped rather than kept
despite the negative result. **Please independently re-run the validation commands above before relying
on this branch for a real submission**, and treat report.txt's description of these techniques as a
starting draft to review, not a final artifact.
