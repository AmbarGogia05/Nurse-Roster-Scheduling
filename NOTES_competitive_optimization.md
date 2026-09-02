# Competitive Optimization Push — Results

Follow-up to `NOTES_correctness_and_approaches.md` and `NOTES_experiment_results.md`. This covers the
"push as far as possible" pass: broader data-structure experiments, stronger infeasibility pruning, and
—the headline result—a randomized-restart strategy that turned out to be dramatically more effective
than anything tried so far. **As before, everything here stays in `experiments/` — `part_a.py` and
`part_b.py` are untouched; every benchmark run below restores them automatically (confirmed via
`git diff` after every run) and you decide what to merge.**

## Headline result: `experiments/part_a_random_restart.py`

**993/1000 PASS on the full `suite_001` sweep (99.3%), with *zero* regressions** — every one of the 7
remaining failures is a strict subset of the original 68-failure baseline set; no case that baseline
solved is now failing. Baseline was 932/1000 (93.2%). That's an **~90% reduction in the failure rate**
from a single, syllabus-mainstream technique (L05: random restarts).

It also solves **all 6 of the previously-known-hard cases** except `suite_002/test22` specifically:

| case | baseline | random_restart |
|---|---|---|
| `suite_001/test25` (thrashing case study) | FAIL (10s) | **PASS (~1.1s)** |
| `suite_002/test1` (N=50,D=30, 400% slack) | FAIL (20s) | **PASS (~2.2s)** |
| `suite_002/test22` | FAIL (20s) | FAIL (21s) |
| `suite_003/test7` | FAIL (30s) | **PASS** |
| `suite_003/test8` (N=9,D=6, zero slack) | FAIL (30s) | **PASS (~3.1s)** |
| `suite_003/test2` (N=20,D=14, T=600s) | FAIL (600s) | **PASS (~62.5s)** |

Full `suite_002` (24 cases): **23/24 PASS** (only `test22` still fails), total wall time actually
*lower* than baseline (30.8s vs 48.7s) despite solving strictly more cases.

### Why this works — a genuine, surprising finding

The `test25` case study (`NOTES_correctness_and_approaches.md`) already showed the current heuristic
value-scorer (`score_domain_value`) can actively mislead the search on some instances. Direct
experimentation here confirms it concretely: **on `test25`, replacing the heuristic scorer with a
uniformly random one solved the instance on the very first attempt in ~1 second** — while randomizing
only *ties* on top of the existing heuristic (keeping it "in charge") failed even after ~10 restart
attempts with generous per-attempt budgets. This is why `part_a_random_restart.py` is designed the way
it is: the deterministic first attempt is byte-identical to `part_a.py` (so already-fast cases are
completely unaffected — confirmed by the 24/24-minus-1 suite_002 result matching baseline everywhere
except the two genuine improvements), and only when that attempt times out does it fall back to
restarts with **fully random value ordering** (not heuristic-guided), each restart getting a short time
slice (`max(0.5, T*0.1)`) carved from whatever budget remains. A restart's `backtrack()` completing
*without* hitting its slice's deadline is still a valid proof of infeasibility regardless of tie-break
order (forward-checking pruning never removes a genuine solution), so the search is never unsound —
falling back to randomization only ever helps performance, never validity.

### Design detail worth flagging for `report.txt`

This is squarely a **hybrid of backtracking (L04) and random restarts (L05)** — a well-established
combination pattern, not a novel algorithm — but note that the restart mode discards the heuristic
value-orderer entirely rather than randomizing *around* it. That's an empirical finding from this
specific instance mix, not a general claim that heuristic guidance is bad; it should be described
honestly as "random restarts with uniform value ordering, since the current heuristic scorer was found
to actively mislead search on certain instance structures" rather than as a refinement of the scorer.

## A cautionary finding: combining with hybrid-LCV is a net *loss* at scale

