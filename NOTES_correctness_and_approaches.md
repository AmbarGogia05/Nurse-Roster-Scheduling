# Correctness Check + Approach Exploration — Nurse Roster Scheduling

This note supports the Assignment 1 (nurse rostering CSP) implementation. It covers:
(A) a real correctness/performance verdict for the current `part_a.py`, obtained by running the
unofficial `checker/` test suites (2034 cases with model solutions) inside a network-isolated Docker
sandbox; (B) a prioritized menu of candidate improvements for Part A; (C) a from-scratch design menu
for Part B (currently unimplemented); (D) explicit scope notes. No changes were made to `part_a.py` or
`part_b.py` in this pass — this is an exploration/report deliverable only.

Course constraint driving everything below: solutions must stay in the **search/CSP family** and
"adjacent techniques" to what's actually taught (see `Slides/`) — not fundamentally different
mathematical machinery (no ILP/SAT solvers, no ML). Confirmed in-scope from the slides:
- **L04 (Constraint Satisfaction)** — explicitly worked a "Nurse Scheduling Problem" CSP example.
  Backtracking search, MRV, degree heuristic (MRV tiebreak), LCV, forward checking, arc consistency,
  AC-3, k-consistency.
- **L05 (Local Search)** — hill-climbing (steepest-ascent), local beam search, stochastic beam search,
  random restarts, random walk, stochastic hill climbing, sideways moves.
- **L06 (Informed search)** — A*/IDA*/greedy best-first; less directly applicable to a fixed-size CSP
  like this one, but the heuristic-design concepts (admissibility, relaxation, dominance) are relevant
  background for scoring functions.
- **Not** in the slides: simulated annealing, genetic algorithms, min-conflicts by name. Treat these as
  out-of-scope/borderline for this course's explicit framing, even though they're standard AIMA
  local-search topics — don't lean on them as the primary technique.

---

## A. Correctness / performance findings (checker run, Dockerized)

Harness: `docker/Dockerfile.checker` (python:3.10-slim, non-root user, nothing baked in but Python) +
`scripts/run_checker.sh` (`docker run --network none --read-only -v repo:ro --tmpfs /tmp ...`), running
`checker/check.py` against the current, unmodified `part_a.py`. `part_b.py` is still the starter stub,
so only `--part a` was run (a `--part both` run would trivially fail every Part B case — not
informative yet).

### suite_001 (1000 cases, `-j 8`) — full sweep

**Summary: 932/1000 PASS, 68/1000 FAIL.** Every one of the 68 failures was independently cross-checked:
- All 68 failed by hitting the T budget almost exactly (reported `seconds` ≈ T), i.e. genuine
  `SearchTimeout`s, not crashes or `RuntimeError`s.
- All 68 have a **non-empty (feasible) bundled model solution** — none are cases where `part_a.py`
  correctly detected infeasibility; every failure is a real, solvable instance the search didn't finish
  in time.
- All 68 belong to the `T=10s` budget group (700 of the 1000 cases; `N` 8–50, `D` 1–30). **Zero**
  failures occurred in the `T=3s` group (300 cases, smaller `N` 3–12, `D` 2–8) — so the failure rate is
  concentrated entirely in the larger/harder-instance group, ≈9.7% (68/700) of it, and is exactly zero
  elsewhere. No soundness issue (bad output, wrong invalid/valid verdict) surfaced anywhere in the 1000
  cases — this is a **pure search-performance gap**, not a correctness bug.

### suite_002 (24 cases, N up to 50, D=30, T=20s) — `-j 8`, reproduced twice (deterministic)

- **22/24 PASS**; **2/24 FAIL by timeout at exactly the T=20s budget** (`test1.csv` N=50,D=30 ~20.2–20.3s;
  `test22.csv` N=49,D=30 ~20.2–20.3s), reproduced identically across two separate runs.
- Both instances confirmed **genuinely feasible** via their bundled model solutions (1500 and 1470
  nurse-day keys respectively, non-empty).

### suite_003 (9 cases; six of them N/D up to 50/30 with a generous T=600s budget, three smaller with
T=30s) — `-j 6-8`, full sweep completed

