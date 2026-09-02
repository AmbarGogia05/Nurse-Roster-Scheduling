# Part B Algorithmic Experiments — Results

Follow-up to `NOTES_part_b_literature.md`. Merged per the standing policy once validated.

## Tier 1 (`experiments/part_b_tier1.py`): VNS shake + worst-nurse-first + early-abort

Soundness-checked clean (20 random `suite_001` cases). Benchmark: **neutral** — matched baseline exactly
on `suite_002`+`suite_004` (avg_gap 104.7 vs 104.6) and on a 150-case `suite_001` sample (24 MATCHED,
avg_gap 22.3, identical to baseline). **Not merged** — no measurable win found on the workloads tested,
kept in `experiments/` as a documented negative/neutral result rather than merged speculatively.

## Branch-and-bound (`experiments/part_b_branch_and_bound.py`) — **merged into `part_b.py`**

DFS branch-and-bound with the convex per-nurse lower bound from the literature note, run as a small
time-boxed pass ahead of the existing construction+hill-climb pipeline, keeping whichever result is
better.

**A real bug found and fixed during validation**: the first version reserved 40% of the time budget for
branch-and-bound. On a 150-case `suite_001` sample this produced a genuine regression
(`suite_001/test39`: baseline and Tier-1 both PASS, this variant FAILed) — root cause: `branch_and_bound`
forces deterministic-only search (no randomized-restart escape hatch, needed for clean incumbent/bound
tracking), so on an instance where plain deterministic construction is itself borderline-slow, the large
slice both wasted time finding no incumbent AND starved the guaranteed-safe fallback of the runway it
needed. Fixed by capping the slice to a small absolute value (`min(2.0s, T*0.15)`) instead of a large
fraction of `T`. Re-validated clean: **1 FAIL (the same instance every variant fails on, inherited from
Part A), zero regressions.**

**Validated result** (150-case `suite_001` sample, before → after):

| | MATCHED (proven optimal) | avg. cost gap vs. bundled model | FAIL |
|---|---|---|---|
| baseline | 24 | 22.3 | 1 |
| **branch_and_bound (fixed)** | **29** | **20.2** | **1** |

A genuine, measurable quality improvement — 5 more instances proven exactly optimal, lower average gap
overall — with zero net regressions. On `suite_002`/`suite_004` (larger N≤50,D=30 instances, T=20-30s),
the effect was neutral (branch-and-bound's slice is too small relative to those instances' size to find
many improving proofs) — consistent with the literature's own framing: real value on small/medium
instances, no expectation of scaling to the largest ones within a short slice.

**Soundness**: checked clean before AND after the budget fix (zero invalid rosters, zero crashes across
~55 total sampled `suite_001` cases combined).

## Not attempted this pass (time-boxed per "rapid experimentation" priority)

Constructive beam search (Tier 2, item 2 in the literature note) and GRASP-style randomized construction
(Tier 3) — both still-open, reasonably scoped follow-ups noted in `NOTES_part_b_literature.md`, not
built in this pass given the strong, validated win already banked from branch-and-bound and the priority
on iteration speed over exhaustive coverage.