Initial testing combined `random_restart` with `hybrid_lcv`'s true-LCV fallback (`part_a_restart_lcv.py`)
since hybrid-LCV alone uniquely fixed `suite_002/test22` (which pure `random_restart` doesn't). The
combined variant looked even better on the small known-hard set — **6/6 PASS**, and 24/24 on
`suite_002` — but a full `suite_001` sweep told a different story:

**`part_a_restart_lcv.py`: 989/1000 PASS (98.9%) — *worse* than pure `random_restart`'s 993/1000, and
with 4 genuinely new regressions** (`test32`, `test39`, `test547`, `test555` — none in the original
68-failure baseline). Confirmed by direct reproduction: baseline solves `test32`/`test39` in ~0.06s
each; `part_a_hybrid_lcv.py` *alone* (no restart involved) times out on the same cases at the full T=10s
budget. This isn't a bug — `true_lcv_score`'s speculative assign/forward-check/restore was checked and
is properly symmetric/side-effect-free — it's a genuine case where the more "theoretically correct" LCV
computation leads the search down a bad path that the cheap heuristic proxy avoids entirely. **No single
value-ordering heuristic dominates across all instance structures**, which is itself a useful, concrete
thing to report.

**Recommendation: use `experiments/part_a_random_restart.py` alone, not the LCV-combined version.**
It's simpler, strictly safer (zero known regressions across 1000+ suite_001 cases plus all of
suite_002/003/004 checked), and only misses one known case (`test22`) that the combined version fixes
at the cost of 4 new failures elsewhere — a bad trade at scale.

## Part B: wiring the improved construction through

`experiments/part_b_hillclimb_v2.py` — identical to the original `part_b_hillclimb.py` design (L05
hill-climbing + sideways moves + random-restart perturbation over cross-nurse same-day swaps) but
constructs its initial roster via `part_a_random_restart.solve` instead of plain `part_a.solve`, since
`NOTES_experiment_results.md` traced every one of Part B's original failures directly to Part A's
construction timing out on the same hard instances documented above.

**Result: 30/34 cases produce a valid roster (up from 24/34 for the original `part_b_hillclimb.py`),
only 4 FAIL** (`suite_002/test22`, `suite_003/test3`, `suite_003/test5`, `suite_003/test6`).

- `suite_002/test22` is the one known case that pure `random_restart` alone doesn't fix in Part A
  either (needs the LCV addition, which was deliberately excluded here for its suite_001 regressions)
  — an expected, explained gap, not a new issue.
- `suite_003/test3`, `test5`, `test6` are 3 of the 6 hardest T=600s cases. `solve_part_b` reserves only
  30% of the budget (~180s) for construction before switching to hill-climbing — some of these instances
  needed most or all of a full T=600s budget for Part A construction alone (per the Part A benchmark
  results above), so 180s isn't enough. **Follow-up**: make the construction/optimization time split
  adaptive (e.g. detect a slow construction and extend its share) rather than a fixed 30/70 split, or
  reuse `part_a_random_restart`'s own internal restart-budget logic directly instead of a single
  fixed-size external slice.
- Objective quality on the 29 SUBOPTIMAL + 1 PASS cases is broadly consistent with the original
  `part_b_hillclimb.py`'s results (median gap in the same range as before) — this pass's construction
  fix targeted *validity*, not cost quality; the cost-quality follow-ups from the original
  `NOTES_experiment_results.md` (richer move neighborhood, cost-aware warm start, beam search) are still
  open and not attempted in this push.

**Recommendation**: `part_b_hillclimb_v2.py` (built on `part_a_random_restart`, not the LCV-combined
version, for the same regression-avoidance reason as the Part A recommendation) is a clear improvement
over v1 and the natural next Part B baseline if you decide to merge — but the fixed 30/70 time-split and
the cost-quality gap remain open follow-ups.

## Data-structure and pruning experiments

### `experiments/part_a_lazy_candidates.py` — batched `update_coverage_candidates` calls

