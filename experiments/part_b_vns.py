#!/usr/bin/env python3
"""EXPERIMENTAL variant: Variable Neighborhood Descent (VND, the
deterministic core of VNS -- Mladenovic & Hansen 1997; see
NOTES_literature_review.md) on top of part_b.py's hill-climbing design.

Adds a second, larger neighborhood -- a 3-nurse cyclic shift exchange on
the same day (see apply_cycle/is_legal_cycle/cycle_cost_delta/
best_cycle_move below), still headcount-preserving by the same reasoning
as the pairwise swap. hill_climb() now escalates to this larger
neighborhood only once the pairwise-swap neighborhood is exhausted
(VND's standard "escalate on failure to improve, drop back to the
smallest neighborhood on success" policy), instead of relying solely on
perturb-and-restart to escape a pairwise-swap local optimum.

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
import os
import random
import sys
import time
from typing import Optional

try:
    import part_a
except ImportError:
    # When this file is copied to repo_root/part_b.py for benchmarking
    # (see scripts/bench_experiment.sh), part_a is right there; when run
    # directly from experiments/, part_a.py is one directory up.
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


def apply_cycle(roster: Roster, day: int, i: int, j: int, k: int) -> None:
    """Rotate three nurses' shifts on `day`: i<-(old k), j<-(old i),
    k<-(old j). Still headcount-preserving -- same multiset of shift
    labels on that day, just relabeled among three nurses instead of two."""
    si, sj, sk = roster[i][day], roster[j][day], roster[k][day]
    roster[i][day], roster[j][day], roster[k][day] = sk, si, sj


def is_legal_cycle(roster: Roster, problem: "part_a.Problem", day: int, i: int, j: int, k: int) -> bool:
    if len({i, j, k}) != 3:
        return False
    si, sj, sk = roster[i][day], roster[j][day], roster[k][day]
    if si == "R" or sj == "R" or sk == "R":
        return False
    if si == sj == sk:
        return False

    apply_cycle(roster, day, i, j, k)
    ok = (
        nurse_hard_constraints_ok(roster, problem, i)
        and nurse_hard_constraints_ok(roster, problem, j)
        and nurse_hard_constraints_ok(roster, problem, k)
    )
    roster[i][day], roster[j][day], roster[k][day] = si, sj, sk  # direct revert
    return ok


def cycle_cost_delta(
    roster: Roster,
    problem: "part_a.Problem",
    counts: list[tuple[int, int, int]],
    day: int,
    i: int,
    j: int,
    k: int,
) -> Optional[tuple[int, tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]]:
    """Same idea as swap_cost_delta, for the 3-nurse cyclic-exchange move."""
    si, sj, sk = roster[i][day], roster[j][day], roster[k][day]
    if not is_legal_cycle(roster, problem, day, i, j, k):
        return None

    old_cost = (
        nurse_local_cost(*counts[i]) + nurse_local_cost(*counts[j]) + nurse_local_cost(*counts[k])
    )
    apply_cycle(roster, day, i, j, k)
    new_ci = nurse_shift_counts(roster, problem.D, i)
    new_cj = nurse_shift_counts(roster, problem.D, j)
    new_ck = nurse_shift_counts(roster, problem.D, k)
    roster[i][day], roster[j][day], roster[k][day] = si, sj, sk  # direct revert
    new_cost = nurse_local_cost(*new_ci) + nurse_local_cost(*new_cj) + nurse_local_cost(*new_ck)
    return new_cost - old_cost, new_ci, new_cj, new_ck


def best_swap_move(
    roster: Roster,
    problem: "part_a.Problem",
    counts: list[tuple[int, int, int]],
    by_day: list[list[int]],
    deadline: float,
    sideways_used: int,
    max_sideways: int,
):
    """Scan the pairwise-swap neighborhood (N1) for the best move."""
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
    return best_delta, best_move


def best_cycle_move(
    roster: Roster,
    problem: "part_a.Problem",
    counts: list[tuple[int, int, int]],
    by_day: list[list[int]],
    deadline: float,
):
    """Scan the 3-nurse cyclic-exchange neighborhood (N2, larger than N1)
    for an improving move. Only tried once N1 is exhausted (VND
    convention: escalate to a larger neighborhood on failure to improve,
    drop back to the smallest on success)."""
    best_delta = 0
    best_move = None
    for day in range(problem.D):
        nurses = by_day[day]
        n = len(nurses)
        for a_idx in range(n):
            i = nurses[a_idx]
            for b_idx in range(a_idx + 1, n):
                j = nurses[b_idx]
                for c_idx in range(b_idx + 1, n):
                    k = nurses[c_idx]
                    result = cycle_cost_delta(roster, problem, counts, day, i, j, k)
                    if result is None:
                        continue
                    delta, new_ci, new_cj, new_ck = result
                    if delta < best_delta:
                        best_delta = delta
                        best_move = (day, i, j, k, new_ci, new_cj, new_ck)
        if time.monotonic() >= deadline:
            break
    return best_delta, best_move


def hill_climb(
    roster: Roster,
    problem: "part_a.Problem",
    deadline: float,
    max_sideways: int = 20,
) -> tuple[Roster, int]:
    """Variable Neighborhood Descent (VND, the deterministic core of VNS --
    Mladenovic & Hansen 1997; see NOTES_literature_review.md): hill-climb
    the pairwise-swap neighborhood (N1) with sideways moves to a local
    optimum; when N1 has no improving/sideways move left, escalate to the
    larger 3-nurse cyclic-exchange neighborhood (N2) and, if it finds an
    improving move, apply it and drop back to N1 (a move in N2 can unlock
    further N1 improvements). Only when NEITHER neighborhood has an
    improving move are we at a local optimum w.r.t. both, and we stop."""
    counts = [nurse_shift_counts(roster, problem.D, n) for n in range(problem.N)]
    cost = sum(nurse_local_cost(*c) for c in counts)
    sideways_used = 0

    while time.monotonic() < deadline:
        by_day = working_nurses_by_day(roster, problem)

        delta, move = best_swap_move(
            roster, problem, counts, by_day, deadline, sideways_used, max_sideways
        )
        if move is not None:
            day, i, j, new_ci, new_cj = move
            apply_swap(roster, day, i, j)
            counts[i], counts[j] = new_ci, new_cj
            cost += delta
            sideways_used = sideways_used + 1 if delta == 0 else 0
            continue

        if time.monotonic() >= deadline:
            break

        cycle_delta, cycle_move = best_cycle_move(roster, problem, counts, by_day, deadline)
        if cycle_move is not None:
            day, i, j, k, new_ci, new_cj, new_ck = cycle_move
            apply_cycle(roster, day, i, j, k)
            counts[i], counts[j], counts[k] = new_ci, new_cj, new_ck
            cost += cycle_delta
            sideways_used = 0
            continue  # drop back to N1 (VND convention)

        break  # local optimum w.r.t. both neighborhoods

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
