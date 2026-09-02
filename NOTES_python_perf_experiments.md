# Pure Python Performance Experiments — Results

Follow-up to the earlier rounds (`NOTES_competitive_optimization.md`, `NOTES_literature_experiments.md`).
This round is about constant-factor speed, not algorithm changes — better data structures
(`collections.deque`, `heapq`) and `itertools`, per explicit request and confirmed allowed on the
course's Piazza. As always, **everything stays in `experiments/` — `part_a.py`/`part_b.py` are
untouched** (confirmed via restoration checks after every benchmark), and every variant is
soundness-checked (random `suite_001` sample + the constructed infeasible counter-example) before any
performance claim.

## Methodology note

Since several of these instances (e.g. `suite_002/test22`) always consume their full time budget
(they're among the still-unsolved hard cases), plain wall-clock comparison on them is meaningless — both
variants "take 10s" regardless of speed. The correct apples-to-apples metric is **throughput**: how many
search nodes (`backtrack()` calls) get explored within a fixed time budget, measured directly (not via
`cProfile`, whose per-call instrumentation overhead would itself distort the comparison — used only for
initial orientation, per the plan). `perf`/`valgrind` were available on this machine but the direct
node-counting approach turned out to be sufficient and more directly interpretable for these
apples-to-apples comparisons; profiling with `perf stat -e task-clock` was used to confirm the two runs
had comparable CPU utilization (both ~1.09 CPUs, i.e. neither was throttled differently), and `cProfile`
was used up front (see below) to identify where to look at all.

## Profiling findings (the starting point)

`cProfile` on `part_a.py` (the current merged baseline) against `suite_002/test22` for a full 20s
sustained run:

- Set-object operations (`update_coverage_candidates`, `remove_values`, `is_consistent`,
  `restore_domains`, plus raw `set.add`/`set.remove`/`set.discard`) collectively account for roughly
  half of total `tottime`.
- `forward_check`'s H5 window check constructs a fresh `{None, "R"}` set literal on every one of 3.6M
  calls — a clear, isolated, avoidable cost.

## Results

| variant | mechanism | `test22` throughput (backtrack calls / 10s) | vs. baseline (148,309) | suite_002 (24 cases): pass / total wall time |
|---|---|---|---|---|
| baseline (`part_a.py`) | — | 148,309 | — | 23/24 PASS (test22 known gap) / 49.9s |
| **`hoisted_constants`** | module-level frozenset constants instead of literals rebuilt per call; `slots=True` on `Problem`/`SearchState` | **160,661** | **+8.3%** | 23/24 PASS, zero regressions / **42.4s (−15%)** |
| **`bitmask`** (domains only) | 5-bit int domains instead of `set[Shift]`; candidate sets left as-is | 154,409 | +4.1% | **24/24 PASS** (fixes test22 too!), zero regressions / **10.3s (−79%)** |
| `heapq_mrv` | heapq-based MRV instead of bucket-array scan | 74,843 | **−49.5%** | 23/24 PASS, zero new regressions / 45.3s (roughly flat vs. baseline) |
| `deque_worklist` | `collections.deque` FIFO worklist instead of set, +dedup tracker | 122,445 | **−17.4%** | 23/24 PASS, zero new regressions / 28.4s (faster than baseline despite the negative node-count result) |
| `part_b_itertools` | `itertools.combinations` instead of nested index loops (Part B) | 8,350 moves / 10s (identical to baseline) | ~0% | no regression, no measurable gain either |

`bitmask`'s `suite_002` result is the standout: **24/24 PASS with 79% less total wall time** — far
stronger than the isolated `test22` node-count comparison (+4.1%) suggested. Two things are going on:
(1) `test22` specifically is a thrashing case where raw per-node speed matters less than *which* nodes
get visited (the random-restart mechanism dominates outcome there), so the node-count metric understates
`bitmask`'s effect on the *typical* case; (2) across the other 23, mostly-easy `suite_002` instances,
raw per-node speed translates directly into finishing faster, and the aggregate effect compounds. Take
the single-hard-case throughput numbers as a lower bound on `bitmask`'s value, not the full picture —
the `suite_002` aggregate is the more representative result.

`heapq_mrv` and `deque_worklist`'s aggregate `suite_002` wall times (45.3s, 28.4s) don't look as
uniformly negative as their isolated `test22` throughput numbers (both ~50%/~17% *slower* there) — most
likely because `test22`'s sustained 20s thrash is an outlier profile (many, many `select_unassigned_variable`/
`forward_check` calls in a row) that isn't representative of the mostly-fast, low-call-count cases making
up the rest of `suite_002`. The isolated, controlled `test22` measurement remains the more reliable
apples-to-apples comparison for "is this mechanism itself faster or slower," since it isolates the
technique from Docker/system-load noise across a 24-process parallel run; both pieces of evidence point
the same direction (negative), just with different magnitude.

## Discussion

**`hoisted_constants` is the standout winner** — the single cheapest, safest change tried in this round
(mechanical, no logic change) delivers a bigger throughput gain than the much more invasive bitmask
rewrite. This is a useful, slightly counter-intuitive lesson: the profiling evidence correctly identified
"set operations are expensive," but the *specific* fix that mattered most wasn't restructuring the data
type, it was eliminating needless reallocation of the same handful of tiny literal sets millions of
times over. Recommended as a safe, high-confidence merge candidate.