Profiling `test25` showed `update_coverage_candidates` as the single hottest non-recursive function
(2.28s of a 10s budget, 1.34M calls) — the real `part_a.py` calls it once **per value**
removed/restored inside `remove_values`/`restore_domains`, even when several values from the same cell
change together (e.g. H2/H3/H6's `{"M","B","E"}` removals). Batching it to once per cell actually
touched (since it only depends on final domain state, not the removal path) is safe and sound by
construction.

**Measured effect** (same 10s budget on `test25`): backtrack calls **26,908 → 40,872** (+52% more nodes
explored per second), `update_coverage_candidates` calls **1,339,933 → 972,672** (-27%), its cumulative
time **3.05s → 1.88s** (-38%). A genuine, real throughput multiplier — confirmed zero regressions on the
full `suite_002` (24/24 matching baseline exactly). This is a pure speed win with no behavioral change,
so it composes safely with `random_restart` (more nodes/second directly helps every restart slice too) —
**recommend combining the two** (not yet benchmarked together; a natural next step).

### `experiments/part_a_matching_prune.py` — leave-aware global capacity bound

Strengthens `basic_feasibility_checks`'s global bound from the crude `N * K` (which ignores that leave
days remove workable days from a nurse's schedule without reducing `K`) to
`Σ min(K, per_day_cap * (D − that nurse's own leave-day count))`, where `per_day_cap` is 2 for surgical
nurses (a B shift consumes 2 load-units in one day) and 1 for general nurses (who can never hold B).
This is a provably valid Hall's-theorem-style necessary condition — strictly tighter than the original
bound, never looser, so it can only catch *more* true-infeasible instances, never produce a false
positive.

**Constructed a concrete counter-example** (`experiments/test_leave_capacity_infeasible.csv`: 8 general
nurses, 10 days, 3 nurses with heavily concentrated leave making the instance genuinely infeasible
despite every single day individually having enough available headcount — the old per-day check can't
see this, only a cross-day capacity argument can) to validate the improvement is real, not just
theoretical:

- Baseline `part_a.py`: takes the full T=5s budget doing real (unproductive) search before concluding
  infeasible.
- `part_a_matching_prune.py`: concludes infeasible in **0.045s** — a **~112x speedup**, both agreeing on
  the same (correct) answer.

Confirmed zero regressions on feasible instances (full `suite_002`, 24/24 matching baseline). This
directly addresses the "explore pruning to speed up no-solution cases" request — the improvement is
narrowly scoped (only changes the pre-search feasibility check, never touches the actual search path for
feasible instances) so it's essentially risk-free to combine with anything else.

### `heapq` / `deque` exploration

Per the plan, considered but not implemented as separate experiments: bucket-array MRV selection
(current design, domain sizes bounded 0–5) is already an O(1) counting-sort-style structure that a
`heapq`-based priority selection (O(log n)) cannot beat for this specific bounded-size case — confirmed
by inspection rather than by building and losing to it. `collections.deque` for `forward_check`'s
`dirty_days` worklist (currently a `set`, arbitrary pop order) was not benchmarked this pass; given how
much of the total win came from `random_restart`, this is a lower-priority follow-up rather than
something skipped for cause.

### Symmetry breaking, backjumping, AC-3/MAC, portfolio strategies

Not implemented this pass — `random_restart`'s result was strong enough, and found early enough in the
breadth-first exploration, that further Part A search-strategy work has diminishing expected returns
relative to effort (7 failures remain out of 1000, several already fixed on their own; further gains are
in a much smaller remaining pool). Worth a follow-up specifically targeting the 7 remaining suite_001
failures and `suite_002/test22` if more time is available, but not undertaken here.

## Summary table (Part A)

| variant | suite_001+002 combined (1024) | 6 known-hard | regressions | total checker wall time |
|---|---|---|---|---|
| baseline (`part_a.py`) | 953/1024 (93.1%) | 0/6 | — | 1223.1s |
| `part_a_degree_heuristic` | not run at 1024-scale | 3/6 | none found (suite_002-scale) | — |
| `part_a_hybrid_lcv` (alone) | not run at 1024-scale | 3/6 | **yes** (test32/test39 confirmed) | — |
| `part_a_restart_lcv` (combined) | 989/1000 suite_001 only (98.9%) | 6/6 | **4 new** (test32/test39/test547/test555) | — |
| `part_a_random_restart` | 993/1000 suite_001 only (99.3%) | 5/6 | none | — |
| **`part_a_best_combo`** (random_restart + lazy_candidates + matching_prune) | **1017/1024 (99.3%)** | **5/6** | **none** | **691.1s** |

**`part_a_best_combo.py` is the final recommendation**: combines the three independently-validated,
zero-regression improvements. Fully validated on the complete `suite_001` (1000 cases) + `suite_002`
(24 cases) = 1024-case sweep in one run: **1017/1024 PASS (99.3%), zero regressions relative to
baseline** (every one of the 7 remaining failures — `test228`, `test332`, `test337`, `test635`,
`test656`, `test84`, `suite_002/test22` — was already failing in baseline; no case baseline solved is
now failing), **and 43% less total checker wall time than baseline** (691.1s vs 1223.1s) despite solving
64 more cases. The only known gap is `suite_002/test22`, which needs the hybrid-LCV addition that was
deliberately excluded for its own regressions elsewhere (see above) — a reasonable, explained trade-off
rather than an oversight.
