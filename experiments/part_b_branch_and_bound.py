#!/usr/bin/env python3
"""EXPERIMENTAL variant: branch-and-bound with a convex per-nurse lower
bound (see NOTES_part_b_literature.md, Part 2, item 1), run as a bounded
first pass ahead of the existing local-search pipeline, keeping whichever
result is better.

branch_and_bound() below performs DFS over the SAME (nurse,day)->shift
CSP tree part_a's backtracking search already explores (reusing
part_a.build_initial_state/select_unassigned_variable/order_domain_values/
is_consistent/forward_check/assign/unassign/restore_domains directly --
no hard-constraint logic is duplicated), but continues past the first
complete solution found ("the incumbent"), pruning any branch whose
lower bound on final cost already meets or exceeds the incumbent's cost.

Lower bound, deliberately the SAFE/simple form of the convex bound
described in the literature note (not the tighter "distribute remaining
days evenly" form): for each nurse, 0 if any of their days are still
unassigned (always a valid under-estimate -- with remaining flexibility a
nurse could in principle still end up with cost as low as 0), else their
EXACT final cost (fixed, no longer changeable, once all their days are
assigned). Summed over nurses, this is a valid admissible lower bound on
the cost of ANY completion of the current partial assignment -- it can
never overestimate the true minimum achievable, so pruning on it can only
discard branches that provably cannot beat the incumbent, never the true
optimum. This trades some pruning power (it's not the tightest possible
bound) for a soundness argument that's easy to verify by inspection.

Because pruning only activates once an incumbent exists, and finding the
first complete solution uses exactly the same search as part_a.solve's
deterministic attempt, branch-and-bound reaches its first (feasible, not
yet proven optimal) roster about as fast as plain construction would --
so even a branch-and-bound run that never proves optimality within its
time slice still typically has a usable, often-improved incumbent.

Part B: nurse rostering soft-constraint optimization via local search.

Design (see HANDOFF_experiments_llm.md and
NOTES_correctness_and_approaches.md, Section C, Approach B): construct an
initial valid roster by reusing part_a.solve (which itself includes the
randomized-restart fallback -- see part_a.py's module docstring), then
hill-climb by repeatedly applying the best-improving *cross-nurse
same-day shift swap* -- exchanging two already-working nurses' shift
types on the same day. This move is headcount-preserving by construction
(the day's multiset of shift labels is unchanged), so H4/H7 stay
satisfied automatically; only H1/H2/H3/H5/H6/H8/H9 need a cheap per-nurse
recheck for the two nurses involved (H9 is trivially satisfied since only
already-working, i.e. non-leave, cells are swapped). Uses steepest-descent
with a bounded number of sideways moves to escape plateaus, then spends
any remaining time budget on perturb-and-reclimb restarts (L05:
hill-climbing with sideways moves, random restarts).

Reuses part_a.py directly (Problem, parse_input, solve, shift_load,
write_solution) rather than duplicating any backtracking/CSP logic.

Benchmark summary (full detail in HANDOFF_experiments_llm.md): 28/34 valid
rosters across the suite_002+003+004 checker suites (up from 0/34 -- Part B
was unimplemented before); remaining gaps are one instance Part A itself
doesn't solve (see part_a.py's docstring) and several of the hardest T=600s
(and a couple of borderline T=30s) instances where the fixed
30%-of-budget construction reservation isn't enough --
see the handoff doc's "Known limitations" section.
"""

from __future__ import annotations

import dataclasses
import itertools
import os
import random
import sys
import time
from typing import Optional

try:
    import part_a
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import part_a

Shift = str
Roster = list  # list[list[Shift]], roster[nurse][day]


def nurse_shift_counts(roster: Roster, D: int, nurse: int) -> tuple[int, int, int]:
    """Return (M-count, A-count, E-count) for one nurse; B counts to both M and A."""
    m = a = e = 0
    for day in range(D):
        s = roster[nurse][day]
        if s in ("M", "B"):
            m += 1
        if s in ("A", "B"):
            a += 1
        if s == "E":
            e += 1
    return m, a, e


def nurse_local_cost(m: int, a: int, e: int) -> int:
    """Per-nurse contribution to the spec's cost C, mirroring
    checker/verifier.py's calculate_objective (algebraically identical to
    9*(1/3)*sum((x-mu)^2) for x in {m,a,e})."""
    total = m + a + e
    return 3 * (m * m + a * a + e * e) - total * total


