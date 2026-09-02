# Experiment Results — Prototyped Strategies vs. the Dockerized Checker

Follow-up to `NOTES_correctness_and_approaches.md`. Each candidate strategy from that report's Section
B/C was prototyped as a standalone, non-destructive fork in `experiments/` and benchmarked through the
real sandboxed checker flow (`scripts/bench_experiment.sh`: temporarily swaps the experiment in for
`part_a.py`/`part_b.py`, runs `scripts/run_checker.sh` unchanged, then restores the original file via an
`EXIT` trap — confirmed restored after every run below). **`part_a.py` and `part_b.py` were not modified
by this pass**; this note only reports what was measured, so a deliberate merge decision can be made
separately.

## Benchmark set

The 6 known-timeout instances already identified while gathering correctness data (`suite_002/test1`,
`suite_002/test22`, `suite_003/test2`, `suite_003/test7`, `suite_003/test8`, `suite_001/test25` — the
thrashing case study), all confirmed genuinely feasible. This is a small, targeted, adversarial set —
useful for "does this specific idea help" signal, not a statistically representative sample. Broader
regression-style validation across `suite_001` (as planned) was not run this pass due to the wall-clock
cost of the T=600s cases (each full sweep of the 6-case set alone takes ~600–650s); note this as a gap
for the next round rather than skip past it silently.

## Part A: degree-heuristic MRV tiebreak vs. hybrid true-LCV vs. combined

| variant | fixed | still failing |
|---|---|---|
| baseline (current `part_a.py`) | none | all 6 |
| `experiments/part_a_degree_heuristic.py` | **test1, test7, test8** | test22, test25, test2 |
| `experiments/part_a_hybrid_lcv.py` | **test7, test8, test22** | test1, test25, test2 |
| `experiments/part_a_combined.py` | **test1, test7, test22** | **test8** (regression), test25, test2 |

Three concrete, measured findings:

1. **Both individual changes are real, substantial wins on their own** — each independently converts
   3 of 6 known-hard timeouts into fast passes (sub-second to ~1.4s, down from hitting the full T
   budget). This is a strong, checker-verified confirmation that Section B's #1 and #2 priorities were
   correctly ranked — search-order quality, not just problem scale, was genuinely limiting the current
   implementation.
2. **The two changes fix different, only partially-overlapping subsets** (`test1`/`test8` vs.
   `test8`/`test22`, sharing only `test8`) — each is addressing a real but distinct weakness in the
   current tie-breaking/ordering, not the same underlying issue twice.
3. **Combining them is not simply additive — it can regress.** `part_a_combined.py` fixes the union of
   what each contributes to `test1` and `test22`, but **loses `test8`** (the zero-slack, 9-nurse/6-day
   tight instance), which *both* individual variants fixed on their own. This is a concrete demonstration
   that heuristic interactions in backtracking search are non-monotonic — good empirical evidence to
   include in `report.txt` if either change (or both) is adopted, and a reminder that "benchmark before
   merging" (Section 5's stated goal) is not a formality here.
4. **Neither individually nor combined do these two changes fix `test25` (the large-slack thrashing
   case study) or `test2` (T=600s, still fails at the full budget in all three variants).** This is
   consistent with the report's diagnosis that `test25`'s failure mode (thrashing despite abundant
   solutions) is a different mechanism than what MRV-tiebreak/LCV-quality address — it's the kind of
   case random-restart backtracking (Section B item 4) or conflict-directed backjumping (item 4b) is
   specifically aimed at, and remains untested pending those prototypes. `test2`'s persistence across
   all three variants at the full 600s budget suggests it may need stronger propagation (AC-3/MAC,
   item 3) rather than better ordering alone — also untested pending that prototype.

