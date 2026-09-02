# Literature Review — NRP Modeling & Advanced Search Techniques

Two research passes: (1) how the Nurse Rostering Problem is modeled in the academic literature, and how
our CSP formulation compares; (2) search/CSP techniques beyond plain backtracking+MRV+LCV+FC and beyond
simple random-restart hill-climbing, each rated against the course's "search/CSP-adjacent only"
constraint (confirmed syllabus: L04 backtracking/MRV/degree/LCV/FC/AC-3/k-consistency, L05
hill-climbing/beam search/random restarts/random walk/sideways moves, L06 A*/greedy/IDA*).

## Part 1: Modeling — is our CSP formulation standard?

**Yes.** The current `(nurse, day) → shift symbol` multi-valued-domain CSP is called the **"nurse-based"
model** in the literature and is a well-established, standard formulation — not an ad hoc
simplification. Key reference: Abdennadher & Schlenker, "A Nurse Rostering System Using Constraint
Programming and Redundant Modeling" (IEEE Intelligent Systems 15(2), 2000), a real hospital deployment
(Kliniken Rhön, Germany) using exactly this style of model with CLP(FD)/Prolog backtracking.

### Four formulations found in the literature

| Formulation | Variables | Solved by | CSP/search-adjacent? |
|---|---|---|---|
| **Nurse-based (ours)** | (nurse,day)→shift symbol | backtracking + constraint propagation | Yes — this is our model |
| **Shift-based dual + channeling** | (shift,slot)→nurse, linked to the nurse-based view via channeling constraints | CP with dual-model propagation | Yes — same paradigm, stronger propagation |
| **Binary assignment** | (nurse,day,shift)→0/1 | MILP branch-and-cut, or SAT/SMT clauses, or CP-SAT | No — LP relaxation/branch-and-bound or SAT solving, different math |
| **Pattern/column generation** | nurse→whole-horizon work pattern (0/1 per pattern) | branch-and-price (LP master + CP/DP pricing subproblem) | No (master problem) — LP/ILP machinery, though the *pricing* subproblem is often solved by CP/DP over per-nurse sequence constraints, which is CSP-adjacent |

**Why this matters for the assignment**: the binary-assignment and pattern/column-generation
formulations are exactly the kind of "fundamentally different mathematical underpinnings" (LP
relaxation, branch-and-price) the course explicitly excludes — confirming our nurse-based CSP choice is
not just standard but also the *correct* choice given the course's constraints, not merely the
convenient one.

### Comparison to the standard benchmark (INRC)

The International Nurse Rostering Competition (INRC-I: Haspeslagh et al., *Annals of OR* 2014; INRC-II:
Ceschia et al., arXiv:1501.04177) constraint taxonomy maps cleanly onto our H1–H9:

- Our **exact daily headcount** ≈ INRC's min/max staffing-per-shift, but *stricter* (hard equality vs.
  INRC's typical soft under/over-staffing penalty) — this pushes our problem structurally closer to a
  **classic set-partitioning/exact-cover** flavor on the coverage axis, which is exactly why the
  bipartite-matching pruning (below) applies.
- **No-consecutive-morning** / **max-consecutive-workdays** ≈ INRC's "illegal shift-type successions" /
  "max consecutive working days" — standard NRP constraint families (De Causmaecker & Vanden Berghe's
  taxonomy, *J. Scheduling* 2011, calls these "sequence constraints").
- **Leave days** ≈ INRC's fixed day-off pre-assignments.
- **Evenness-of-distribution soft cost** ≈ a "counter constraint" (De Causmaecker & Vanden Berghe's
  term) — INRC's version is typically a *linear* (L1) deviation penalty; our spec's *quadratic*
  deviation is a deliberate, less common choice (linear penalties are more typical in CP objectives for
  solver-friendliness; quadratic is more an ILP/QP convention) — worth noting in `report.txt` as a
  point where this assignment's formulation deviates slightly from the INRC norm.
- The **surgical double-shift (B)** value is *not* a standard INRC/benchmark shift type — most published
  models keep shifts atomic and define long/double shifts as their own shift type with explicit
  start/end coverage. Packing it into one domain symbol that covers two time-slots is a legitimate,
  hospital-specific extension in the spirit of case-study papers (e.g. Bard & Purnomo), just not a named
  standard construct.

### The Hall's-theorem connection — a real, citable result