def _apply_count(counts: list[list[int]], nurse: int, shift: Shift, sign: int) -> None:
    if shift in ("M", "B"):
        counts[nurse][0] += sign
    if shift in ("A", "B"):
        counts[nurse][1] += sign
    if shift == "E":
        counts[nurse][2] += sign


def branch_and_bound(
    problem: "part_a.Problem", deadline: float
) -> tuple[Optional[Roster], Optional[int]]:
    """DFS branch-and-bound; see this module's docstring for the full
    design and the soundness argument for the lower bound used. Returns
    (best_roster, best_cost), or (None, None) if no valid roster was
    found before `deadline`. `best_cost` may not be proven optimal if the
    deadline was hit before the whole tree was explored -- callers should
    treat it as "best found," not "proven optimal," unless they also
    confirm the search completed (not attempted here, kept simple: the
    caller only cares about the best cost found either way)."""
    if not part_a.basic_feasibility_checks(problem):
        return None, None

    part_a._RNG = None  # force the deterministic MRV+degree path, never the
    # randomized-restart path -- B&B's own incumbent-tracking is the
    # "keep trying" mechanism here, not part_a's restart loop.

    state = part_a.build_initial_state(problem)
    counts: list[list[int]] = [[0, 0, 0] for _ in range(problem.N)]
    remaining_days = [problem.D for _ in range(problem.N)]
    incumbent: list = [None, None]  # [roster, cost]

    def lower_bound() -> int:
        total = 0
        for nurse in range(problem.N):
            if remaining_days[nurse] > 0:
                continue  # safe under-estimate: contributes >= 0
            m, a, e = counts[nurse]
            total += nurse_local_cost(m, a, e)
        return total

    def recurse() -> None:
        if time.monotonic() >= deadline:
            raise part_a.SearchTimeout

        if incumbent[1] is not None and lower_bound() >= incumbent[1]:
            return  # pruned: this branch cannot beat the incumbent

        if state.unassigned_count == 0:
            if part_a.final_constraints_hold(problem, state):
                cost = sum(nurse_local_cost(*c) for c in counts)
                if incumbent[1] is None or cost < incumbent[1]:
                    incumbent[0] = [row[:] for row in state.roster]
                    incumbent[1] = cost
            return

        variable = part_a.select_unassigned_variable(problem, state)
        if variable is None:
            return
        nurse, day = variable

        for shift in part_a.order_domain_values(problem, state, nurse, day):
            if not part_a.is_consistent(problem, state, nurse, day, shift):
                continue

            part_a.assign(state, nurse, day, shift)
            _apply_count(counts, nurse, shift, 1)
            remaining_days[nurse] -= 1

            changes = part_a.forward_check(problem, state, nurse, day, shift)
            if changes is not None:
                recurse()
                part_a.restore_domains(state, changes)

            remaining_days[nurse] += 1
            _apply_count(counts, nurse, shift, -1)
            part_a.unassign(state, nurse, day, shift)

    try:
        recurse()
    except part_a.SearchTimeout:
        pass

    if incumbent[0] is None:
        return None, None
    return incumbent[0], incumbent[1]


def roster_cost(roster: Roster, problem: "part_a.Problem") -> int:
    return sum(
        nurse_local_cost(*nurse_shift_counts(roster, problem.D, nurse))
        for nurse in range(problem.N)
    )


def nurse_hard_constraints_ok(roster: Roster, problem: "part_a.Problem", nurse: int) -> bool:
    """Mirror checker/verifier.py's per-nurse hard-constraint checks
    (H1's B-eligibility, H2, H3, H5, H6, H8, H9), scoped to one nurse."""
    D = problem.D
    load = 0
    for day in range(D):
        s = roster[nurse][day]
        if s == "B" and nurse >= problem.Ns:
            return False
        if problem.is_on_leave(nurse, day) and s != "R":
            return False
        load += part_a.shift_load(s)
    if load > problem.max_shifts:
        return False
    for day in range(D - 1):
        cur, nxt = roster[nurse][day], roster[nurse][day + 1]
        if cur in ("M", "B") and nxt in ("M", "B"):
            return False
        if cur == "E" and nxt in ("M", "B"):
            return False
        if cur == "B" and nxt not in ("R", "E"):
            return False
    for start in range(D - 5):
        if all(roster[nurse][d] != "R" for d in range(start, start + 6)):
            return False
    return True