**Net read**: both cheap changes are worth pursuing further, but *not* as a blind combination — if both
are merged into `part_a.py`, `test8`-like tight-instance regressions need to be specifically re-checked
(e.g. via a targeted re-run against `suite_003/test8` and similar zero/near-zero-slack cases identified
in the correctness report's slack table), or the two orderings should be applied situationally rather
than unconditionally stacked (e.g. degree-heuristic tiebreak generally, hybrid-LCV only past a certain
candidate-count or tightness threshold — worth a follow-up experiment).

## Part B: hill-climbing (cross-nurse same-day swaps + sideways moves + random restart)

Implemented from scratch in `experiments/part_b_hillclimb.py` (the report's recommended primary
approach). Benchmarked against `suite_002`, `suite_003`, `suite_004` — `suite_001` was not run this pass
(time budget; same gap as noted above for Part A).

### suite_002 + suite_004 (25 cases)

**22/25 produced a valid roster (all reported SUBOPTIMAL vs. the bundled model — none MATCHED or
MORE_OPTIMAL), 3/25 FAIL** (`suite_002/test1`, `suite_002/test14`, `suite_004/test1`).

- The 3 failures are a **direct inheritance from Part A's construction-phase struggles**, not a new Part
  B bug: `suite_002/test1` and `suite_004/test1` are exactly the same hard instances already identified
  in Part A's correctness/benchmark data (the current implementation's plain `part_a.solve`, which
  `part_b_hillclimb.py` calls unmodified for construction, can't find a starting roster within its
  reserved share of the time budget). This directly confirms the report's implicit point: **fixing
  Part A's construction bottleneck benefits Part B for free**, since Part B's correctness is currently
  gated on Part A's.
- On the 22 valid cases, the found rosters are meaningfully better than nothing (Part B was previously
  fully unimplemented) but consistently short of the bundled models' optimum: **median cost gap ≈31%
  above the model objective** (e.g. `test16`: 130 vs. 92 model, ≈41% above; `test23`: 96 vs. 12 model,
  ≈700% above at the low-cost end where small absolute gaps read as large percentages; a few cases came
  within 6–12% of the model). No case reached MATCHED/MORE_OPTIMAL.

### suite_003 (9 cases, includes the T=600s adversarial group)

**1/9 PASS (`test9`, trivial), 1/9 SUBOPTIMAL (`test1`: 18 vs. model 6, using the full 600s budget), 7/9
FAIL** — again, every failure is inherited directly from the same Part-A-construction-hard instances
already catalogued in the correctness report (`test2`–`test6` at T=600s, `test7`/`test8` at T=30s).

### Interpretation

The hill-climbing design itself works as intended where it gets the chance to run — it reliably improves
on the initial constructed roster and stays hard-constraint-valid throughout (every non-FAIL case passed
`verify_solution`). Its two current limitations, both addressable in a follow-up pass rather than
indicating a flawed approach:

1. **It's currently only as good as Part A's construction phase**, since `solve_part_b` calls
   `part_a.solve` unmodified. Wiring in a validated Part A improvement (degree-heuristic tiebreak looks
   like the safer standalone candidate given the combined-variant regression above) as Part B's
   construction step would directly reduce these inherited failures.
2. **The cross-nurse-same-day-swap neighborhood alone doesn't reach the bundled models' optimum** on
   most cases (~31% median gap). This isn't unexpected for a single, narrow move type — the report's
   Approach C (parallel local/stochastic beam search over several restarts) or a richer move set (e.g.
   also allowing swaps between a working and a resting nurse, which is still headcount-preserving per
   the correctness report's own reasoning, just not implemented in this first prototype to keep the
   move's effect easy to reason about) are the natural next things to try — not evidence the local-search
   framing itself is wrong.

## What wasn't run this pass (for a follow-up)

- Part A: conflict-directed backjumping and AC-3/MAC prototypes (Section B items 3, 4b) — specifically
  relevant to `test25` and `test2`, which none of the ordering-only changes above fixed.
- Part A: random-restart backtracking (item 4) — also specifically relevant to `test25`.
- A full `suite_001` sweep for any variant, to get a broader (not just adversarial-6-case) regression
  and improvement signal.
- Re-testing the degree-heuristic-only and hybrid-LCV-only variants (not just the combined one) against
  `suite_001`'s full 68-case failure set to see how much of that ~7% baseline failure rate each closes.
- A richer Part B move set (working↔resting swaps) and/or wiring a validated Part A construction
  improvement into `part_b_hillclimb.py`'s `initial_roster` step.