Our empirically-discovered leave-aware bipartite-matching infeasibility pruning
(`experiments/part_a_matching_prune.py`) turns out to be a manual instance of what constraint solvers
formalize as the **global cardinality constraint (GCC) propagator**: J.-C. Régin, "Generalized Arc
Consistency for Global Cardinality Constraint," AAAI 1996 — a flow/Hall-deficiency-based filtering
algorithm for exactly this "assign values such that each takes a specific count" structure. This is the
standard CP-native way to encode "exact daily headcount per shift" with strong propagation, and is the
most valuable specific literature pointer found: it gives our ad hoc pruning heuristic a name, a proper
algorithm, and a citation. See Section 3 below (`part_a_gcc_filter.py`) for the during-search
formalization attempt.

Also directly relevant: the INRC-II winning solvers used **network-flow-based ILP formulations**
(Rönnberg & Larsson) — the flow/max-matching generalization of the same bipartite structure — confirming
this connection is well-established in the OR literature, not a coincidence.

### Other useful citations for `report.txt`

- Burke, De Causmaecker, Vanden Berghe, Van Landeghem, "The State of the Art of Nurse Rostering," *J.
  Scheduling* 7(6), 2004 — the standard survey; explicitly discusses CP vs. IP vs. metaheuristic
  paradigms as complementary, noting CP's strength on hard-constraint-dense, tightly-coupled instances
  (matches our problem's profile: many interacting per-day and per-nurse constraints).
- He & Qu (Nottingham), "A Constraint Programming based Column Generation Approach to Nurse Rostering
  Problems" — uses CP specifically for the *pricing subproblem* (a single nurse's feasible pattern,
  i.e. exactly our per-nurse sequence constraints), while ILP handles cross-nurse coverage — a good,
  citable justification for why CP/backtracking is the *right* tool for our specific constraint
  sub-structure even though industrial solvers hybridize with ILP for scale.

## Part 2: Search techniques beyond what's implemented — scope verdicts

| Technique | Verdict | Why |
|---|---|---|
| **Maintaining Arc Consistency (MAC)** | **Solidly in scope** | AC-3 (taught) run during backtracking (taught) — AIMA Ch.6's own natural next step after forward checking |
| **Conflict-directed backjumping (CBJ)** | **Solidly in scope** | Named AIMA Ch.6 extension of backtracking; smarter failure-driven control, same tree-search skeleton |
| **dom/wdeg (weighted-degree ordering)** | Strong defensible extension | Adaptive generalization of MRV + degree heuristic (both taught); Boussemart et al., ECAI 2004; default VOH in the Choco CP solver |
| **Luby/geometric restart scheduling** | Strong defensible extension | Same random-restart mechanism already implemented; proven-optimal cutoff policy (Luby, Sinclair, Zuckerman 1993) for the heavy-tailed runtime distributions Gomes/Selman/Kautz (1998) showed are exactly the profile of randomized backtracking on structured CSPs |
| **VNS/ILS-style structured perturbation** | Strong defensible extension | Directly builds on random-restart hill-climbing + neighborhood concepts (taught); no new acceptance-criterion machinery unlike simulated annealing |
| Large Neighborhood Search (LNS) | Flagged out of scope | Named metaheuristic outside the taught list; "recreate" step typically embeds a full CP/backtracking solve, making it a hybrid that's hard to defend as a pure extension |
| Learned/ML portfolio selection (SATzilla-style) | Flagged out of scope | Pulls in regression/ML machinery, not part of the course |
| Simple portfolio (race taught algorithms, no learning) | Solidly in scope | Just a wrapper around already-implemented techniques |

Full derivations, mechanism descriptions, and citations for each row are in the research transcript;
summarized findings and the 5 in-scope/defensible techniques were prototyped as `experiments/` variants
— see `NOTES_literature_experiments.md` for benchmark results.

**Key theoretical citations** (for `report.txt`):
- Prosser, "Hybrid Algorithms for the Constraint Satisfaction Problem" (1993) — CBJ.
- Boussemart, Hemery, Lecoutre, Sais, "Boosting Systematic Search by Weighting Constraints," ECAI 2004 —
  dom/wdeg.
- Gomes, Selman, Crato, Kautz, "Heavy-Tailed Distributions in Combinatorial Search," AAAI 1998; Luby,
  Sinclair, Zuckerman, "Optimal Speedup of Las Vegas Algorithms," IPL 1993 — restart theory, directly
  explains *why* our empirically-found `test25` thrashing pattern (heavy-tailed, resolved by a lucky
  restart) is a known, named phenomenon, not a one-off quirk.
- Mladenović & Hansen, "Variable Neighborhood Search," Computers & Ops. Research 1997 — VNS.
- Russell & Norvig, AIMA Ch. 6 — the textbook framing tying MAC and CBJ directly to the taught
  backtracking material.
