#!/usr/bin/env python3
"""EXPERIMENTAL Part B solver v2: local search on top of the improved
(randomized-restart) Part A construction.

Identical to part_b_hillclimb.py except it constructs the initial roster
via part_a_random_restart.solve instead of plain part_a.solve. The original
part_b_hillclimb.py's failures (suite_002/test1, suite_002/test14,
suite_004/test1, and 7/9 of suite_003) were all traced directly to Part
A's construction phase timing out on the same hard instances found in
NOTES_experiment_results.md. part_a_random_restart.py (pure randomized
restart, WITHOUT the hybrid-LCV addition -- see
NOTES_experiment_results.md for why the LCV combination was dropped: it
introduced 4 new suite_001 regressions despite fixing one extra known-hard
case) achieves 993/1000 on suite_001 with zero regressions, so this
variant tests whether that improvement closes Part B's inherited failures
too, without inheriting hybrid-LCV's instability.

EXPERIMENTAL Part B solver: local search over valid Part-A rosters.

Design (see NOTES_correctness_and_approaches.md, Section C, Approach B --
the recommended primary approach): construct an initial valid roster by
reusing part_a.solve, then hill-climb by repeatedly applying the
best-improving *cross-nurse same-day shift swap* -- exchanging two already-
working nurses' shift types on the same day. This move is headcount-
preserving by construction (the day's multiset of shift labels is
unchanged), so H4/H7 stay satisfied automatically; only H1/H2/H3/H5/H6/H8/H9
need a cheap per-nurse recheck for the two nurses involved (H9 is trivially
satisfied since only already-working, i.e. non-leave, cells are swapped).
Uses steepest-descent with a bounded number of sideways moves to escape
plateaus, then spends any remaining time budget on perturb-and-reclimb
restarts (L05: hill-climbing with sideways moves, random restarts).

Reuses part_a.py directly (Problem, parse_input, solve, shift_load,
write_solution) rather than duplicating any backtracking/CSP logic.
"""

from __future__ import annotations

import dataclasses
import os
import random
import sys
import time
from typing import Optional

try:
    import part_a_random_restart as part_a
except ImportError:
    # When this file is copied to repo_root/part_b.py for benchmarking
    # (see scripts/bench_experiment.sh), __file__'s own directory is the
    # repo root, not experiments/ -- so also try repo_root/experiments
    # (where part_a_random_restart.py itself is left untouched by the copy).
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (here, os.path.join(here, "experiments")):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
    import part_a_random_restart as part_a

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
            nurses = by_day[day]
            n = len(nurses)
            for a_idx in range(n):
                i = nurses[a_idx]
                for b_idx in range(a_idx + 1, n):
                    j = nurses[b_idx]
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
    instance's T budget."""
    deadline = time.monotonic() + max(0.0, problem.time_limit)
    rng = random.Random(0)

    # Reserve most of the budget for optimization; construction typically
    # only needs a fraction of T for feasible instances (see
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
            return None
        fallback_problem = dataclasses.replace(problem, time_limit=remaining)
        roster = part_a.solve(fallback_problem)
        return roster

    roster = [row[:] for row in roster]
    roster, cost = hill_climb(roster, problem, deadline)
    best_roster, best_cost = roster, cost

    while time.monotonic() < deadline - 0.05:
        perturbed = [row[:] for row in best_roster]
        perturb_roster(perturbed, problem, rng, num_swaps=max(3, problem.D // 5))
        perturbed, pcost = hill_climb(perturbed, problem, deadline)
        if pcost < best_cost:
            best_roster, best_cost = perturbed, pcost

    return best_roster


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python part_b.py <input_csv_path> <output_json_path>")

    sys.setrecursionlimit(5000)
    problem = part_a.parse_input(sys.argv[1])
    roster = solve_part_b(problem)
    part_a.write_solution(sys.argv[2], roster)


if __name__ == "__main__":
    main()