def working_nurses_by_day(roster: Roster, problem: "part_a.Problem") -> list[list[int]]:
    by_day: list[list[int]] = [[] for _ in range(problem.D)]
    for nurse in range(problem.N):
        for day in range(problem.D):
            if roster[nurse][day] != "R":
                by_day[day].append(nurse)
    return by_day


def is_legal_swap(roster: Roster, problem: "part_a.Problem", day: int, i: int, j: int) -> bool:
    """Check whether swapping nurse i/j's shift on `day` keeps both nurses
    H1/H2/H3/H5/H6/H8/H9-valid. Mutates and restores `roster` to check."""
    si, sj = roster[i][day], roster[j][day]
    if i == j or si == sj or si == "R" or sj == "R":
        return False
    if (si == "B" and j >= problem.Ns) or (sj == "B" and i >= problem.Ns):
        return False

    roster[i][day], roster[j][day] = sj, si
    ok = nurse_hard_constraints_ok(roster, problem, i) and nurse_hard_constraints_ok(roster, problem, j)
    roster[i][day], roster[j][day] = si, sj
    return ok


def apply_swap(roster: Roster, day: int, i: int, j: int) -> None:
    roster[i][day], roster[j][day] = roster[j][day], roster[i][day]


def swap_cost_delta(
    roster: Roster,
    problem: "part_a.Problem",
    counts: list[tuple[int, int, int]],
    day: int,
    i: int,
    j: int,
) -> Optional[tuple[int, tuple[int, int, int], tuple[int, int, int]]]:
    """If legal, return (cost delta, new counts[i], new counts[j]) for
    swapping nurse i/j's shift on `day`, without mutating `roster`/`counts`.
    Returns None if illegal."""
    if not is_legal_swap(roster, problem, day, i, j):
        return None

    old_cost = nurse_local_cost(*counts[i]) + nurse_local_cost(*counts[j])
    apply_swap(roster, day, i, j)
    new_ci = nurse_shift_counts(roster, problem.D, i)
    new_cj = nurse_shift_counts(roster, problem.D, j)
    apply_swap(roster, day, i, j)  # revert; caller applies if it accepts the move
    new_cost = nurse_local_cost(*new_ci) + nurse_local_cost(*new_cj)
    return new_cost - old_cost, new_ci, new_cj


def hill_climb(
    roster: Roster,
    problem: "part_a.Problem",
    deadline: float,
    max_sideways: int = 20,
) -> tuple[Roster, int]:
    """Steepest-descent hill-climbing with a bounded sideways-move budget,
    over the cross-nurse same-day swap neighborhood (L05: hill-climbing +
    sideways moves)."""
    counts = [nurse_shift_counts(roster, problem.D, n) for n in range(problem.N)]
    cost = sum(nurse_local_cost(*c) for c in counts)
    sideways_used = 0

    while time.monotonic() < deadline:
        by_day = working_nurses_by_day(roster, problem)
        best_delta = 0
        best_move = None

        for day in range(problem.D):
            for i, j in itertools.combinations(by_day[day], 2):
                result = swap_cost_delta(roster, problem, counts, day, i, j)
                if result is None:
                    continue
                delta, new_ci, new_cj = result
                if delta < best_delta or (
                    delta == 0 and best_move is None and sideways_used < max_sideways
                ):
                    best_delta = delta
                    best_move = (day, i, j, new_ci, new_cj)
            if time.monotonic() >= deadline:
                break

        if best_move is None:
            break

        day, i, j, new_ci, new_cj = best_move
        apply_swap(roster, day, i, j)
        counts[i], counts[j] = new_ci, new_cj
        cost += best_delta
        sideways_used = sideways_used + 1 if best_delta == 0 else 0

    return roster, cost


def perturb_roster(
    roster: Roster, problem: "part_a.Problem", rng: random.Random, num_swaps: int
) -> None:
    """Apply a handful of random *legal* (but not necessarily improving)
    swaps in place, to escape a hill-climbing local optimum before the next
    restart (L05: random restarts / random walk)."""
    for _ in range(num_swaps):
        by_day = working_nurses_by_day(roster, problem)
        day_candidates = [d for d, nurses in enumerate(by_day) if len(nurses) >= 2]
        if not day_candidates:
            return
        day = rng.choice(day_candidates)
        nurses = by_day[day]
        for _attempt in range(10):
            i, j = rng.sample(nurses, 2)
            if is_legal_swap(roster, problem, day, i, j):
                apply_swap(roster, day, i, j)
                break