**Final: 2/9 PASS, 7/9 FAIL.** This suite is a mostly-adversarial hard-instance collection, not a
representative sample — treat the 22% pass rate as "these are the deliberately hard cases," not as a
general failure rate estimate (suite_001's ~93% pass rate is the more representative baseline).

- **PASS**: `test1` (N=14,D=10, ~83–156s), `test9` (~0.5s).
- **FAIL by timeout, all seven confirmed feasible via bundled model solutions** (no soundness issue,
  every failure is a real solvable instance the search didn't finish in time):

  | case | N | D | K | T budget | slack % | seconds taken |
  |---|---|---|---|---|---|---|
  | test8 | 9 | 6 | 2 | 30s | **0%** | ~30.2–30.6s |
  | test7 | 14 | 21 | 8 | 30s | 6.7% | ~30.2–30.6s |
  | test3 | 30 | 20 | 13 | 600s | 8.3% | ~600.2s |
  | test5 | 50 | 30 | 17 | 600s | 4.9% | ~600.3s |
  | test2 | 20 | 14 | 10 | 600s | 19.0% | ~600.3s |
  | test6 | 50 | 30 | 22 | 600s | 22.2% | ~600.3s |
  | test4 | 50 | 30 | 20 | 600s | 38.9% | ~600.2s |

  `test8` (**N=9, D=6, exactly zero slack**) is notable: a tiny 9-nurse/6-day instance timing out at
  30s is a much stronger signal than the large-N cases — the gap isn't purely about state-space size,
  it's also about search-order/propagation quality on tightly-constrained structures. The rest of the
  table reinforces the two-regime split from the diagnostic below: `test7`/`test3`/`test5` are tight
  (<10% slack), `test2`/`test6`/`test4` are looser (19–39%) yet still fail at the full 600s budget on
  large (N up to 50, D=30) instances.

### suite_004 (1 case, N=50,D=30, T=30s)

- **FAIL by timeout** at ~30.6s. Not separately cross-checked for feasibility but pattern-consistent
  with the suite_002/suite_003 large-instance timeouts above.

### Interpretation

**No soundness bug surfaced across any of the 1000+34 cases run** (suite_001 in full, suite_002/003/004
sampled twice): no case where `part_a.py` produced a roster the verifier rejected as invalid, and no
case where it wrongly reported infeasibility for a feasible instance. This is a strong, checker-verified
confirmation of the manual code review's conclusion that `is_consistent`/`forward_check` are sound. The
commit message **"fixed H5 bug"** (commit `70bed60`) remains misleading on inspection: diffing it against
the prior commit shows the only change was narrowing `forward_check`'s H5 propagation scan window
(`range(problem.D - 4)` → `first_window_start=max(0,day-4)`/`last_window_start=min(day, problem.D-5)`),
a pure performance optimization — both forms compute the identical boolean result. No evidence of an
actual prior H5 correctness bug exists in the visible diff history.

The real, checker-confirmed issue is **performance, not correctness**: roughly 7% of instances overall
(concentrated in the harder/larger `T=10s` group of suite_001, plus several suite_002/003/004 cases up
to N=50,D=30, plus at least one surprisingly *small* N=9,D=6 instance) are genuinely feasible but exceed
the T budget under the current backtracking + MRV + forward-checking + heuristic-value-ordering search.
This is concrete, measured evidence — not speculation — motivating Section B below, and specifically
supports prioritizing degree-heuristic tiebreaking and improved value ordering (items 1–2) first, since
the `test8` small-instance failure suggests search-order quality, not just scale, is a real factor.

### Diagnostic: two distinct failure patterns, not one

Computing each failing instance's total shift-unit **supply-vs-demand slack** — `N·K` (total shift
capacity across all nurses) minus `(m+a+e)·D` (total shift-units demanded across all days) — splits the
failures into two clearly different regimes:

| instance | N | D | K | slack (`N·K − (m+a+e)·D`) | slack % of demand |
|---|---|---|---|---|---|
| suite_002/test1 | 50 | 30 | 21 | **840** | 400% |
| suite_002/test22 | 49 | 30 | 6 | 24 | 8.9% |
| suite_003/test2 | 20 | 14 | 10 | 32 | 19% |
| suite_003/test7 | 14 | 21 | 8 | 7 | 6.7% |
| suite_003/test8 | 9 | 6 | 2 | **0** | 0% |
| suite_004/test1 | 50 | 30 | 11 | 10 | 1.9% |

- **Regime 1 — near-zero-slack "tight" instances** (`test8`, `test7`, `suite_004/test1`, and to a
  lesser extent `test22`/`test2`): the total available shift-capacity barely exceeds (or, for `test8`,
  exactly equals) total demand. This is a classic hard combinatorial structure — close to an exact-cover
  problem — where naive chronological backtracking thrashes because almost every nurse-day assignment
  choice has global ripple effects on whether the remaining budget can still cover the remaining demand,
  and forward checking alone (which only looks at directly adjacent cells) doesn't detect these
  budget-exhaustion dead-ends early. This is exactly the profile that **stronger propagation (AC-3/MAC,
  item 3) and degree-heuristic ordering (item 1)** are meant to address — tight instances are where
  additional constraint propagation earns back its overhead most reliably.
- **Regime 2 — large-scale but slack-rich instance** (`test1`: 400% slack, meaning roughly 4x more
  capacity than needed — this instance is *not* combinatorially tight, many valid rosters should exist)
  still fails to be solved in 20s despite abundant feasible solutions existing. This points to a
  **different** bottleneck: at `N=50, D=30` (1500 variables), either per-node cost (the incremental
  forward-checking/propagation work done at every assignment) is high enough that even a
  moderately-branchy search exhausts the time budget, or the current heuristic value-ordering
  (`score_domain_value`) is misleading the search into a bad region of the tree despite many solutions
  being reachable elsewhere. This profile is better addressed by **items 1–2 and 4** (degree-heuristic
  tiebreak, better/hybrid LCV, and random-restart backtracking with randomized tie-breaking to escape a
  single bad greedy trajectory) — pure propagation strength (AC-3/MAC) is less likely to help here since
  the problem isn't that dead-ends are hard to detect, it's that the current ordering isn't finding one
  of the many valid solutions quickly.

Practical implication for Section B: **no single technique covers both regimes** — the recommended order
(degree heuristic → hybrid LCV → AC-3/MAC → random restarts) should be validated against *both* a
tight-budget instance (e.g. `test8`) and a slack-rich large instance (e.g. `test1`) when benchmarking,
since a change that helps one regime is not guaranteed to help the other.

Re-running this slack analysis across all **68 suite_001 failures** (not just the six spot-checked
above) confirms the split is real at scale, not an artifact of a small sample: **23/68 (34%) are
tight** (<15% slack, several at exactly 0%), **45/68 (66%) are slack-rich** (≥15% slack, several above
100–300%). So both regimes are common failure modes, not a minor edge case.

### Case study: a tiny, extremely slack-rich instance still times out (likely thrashing, not scale)

The slack-rich group includes a genuinely surprising outlier: `suite_001/test25.csv` — **N=40, D=2,
K=1, no leaves, only 80 variables total**, with **100% slack** (40 shift-unit capacity vs. 20 units of
demand — needing only 20 of the 40 nurses across both days, with zero symmetry-breaking obstacles, no
leave constraints, no B/surgical complexity at all since both days are general). Reasoning about this
instance by hand, a solution is close to trivial to construct (assign any 10 nurses to day 0's
requirements and any 10 *different* nurses to day 1's, rest everyone else) — yet `part_a.py` fails to
find one within the 10s budget.

Reproduced directly (bypassing Docker/checker, running the repo's own `part_a.py` locally — no need to
sandbox the project's own trusted code): confirmed to reliably burn the full 10s and return `{}`.
Profiling (`cProfile`) shows the search is not stuck in one expensive call — it's doing real, if
unproductive, work: **~26,900 `backtrack` calls and ~101,000 `forward_check` calls in 10 seconds**
(≈2,700 assign/unassign cycles/sec) across only 80 variables, without ever reaching a solution. This is
classic chronological-backtracking **thrashing**: repeatedly re-exploring structurally similar dead-end
subtrees because a bad early choice isn't identified and specifically blamed — the search backtracks to
the most recent choice point (standard backtracking) rather than the choice that actually caused the
conflict, so it can retry many "different but equivalent" combinations of a later variable before ever
revisiting the actual culprit. This is a strong, concrete demonstration (not just a plausible mechanism)
that the current MRV-tie-breaking-by-arbitrary-order and the heuristic value-scorer can actively steer
the search into a bad region even when solutions are abundant nearby in the search tree — directly
motivating **degree-heuristic MRV tiebreaking and improved/hybrid LCV (Section B items 1–2)**, and
making **random-restart backtracking (item 4)** look more immediately valuable than originally assessed,
since a restart with different tie-breaking would very plausibly resolve this specific case almost
immediately (many equally good starting choices exist; the current run just committed to a bad one and
never recovered).

This case also makes **conflict-directed backjumping** worth naming as an additional candidate, adjacent
to plain backtracking + forward checking (it's a direct extension of the same backtracking framework
L04 teaches, and AIMA covers it in the same CSP chapter as forward checking) — but it was **not
explicitly named in the slides** (only MRV, degree heuristic, LCV, forward checking, arc
consistency/AC-3, and k-consistency were), so treat it with the same "prototype-and-benchmark, frame
carefully in `report.txt` if used" caution already applied to AC-3/MAC and random restarts, rather than
as a default recommendation.

---

## B. Candidate approaches — Part A (ranked, syllabus-scoped)

Given the checker run's concrete evidence of T-budget timeouts on feasible N=50,D=30-scale instances,
these are worth pursuing roughly in this order:

1. **Degree-heuristic MRV tiebreak** (low effort, likely helps most directly on the observed
   timeout-prone instances). `select_unassigned_variable` (`part_a.py:270-277`) currently picks
   `next(iter(bucket))` — arbitrary order among MRV ties. L04 teaches degree heuristic as the standard
   tiebreaker: among cells tied for minimum domain size, prefer the `(nurse, day)` on the day with the
   most other still-unassigned cells (a proxy for "most constraining," since same-day cells compete for
   the fixed `m`/`a`/`e` headcounts). `state.unassigned_on_day` is already tracked
   (`part_a.py:70,460,479`), so this is close to free to add. The `test25` case study below (a tiny,
   80-variable, 100%-slack instance that still thrashes for ~27,000 backtrack calls without a solution)
   is direct evidence that arbitrary tie-breaking is actively hurting the search, not just leaving
   performance on the table.

2. **Hybrid true-LCV for cells with few remaining candidate values** (low-medium effort). The commit
   history shows true LCV (speculative assign + forward-check + count + restore) was replaced by the
   current cheap heuristic scorer (`score_domain_value`, `part_a.py:280-350`) for speed, with the commit
   message itself flagging the weights as "as-yet-untuned." A middle ground: fall back to true LCV only
   when `order_domain_values` has ≤2–3 consistent candidates left for a cell — cheap to compute exactly
   there, more accurate than the heuristic proxy, and doesn't pay full-LCV cost everywhere.

3. **AC-3 preprocessing, or MAC during search** (medium effort, uncertain marginal payoff). Squarely
   in-scope (L04). The existing `forward_check` already does incremental, worklist-based propagation
   (`dirty_days` fixpoint, `part_a.py:552-624`) that is somewhat AC-3-like in spirit, so the *marginal*
   benefit over plain textbook forward checking may be smaller here than usual. Recommend prototyping
   only after items 1–2 are tried and benchmarked against the checker suites — don't invest
   speculatively given the uncertain payoff and real per-node overhead risk.

4. **Random-restart backtracking with randomized tie-breaking** for instances that still time out after
   1–3 (medium effort, situational, but promoted in priority by the `test25` case study — thrashing
   caused by one bad early tie-break is exactly what a restart with different randomized choices would
   plausibly escape almost immediately). Random restart is explicitly named in L05; applying it to
   systematic CSP backtracking (rather than local search proper) is a reasonable adjacent framing.
   Requires careful time-budget slicing across restarts given the strict per-instance `T`.

4b. **Conflict-directed backjumping** (medium effort, mechanistically well-matched to the `test25`
   thrashing pattern, but **not explicitly named in the slides** — only MRV/degree/LCV/forward
   checking/AC-3/k-consistency were). It's a direct, same-chapter extension of plain backtracking (AIMA
   covers it alongside forward checking), so it's defensible as "adjacent," but should be prototyped and
   benchmarked rather than assumed, and framed carefully in `report.txt` as an extension of the taught
   backtracking framework if used — same caution level as AC-3/MAC and min-conflicts below.

5. **Min-conflicts / local-search-repair fallback for Part A — not recommended.** Local search generally
   is taught (L05), but min-conflicts by name is not in the slides, and Part A's tightly-coupled hard
   constraints (H4's exact per-day headcounts, H7's per-day surgical coverage) don't decompose cleanly
   into single-cell "fix the worst conflict" repairs — a one-cell change can break H4 on two different
   days at once. Only reconsider if items 1–4 don't close the gap on suite_001/suite_002/suite_003, and
   frame it very carefully in `report.txt` as an explicitly local-search-derived fallback (not the
   textbook min-conflicts algorithm) if it's ever used.

Tuning note: since `score_domain_value`'s constants (`5`, `2`, `5`, `-5` at `part_a.py:312,314,343,348`)
are explicitly flagged as untuned, any of the above should be benchmarked against the checker suites
(pass/fail/timeout counts and timing) before/after, not adopted on intuition alone — suite_002 (24
cases, fast) and the six T=600s suite_003 cases are a good fast/slow pairing for iteration.

---

## C. Candidate approaches — Part B (from scratch; currently unimplemented)

`part_b.py` is still the 26-line starter stub — no solver, no output writing. `verifier.calculate_objective`
(both the root copy and `checker/verifier.py`'s copy) was independently confirmed to implement the
spec's cost formula correctly: `C = 9·Σᵢ(1/3)[(Cᵢ,M−μᵢ)²+(Cᵢ,A−μᵢ)²+(Cᵢ,E−μᵢ)²]` reduces algebraically to
`Σᵢ[3(m²+a²+e²) − total²]` per nurse, exactly what `calculate_objective` computes. The objective is
**separable per nurse given a fixed per-nurse total workload** — minimized when a nurse's M/A/E counts
are as equal as possible — which matters directly for designing cheap local moves.

Three candidate approaches, all from the taught local-search family (L05):

- **Approach A — constructive (cheap warm start).** Bias `part_a.py`'s value-ordering scorer toward
  evenness of M/A/E per nurse and reuse the CSP backtracking engine directly for construction. Minimal
  new code; correctness inherited for free since any complete assignment the engine returns is still
  H1–H9-valid by construction. Downside: greedy/short-sighted, no post-hoc improvement.

- **Approach B — repair/local search (recommended primary).** Start from a valid Part-A roster, then
  hill-climb via **cross-nurse same-day shift swaps**: pick a day and two working nurses on that day,
  swap their shift assignments. This move is headcount-preserving *by construction* (same multiset of
  shifts assigned that day, so H4/H7 stay satisfied automatically without rechecking), leaving only a
  cheap, localized recheck of H2/H3/H5/H6/H8 around the swapped day for the two nurses involved (not a
  full-roster re-verification). Use steepest-descent hill-climbing with a bounded number of sideways
  moves to escape plateaus, and random-restart hill-climbing (fresh Part-A solves with randomized
  tie-breaking, or perturbations of the current best) if time remains — all explicitly named L05
  techniques. The objective's separability (per-nurse, given fixed workload) means each candidate
  swap's cost delta is O(1) to evaluate from cached per-nurse `(m_i, a_i, e_i)` counts, not an O(N·D)
  rescan.

- **Approach C — stochastic/local beam search variant.** Maintain k valid rosters in parallel (from k
  Part-A solves with randomized ordering, or k perturbations of one base roster), apply one improving
  move to each per round, return the best. More expensive per round; worth adding only if plain
  hill-climbing (Approach B) plateaus too early empirically.

**Recommendation: B as the primary optimizer, A as a cheap warm-start feeding into B** — fewer
hill-climbing iterations needed to converge if the starting roster is already construction-biased toward
evenness.

Reuse surface already available in `part_a.py` for whenever Part B implementation is taken up: `Problem`,
`parse_input`, `solve`, `roster_to_json`, `write_solution` are all cleanly importable as-is (no
import-time side effects — `main()` is gated behind `if __name__ == "__main__":`). Threading an optional
`scorer` parameter through `solve` → `backtrack` → `order_domain_values` (the latter already accepts a
`scorer` argument, `part_a.py:358`, but `solve`/`backtrack` don't yet expose it) would be a minimal,
backward-compatible change enabling Approach A without duplicating any backtracking code in `part_b.py`.
Noted here as a prerequisite for a future implementation pass, not built in this one.

---

## D. Scope notes

Per explicit direction, this pass is **exploration + report only**: it built the Docker sandbox
(`docker/Dockerfile.checker`, `scripts/run_checker.sh`), ran it against the current `part_a.py`, and
produced the findings/approach menu above. **No changes were made to `part_a.py` or `part_b.py`.**
Implementing any of the Section B/C items is a separate, future pass.
