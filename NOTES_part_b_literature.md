# Part B Literature Review — Local Search Refinements + Non-Local-Search Alternatives

Two research passes for Part B's exact objective (`C = 9·Σᵢ (1/3)[(Cᵢ,M−μᵢ)²+(Cᵢ,A−μᵢ)²+(Cᵢ,E−μᵢ)²]`,
a quadratic per-nurse workload-balance penalty), filtered against the same course-scope constraint used
throughout this project. Each item gets an explicit verdict: **solidly in scope**, **defensible adjacent
extension**, or **likely out of scope**.

## Part 1: Local-search refinements to the existing hill-climber

| # | Idea | Verdict | Effort | Notes |
|---|---|---|---|---|
| 1 | Delta-evaluation via `S2=ΣC²` sufficient statistic (`Σ(C−μ)²=ΣC²−(ΣC)²/3`) | Solidly in scope | Trivial | Housekeeping check — confirms our O(1) move-delta is the standard efficient form, not new math |
| 2 | **VNS "shake" fix**: use the 3-cycle move as a single random jump after 2-swap convergence, not an exhaustive second descent neighborhood | Solidly in scope | Low | Directly diagnoses and fixes the earlier 3-cycle regression — Mladenović & Hansen (1997) and a 2025 healthcare-VNS review are explicit that large neighborhoods should be *shaken*, not scanned |
| 3 | **Worst-nurse-first move bias**: prioritize swap candidates touching the currently most-imbalanced nurse(s) | Solidly in scope | Low | Cheap scan-order heuristic, directly targets the cost function; precedent in Bilgin et al. 2012 and 2024 hospital case-study workload-balance papers |
| 4 | **Local/stochastic beam search over rosters** (k parallel candidates, existing swap as successor function) | Solidly in scope | Medium | Explicitly taught technique, untried in this codebase for post-hoc refinement |
| 5 | **GRASP-style randomized construction** (restricted-candidate-list, pick randomly among near-best next choices during Part A's backtracking) | Defensible adjacent extension | Low-medium | Same reasoning that blessed random-restart; only touches construction, no new acceptance criterion |
| 6 | **Early-abort hill-climb** (Burke, Curtois et al. 2011 "progress control"): abort an unpromising post-perturbation climb early, reallocate time to more restart cycles | Solidly in scope | Low | Pure budget-reallocation tuning on existing machinery |
| 7 | Guided Local Search (persistent feature-penalty weighting) | **Likely out of scope** | — | Genuinely new adaptive machinery (modifies the objective itself across restarts) beyond sideways-moves/restarts; noted only as "considered and rejected" |
| 8 | Ejection chains (ORTEC/Burke & Curtois) | **Likely out of scope** | — | LNS-flavored compound-move mechanism, not a simple neighborhood swap |

**Key citations**: Mladenović & Hansen, "Variable Neighborhood Search," EJOR 130(3), 1997; Bilgin, De
Causmaecker, Rossie, Vanden Berghe, "Local search neighbourhoods for a novel nurse rostering model,"
Annals of OR 194(1), 2012; Burke, Curtois, van Draat, van Ommeren, Post, "Progress control in iterated
local search for nurse rostering," JORS 62(2), 2011; Feo & Resende, GRASP, J. Global Optimization, 1995;
2025 VNS healthcare-rostering review, J. Heuristics.

## Part 2: Non-local-search alternatives

| # | Idea | Verdict | Effort | Notes |
|---|---|---|---|---|
| 1 | **Branch-and-bound with a convex per-nurse lower bound** | Solidly in scope | Medium | The objective is convex and separable per nurse — Jensen's-inequality reasoning gives a cheap, valid lower bound. Direct extension of A*/IDA*'s relaxation-based heuristic design (L06). Unique upside: can **prove optimality** on tractable instances |
| 2 | **Constructive beam search** (successors = extend partial roster by one cell; score = cost + lower bound; keep top-k) | Solidly in scope | Medium | Same taught technique as local-search item 4, retargeted to construction; reuses the B&B bound |
| 3 | Greedy least-imbalanced-shift construction heuristic | Defensible adjacent extension, awkward theoretical fit | Low | Inspired by Graham's online load-balancing (`2−1/m` ratio), but that guarantee is for *makespan*, not our *quadratic* objective — useful as a cheap heuristic/scoring function, not a standalone provable-quality contribution |
| 4 | MDP / value-iteration / deterministic-DP framing | Technically valid reduction, **not practically recommended** | — | Real curse-of-dimensionality: state = every nurse's running (M,A,E) counts, blows up combinatorially; no genuine uncertainty/policy to justify MDP terminology here. Worth a one-paragraph theoretical aside only |
| 5 | Cost-based GCC filtering (Régin's `cost-gcc`, min-cost-flow domain pruning) | Real CP literature, **not recommended to implement** | — | Extends our existing GCC/Hall's-theorem hard-constraint pruning, but doesn't plug in cleanly for a *quadratic* (not linear) cost, and full implementation pulls in flow-optimization machinery beyond the course's stated intent. Cite as theoretical grounding for item 1's bound instead |

**Key citations**: Tsang, *Foundations of Constraint Satisfaction*, Ch.10 (CSOPs, branch-and-bound);
Régin, "Cost-Based Arc Consistency for Global Cardinality Constraints," Constraints 7, 2002; Kleinberg &
Tardos, Ch.11 (load balancing, Graham's `2−1/m` bound); Bertsekas / Powell, curse-of-dimensionality in
(A)DP; "Parallel Beam Search for Combinatorial Optimization," 2022.

## Ranked recommendation (both passes combined)

1. **VNS shake fix** (Part 1, #2) — cheapest, highest-confidence, directly fixes a diagnosed prior regression.
2. **Worst-nurse-first bias** (Part 1, #3) — cheap, directly targets the objective.
3. **Branch-and-bound with the convex bound** (Part 2, #1) — highest new-value item; uniquely can prove optimality, extends taught A*/IDA* heuristic-design material.
4. **Constructive beam search** (Part 2, #2) — reuses the B&B bound and successor logic, gives a scalable anytime alternative.
5. **Early-abort hill-climb** (Part 1, #6) — cheap budget tuning.
6. **Local/stochastic beam search over rosters** (Part 1, #4) and **GRASP-style construction** (Part 1, #5) — worth trying if time remains after 1–5.

**Considered and explicitly rejected** (documented here for `report.txt`, not implemented): Guided Local
Search, ejection chains, MDP/value iteration over the full per-nurse-count state space, full cost-based
GCC/min-cost-flow filtering. Each is a real, citable technique — the reasons for setting them aside are
either genuine new machinery beyond the taught local-search/CSP family, or a poor mathematical fit for
this specific quadratic objective, not simply "didn't get to it."