def solve_part_b(problem: "part_a.Problem") -> Optional[Roster]:
    """Find a valid roster minimizing the spec's soft cost, within the
    instance's T budget.

    Tries branch_and_bound() first with a bounded slice of the budget
    (it can prove optimality on tractable instances, and even a
    timed-out slice typically still yields a usable incumbent -- see
    this module's docstring), then runs the existing construction +
    hill-climbing pipeline with whatever time remains, and returns
    whichever of the two results has the lower cost. This can never be
    worse than the plain local-search pipeline alone: if branch-and-bound
    finds nothing, its result is simply ignored.
    """
    deadline = time.monotonic() + max(0.0, problem.time_limit)
    rng = random.Random(0)

    # Small, ABSOLUTE-capped budget (not a fraction of T): a first attempt
    # at 40% of T caused a genuine regression on suite_001/test39 (a
    # 150-case sample validation) -- branch_and_bound() forces
    # part_a._RNG=None (deterministic-only, no randomized-restart escape
    # hatch), so on instances where PLAIN deterministic construction is
    # itself borderline-slow, a large B&B slice both (a) can fail to find
    # even a first incumbent (inheriting the same thrashing weakness
    # random-restart was built to fix) and (b) eats into the time the
    # guaranteed-safe construction+hill-climb fallback below needs, which
    # can turn a case baseline solves into one this variant doesn't. A
    # small cap keeps the fallback's effective budget close to baseline's
    # regardless of how B&B's own search goes, while still giving B&B
    # real room to find quick optimality proofs on the (usually smaller/
    # easier) instances that construct fast, which is where its measured
    # 24->29 MATCHED improvement on that same sample actually came from.
    bnb_budget = max(0.1, min(2.0, problem.time_limit * 0.15, deadline - time.monotonic()))
    bnb_roster, bnb_cost = branch_and_bound(problem, time.monotonic() + bnb_budget)

    def better_of(roster: Optional[Roster], cost: Optional[int]) -> Optional[Roster]:
        """Return whichever of (roster, cost) and (bnb_roster, bnb_cost)
        is better, treating a missing side as infinitely worse."""
        if roster is None:
            return bnb_roster
        if bnb_roster is None or bnb_cost >= cost:
            return roster
        return bnb_roster

    if time.monotonic() >= deadline:
        return bnb_roster

    # Reserve most of the remaining budget for optimization; construction
    # typically only needs a fraction of T for feasible instances (see
    # NOTES_correctness_and_approaches.md for cases where this isn't true).
    construction_budget = max(0.1, min(problem.time_limit * 0.3, deadline - time.monotonic()))
    construction_problem = dataclasses.replace(problem, time_limit=construction_budget)
    roster = part_a.solve(construction_problem)

    if roster is None:
        # Construction alone needed more than its reserved share -- retry
        # with whatever time remains, and skip optimization entirely if it
        # succeeds only right at the deadline.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return bnb_roster
        fallback_problem = dataclasses.replace(problem, time_limit=remaining)
        roster = part_a.solve(fallback_problem)
        if roster is None:
            return bnb_roster
        return better_of(roster, roster_cost(roster, problem))

    roster = [row[:] for row in roster]
    roster, cost = hill_climb(roster, problem, deadline)
    best_roster, best_cost = roster, cost

    while time.monotonic() < deadline - 0.05:
        perturbed = [row[:] for row in best_roster]
        perturb_roster(perturbed, problem, rng, num_swaps=max(3, problem.D // 5))
        perturbed, pcost = hill_climb(perturbed, problem, deadline)
        if pcost < best_cost:
            best_roster, best_cost = perturbed, pcost

    return better_of(best_roster, best_cost)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python part_b.py <input_csv_path> <output_json_path>")

    sys.setrecursionlimit(5000)
    problem = part_a.parse_input(sys.argv[1])
    roster = solve_part_b(problem)
    part_a.write_solution(sys.argv[2], roster)


if __name__ == "__main__":
    main()