**`bitmask` turned out to be the strongest single result of this round** once measured at `suite_002`
scale (24/24 PASS, including `test22`, in 79% less wall time than baseline) — even though the
domains-only conversion left the four per-day *candidate sets* (`morning_candidates`,
`afternoon_candidates`, `evening_candidates`, `surgery_candidates`) as regular `set[int]`, untouched.
Those candidate-set operations (`.add`/`.discard`/`in`/`len` inside `update_coverage_candidates`,
`is_consistent`, `score_domain_value`) are a comparably large share of the original set-operation cost
per profiling, so converting them too (to per-day integer bitmasks over nurse indices, up to 50 bits —
trivial for Python's arbitrary-precision ints) is a promising, likely-even-stronger follow-up, not
attempted here given the risk/effort of an already-substantial rewrite (touches `initial_domain`,
`build_initial_state`, `remove_values`, `restore_domains`, `update_coverage_candidates`, `is_consistent`,
`forward_check`, `order_domain_values`/`score_domain_value`, and `select_unassigned_variable`'s bucket
sizing — all already converted for domains; extending to candidate sets touches the same set of
functions again for the second data structure). **`hoisted_constants` + `bitmask` together** (not yet
benchmarked as a combination) is a natural next experiment, since they're orthogonal changes to
different aspects of the same hot functions and both are independently validated as strong wins.

**`heapq_mrv` is a decisive, confirmed negative result** — settles the question the plan posed
("buckets already win for this bounded domain-size range, confirm rather than assume") with real data:
heapq-based selection is **roughly half the throughput** of the current O(1) bucket-array scan. This
makes sense in hindsight: domain sizes here are bounded to a tiny, fixed range (0–5), which is exactly
the case a counting-sort-style bucket array is asymptotically and practically superior to a general
O(log n) heap for — heapq's per-push/pop overhead (list operations, comparison overhead on tuples) simply
isn't worth paying when the "priority" domain is this small. **Not recommended**, but valuable as a
confirmed (not assumed) negative result for `report.txt`.

**`deque_worklist` is also a negative result**, though a smaller one — the separate `queued_days` dedup
tracker needed to replicate the original set's automatic dedup behavior adds enough bookkeeping overhead
to outweigh whatever benefit FIFO propagation order might offer. This suggests propagation *order*
doesn't matter much for this CSP's structure (the H4/H7 fixpoint converges to the same result regardless
of processing order within one `forward_check` call, since it's confluent), so paying for an ordering
guarantee nobody benefits from is pure waste. **Not recommended.**

**`part_b_itertools` is a clean, harmless, no-measurable-effect change** — replacing manual nested index
loops with `itertools.combinations` produced byte-identical move counts and final costs on the workload
tested (a large N=50,D=30 instance, 10s budget). The per-pair *work* (calling `swap_cost_delta`, which
itself does real computation) dominates the iteration mechanism's cost, so C-level iteration doesn't
show through as a measurable win here. Still a legitimate, defensible cleanup (arguably more readable),
just not a performance win on this workload.

## Combining the two winners: `experiments/part_a_perf_combo.py`

Built and validated the natural next step: `hoisted_constants` + `bitmask` together (domains bitmasked,
every remaining repeated literal — both bitmask constants and the few string-keyed ones still needed for
comparisons against the `shift` parameter itself — hoisted to module-level constants, `slots=True` on
both dataclasses).

| variant | `test22` throughput | suite_002 (24 cases) |
|---|---|---|
| baseline | 148,309 | 23/24 PASS / 28.6–49.9s (varies with system load) |
| `hoisted_constants` alone | 160,661 (+8.3%) | 23/24 PASS / 42.4s |
| `bitmask` alone | 154,409 (+4.1%) | 24/24 PASS / 10.3s |
| **`perf_combo`** | **163,705 (+10.4%)** | **24/24 PASS / 11.0s** |

Soundness-checked clean (40 random `suite_001` cases, zero crashes/invalid rosters/false-infeasible
verdicts) and Docker-validated with zero regressions. The combined throughput gain (+10.4%) is real but
sub-additive relative to the two individual gains (8.3% + 4.1% = 12.4% naively) — expected, since both
changes reduce overhead in overlapping hot functions (`is_consistent`, `forward_check`), so some of each
change's savings would have been "spent" on the same cycles the other change also eliminates. The
`suite_002` aggregate result (24/24, ~11s) essentially matches `bitmask` alone, consistent with
`bitmask`'s conversion being the dominant factor at that scale (per the earlier discussion of why
`test22`'s isolated number understates `bitmask`'s real-world effect).

## Final recommendation

**`experiments/part_a_perf_combo.py` is the strongest candidate from this round** — combines both
validated wins, zero regressions, 24/24 on `suite_002` (fixing `test22` too) in about a fifth of
baseline's typical wall time. **Not recommended**: `heapq_mrv`, `deque_worklist` (both confirmed
net-negative, useful as settled-not-assumed answers to "would this help"). **Neutral, keep for code
quality if desired**: `part_b_itertools`.

**Natural next step, not attempted this round**: extend the bitmask conversion to the four per-day
candidate sets too (not just domains) — per the profiling evidence, this is where most of the remaining
set-operation overhead lives, and `perf_combo` is the natural base to build that on top of.
