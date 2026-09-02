# Literature-Driven Experiments — Results

Follow-up to `NOTES_literature_review.md`. Each of the 5 in-scope/defensible search techniques (plus a
GCC-style filter) was prototyped and benchmarked against the Dockerized checker. All forked from the
current `part_a.py` on `experiments_llm` (random-restart + batched candidate updates + leave-aware
infeasibility bound) or `part_b.py` (hill-climbing), so results are measured *on top of* that already-
validated baseline, not from scratch. **As before, everything stays in `experiments/` — `part_a.py`/
`part_b.py` are untouched** (confirmed via restoration checks after every benchmark run below).

## Soundness first

Before any performance claim, every variant was checked for soundness: run against ~25–40 random
`suite_001` cases each, comparing produced output against the bundled model solutions (any roster
produced was independently re-verified; any case the model says is feasible was checked for a false
"infeasible" verdict). **Zero soundness bugs found across all 5 Part A variants** (`mac`, `cbj`,
`domwdeg`, `luby_restart`, `gcc_filter`) after one real bug was caught and fixed during development (see
below).

**One implementation bug caught and fixed during development**: the first draft of `part_a_cbj.py`
unconditionally called `restore_domains`/`unassign` after every recursive call, including on *success* —
destroying the very solution it had just found (the search claimed `solved=True` while returning an
all-`None` roster). This was caught immediately by the standard sanity check (verify the output against
`verifier.py`) before any benchmarking, fixed (only restore/unassign on the failure path), and
re-verified clean. Noted here as a concrete example of why every experiment in this project is
soundness-checked before any performance claim is trusted.

## Headline results — fast known-hard-case set (6 cases)

| variant | known-hard set (5 fast cases) | notes |
|---|---|---|
| baseline (current `part_a.py`) | 4/5 (misses `test22`) | — |
| `mac` | 4/5 (misses `test22`) | no change vs. baseline on this set |
| `cbj` | 4/5 (misses `test22`) | no change vs. baseline on this set |
| `domwdeg` | 4/5 (misses `test22`) | no change vs. baseline on this set |
| **`luby_restart`** | **5/5** (fixes `test22`!) | fastest total time of all variants tried (22.8s vs. baseline's 30.1s) |
| **`gcc_filter`** | **5/5** (fixes `test22`!) | fastest overall (18.4s) |

Both `luby_restart` (Luby-sequence-scheduled restart cutoffs replacing the fixed 10%-of-budget slice)
and `gcc_filter` (a dynamic, during-search generalization of the leave-aware infeasibility bound, using
live candidate-set unions to catch cases where per-category counts look individually sufficient but
overlapping nurse eligibility makes them jointly infeasible) **independently solve `test22`**, the one
case that survived every earlier round of experimentation (`random_restart` alone, `degree_heuristic`,
plain `hybrid_lcv`) — see `HANDOFF_experiments_llm.md`'s "Known limitations."

## The catch: neither holds up at `suite_002` scale

Re-running both against the **full `suite_002`** (24 cases, the same suite the merged `part_a.py`
currently passes 24/24 with zero regressions) told a very different story:

| variant | suite_002 (24 cases) | regressions vs. current `part_a.py` (24/24) |
|---|---|---|
| `luby_restart` | 21/24 | **3 new failures**: `test1`, `test9`, `test14` |
| `gcc_filter` | 17/24 | **7 new failures**: `test1`, `test6`, `test9`, `test14`, `test15`, `test16`, `test21` |

All of these are cases the current `part_a.py` solves cleanly. This is a genuine regression, not noise
— reproduced consistently. Root-caused for `luby_restart`: the Luby sequence's first term is `1`, so
with a small base unit (`max(0.2, T*0.02)`, chosen to keep early restarts cheap) the **deterministic
first attempt only gets a tiny slice** (~0.4s for a T=20s instance) before the search gives up on the
reliable heuristic-guided path and switches to random-ordering restarts — for cases the heuristic would
have solved quickly given a normal-sized first attempt (as the current `part_a.py`'s fixed 10%-of-budget
slice provides), this premature abandonment costs more than it gains, especially under the CPU
contention of a `-j8` parallel checker run (more processes competing for the same cores makes marginal
per-attempt overhead — `build_initial_state`'s O(N·D) rebuild, paid every restart — matter more). Read on
`gcc_filter`: its dynamic union-of-candidates check adds real per-propagation-step overhead (computing
set unions and sums at every dirty day during every `forward_check` call) — for already-easy cases,
that's pure overhead with no compensating benefit, and it appears to tip several borderline-timed cases
over budget.

**Practical implication**: both ideas are real, validated, non-obvious wins on the *specific* structural
weakness `test22` represents, but as currently parameterized they're a net loss across the broader case
distribution. This is directly analogous to the earlier `hybrid_lcv`/`part_a_restart_lcv` finding
(`NOTES_experiment_results.md`) — a technique that looks strictly better on a small hand-picked hard set
can still be a net regression at scale, and the fix isn't "don't use it," it's "gate it more carefully."
**Recommended follow-up, not done in this pass**: give the deterministic first attempt a full,
un-shrunk slice (matching the current `part_a.py`'s behavior exactly) and apply the Luby-scheduled
restarts only to the *subsequent* restart loop, not the first attempt; similarly, only enable the
`gcc_filter` union check when the simpler per-category checks are already close to their bound (e.g.
only compute it when `total_needed` is within some small margin of the sum of individual category
bounds), rather than unconditionally on every propagation step.

## MAC, CBJ, dom/wdeg — 150-case `suite_001` random sample

| variant | pass rate | total checker wall time | vs. baseline |
|---|---|---|---|
| baseline | 150/150 | 103.6s | — |
| `mac` | 150/150 | 133.3s | **+29% slower**, zero pass-rate benefit |
| `cbj` | 150/150 | 132.6s | **+28% slower**, zero pass-rate benefit |
| `domwdeg` | 150/150 | 107.3s | +3.6% slower, zero pass-rate benefit |

This random 150-case sample happened not to include any instance the current `part_a.py` fails on
(baseline: 150/150), so it can't show a pass-rate improvement for any variant here — but it's still a
clean, honest measurement of **overhead on already-easy cases**, and the result is a direct, textbook
confirmation of the literature's own caveat (Sabin & Freuder 1994, cited in `NOTES_literature_review.md`):
MAC's stronger propagation costs real time per search node, and when a case doesn't need that extra
pruning strength (the existing worklist-based forward checking already resolves it), that cost is pure
overhead with nothing to show for it. CBJ shows essentially the same overhead here for a related reason:
the conflict-set bookkeeping (`blamed_cells`/`deepest_in_stack`) runs on every failed value/forward-check
regardless of whether a jump ever triggers, and on easy instances few or no jumps ever fire, so the
bookkeeping cost is paid without ever being cashed in. `domwdeg`'s near-zero overhead (+3.6%) makes sense
by the same logic — its extra cost is a single dict/array write per forward-check failure, far cheaper
than CBJ's conflict-set operations or MAC's transitive propagation.

**Practical implication**: MAC and CBJ, despite being rated "solidly in scope" in the literature review,
are **not recommended as unconditional additions** given this overhead — they'd need to be gated (e.g.
only activate strong propagation after the deterministic attempt has already timed out once, similar to
how the random-restart fallback is already gated) to avoid taxing the easy majority of instances to help
a minority of hard ones. This wasn't attempted in this pass. `domwdeg`'s near-zero overhead makes it the
safest of the three to consider merging outright, though this sample gives no evidence of it *helping*
either — it would need testing specifically against known-hard instances at scale (the `suite_001`
68-failure set) to establish real benefit, which wasn't run this pass due to time.

## Part B: VNS (3-nurse cyclic exchange, VND-style neighborhood escalation)

Benchmarked against `suite_002` (24 cases), compared to the current `part_b.py` baseline:

| variant | valid rosters | avg. cost gap vs. bundled model |
|---|---|---|
| baseline | 23/24 (1 FAIL) | 129.8 |
| `vns` | 24/24 | 132.5 |

**Honest reading, not a clear win**: `vns` produced one more valid roster (though this specific
difference is more likely explained by run-to-run timing variance on a borderline case — same underlying
`part_a` construction — than a genuine VNS effect; not confirmed independently). More importantly, the
**average cost gap is slightly worse** (132.5 vs. 129.8) despite the larger neighborhood. The likely
mechanism: exhaustively scanning the 3-nurse-cyclic-exchange neighborhood (`best_cycle_move`, O(w³) per
day where w is the day's working-nurse count) adds real per-iteration cost; within the same fixed time
budget, that's fewer total hill-climbing/restart iterations available to the plain pairwise-swap
neighborhood, which on this benchmark's instance sizes apparently mattered more than the extra
neighborhood breadth. **Not recommended for merge as-is.** A more promising follow-up (not attempted
here): only invoke the 3-cycle neighborhood scan when the pairwise-swap neighborhood is *actually*
exhausted (already the current gating) *and* remaining time budget is large enough to amortize the O(w³)
cost — i.e. make the escalation time-aware, not just improvement-aware.

## Overall takeaways for `report.txt`

1. Every technique surveyed as "solidly in scope" or "defensible extension" in the literature review was
   implementable without introducing a soundness bug (after fixing the one CBJ bug caught early) — the
   literature's scope judgments held up in practice, not just in theory.
2. Two techniques (`luby_restart`, `gcc_filter`) found a genuine, previously-unsolved case (`test22`) —
   real evidence the literature-driven search was worthwhile, not just confirmatory.
3. Both of those same techniques also demonstrate, concretely, why "helps on the hard cases we already
   know about" is not sufficient validation — broader regression testing at `suite_002` scale caught real
   costs that the narrow known-hard-case set completely missed. This is the same lesson the earlier
   `hybrid_lcv` finding taught, now confirmed a second time with an independent pair of techniques.
4. None of MAC, CBJ, or dom/wdeg (pending the 150-case sample) showed a measurable difference from the
   current baseline on the small known-hard set — plausible explanation: the current `part_a.py`'s
   existing worklist-based forward-checking propagation and random-restart fallback already capture most
   of what these techniques would add on *this specific* CSP's structure (see each variant's own
   docstring for why — e.g. MAC's extra propagation is scoped to sequence constraints the existing code
   already handles reasonably well via direct-neighbor pruning).
