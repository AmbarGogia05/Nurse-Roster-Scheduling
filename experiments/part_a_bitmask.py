#!/usr/bin/env python3
"""EXPERIMENTAL variant: bitmask domain representation. Per-cell domains
(`set[Shift]`, e.g. {"M","A","B"}) are replaced with 5-bit integers (see
M_BIT/A_BIT/E_BIT/R_BIT/B_BIT and BIT_OF/SHIFT_OF/domain_bits() near the
top of this file). Domain add/remove/membership/popcount become bitwise
ops and int.bit_count() (Python 3.10) instead of Python set method calls,
which carry real per-call overhead (hashing, allocation, dispatch) that
cProfile showed as roughly half of total tottime on a sustained search.
The four per-day candidate sets (morning/afternoon/evening/surgery
candidates) are deliberately left as regular sets in this experiment --
only domains were converted, to keep the change bounded and easier to
verify; converting the candidate sets too is a natural follow-up. See
NOTES_python_perf_experiments.md for the timing comparison.

Part A: nurse rostering as a constraint satisfaction problem.

The intended CSP model is:

    variable:       (nurse, day)
    value/domain:   one of M, A, E, R, B
    assignment:     roster[nurse][day]

Solved via CSP backtracking search: MRV variable ordering (O(1) via
domain-size buckets), a heuristic value-ordering scorer, and incremental
forward checking that enforces H2/H3/H4/H5/H6/H7/H8 proactively.

Three additional techniques on top of that base search, all validated via
the Dockerized checker against checker/test-cases (see
HANDOFF_experiments_llm.md and NOTES_competitive_optimization.md for the
full benchmark numbers and derivations):

  1. Randomized-restart fallback (select_unassigned_variable,
     order_domain_values, solve). The deterministic heuristic-guided first
     attempt is unchanged from the original solver, so already-fast
     instances are unaffected. If it times out without a conclusion
     (SearchTimeout, not a definite True/False), the search falls back to
     short time-sliced restarts with UNIFORMLY RANDOM value ordering
     (deliberately ignoring the heuristic scorer -- empirically, the
     heuristic was found to actively mislead search on some instances; see
     the handoff doc for the concrete case study). A restart's backtrack()
     completing without hitting its own slice deadline is still a valid
     proof of infeasibility regardless of tie-break order, since
     forward-checking pruning never removes a genuine solution -- so this
     can only help performance, never soundness.
  2. Batched candidate-set updates (remove_values, restore_domains).
     update_coverage_candidates is called once per cell actually touched
     rather than once per individual domain value removed/restored, since
     it only depends on the final domain state. Pure speed, no behavioral
     change.
  3. A tighter, leave-aware necessary-infeasibility bound
     (basic_feasibility_checks). Replaces the naive N*K global capacity
     bound with a per-nurse cap of min(K, per_day_cap * (D - that nurse's
     leave-day count)), where per_day_cap is 2 for surgical nurses (a B
     shift consumes 2 load-units in one day) and 1 for general nurses.
     Strictly tighter than, never looser than, the original bound, so it
     can only detect more true-infeasible instances faster, never produce
     a false positive.

Benchmark summary (full detail in HANDOFF_experiments_llm.md): 1017/1024
PASS (99.3%) across the combined suite_001 (1000 cases) + suite_002 (24
cases) checker suites, vs. 953/1024 (93.1%) for the prior implementation,
with zero regressions (every remaining failure was already failing before)
and 43% less total checker wall time.
"""

from __future__ import annotations

import csv
import json
import random
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

# Module-level RNG, None in deterministic mode (matches the original
# real part_a.py exactly), set to a seeded Random() during randomized
# restart attempts. Module-level rather than threaded through every call
# to keep this experiment's diff against part_a.py minimal and localized.
_RNG: Optional[random.Random] = None


Shift = str
Variable = tuple[int, int]
DomainChange = tuple[int, int, Shift]
ValueScorer = Callable[["Problem", "SearchState", int, int, Shift], float]

# Bitmask domain representation: a cell's domain is a 5-bit int instead of
# a set[Shift] (see NOTES_python_perf_experiments.md). Bit membership,
# union, and popcount become bitwise ops / int.bit_count() (Python 3.10)
# instead of set method calls, avoiding Python set object overhead
# (hashing, allocation, per-call dispatch) on the hottest path -- cProfile
# showed set operations as ~half of total tottime on a sustained search.
M_BIT, A_BIT, E_BIT, R_BIT, B_BIT = 1, 2, 4, 8, 16
BIT_OF: dict[Shift, int] = {"M": M_BIT, "A": A_BIT, "E": E_BIT, "R": R_BIT, "B": B_BIT}
SHIFT_OF: dict[int, Shift] = {v: k for k, v in BIT_OF.items()}
MB = M_BIT | B_BIT
AB = A_BIT | B_BIT
MBE = M_BIT | B_BIT | E_BIT
MAB = M_BIT | A_BIT | B_BIT
MAEB = M_BIT | A_BIT | E_BIT | B_BIT
MABR = M_BIT | A_BIT | B_BIT | R_BIT
ME = M_BIT | E_BIT
MER = M_BIT | E_BIT | R_BIT
AER = A_BIT | E_BIT | R_BIT
MAER = M_BIT | A_BIT | E_BIT | R_BIT
SURGICAL_DOMAIN = M_BIT | A_BIT | E_BIT | R_BIT | B_BIT
NON_SURGICAL_DOMAIN = M_BIT | A_BIT | E_BIT | R_BIT
SHIFT_ORDER: tuple[Shift, ...] = ("M", "A", "E", "R", "B")


def domain_bits(mask: int) -> "list[Shift]":
    """Iterate the shift values present in a bitmask domain, in
    SHIFT_ORDER, via bit-scanning instead of set iteration."""
    return [shift for shift in SHIFT_ORDER if mask & BIT_OF[shift]]


@dataclass(frozen=True)
class Problem:
    """Immutable input instance."""

    N: int
    D: int
    Ns: int
    Ng: int
    morning_required: int
    afternoon_required: int
    evening_required: int
    time_limit: float
    day_types: str
    max_shifts: int
    leaves: str

    def is_surgical_nurse(self, nurse: int) -> bool:
        return nurse < self.Ns

    def is_surgical_day(self, day: int) -> bool:
        return self.day_types[day] == "S"

    def is_on_leave(self, nurse: int, day: int) -> bool:
        return self.leaves[nurse * self.D + day] == "L"


@dataclass
class SearchState:
    """Mutable information maintained during backtracking."""

    roster: list[list[Optional[Shift]]]
    domains: list[list[int]]  # bitmask domains, see M_BIT/A_BIT/.../BIT_OF above
    domain_buckets: list[set[Variable]]
    morning_candidates: list[set[int]]
    afternoon_candidates: list[set[int]]
    evening_candidates: list[set[int]]
    surgery_candidates: list[set[int]]

    # Current coverage contributed by assigned cells on each day.
    morning_coverage: list[int]
    afternoon_coverage: list[int]
    evening_coverage: list[int]
    surgery_coverage: list[int]
    unassigned_on_day: list[int]

    # H8 counts shift slots: B contributes two, all other work shifts one.
    nurse_shift_load: list[int]
    unassigned_count: int


class SearchTimeout(Exception):
    """Raised internally when the instance time budget is exhausted."""


def parse_input(input_csv: str) -> Problem:
    """Read the one-row assignment CSV."""
    with open(input_csv, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)

    required = {"N", "D", "N_s", "N_g", "m", "a", "e", "T", "days", "K", "leaves"}
    if reader.fieldnames is None or set(reader.fieldnames) != required:
        raise ValueError("input CSV has unexpected columns")
    if len(rows) != 1:
        raise ValueError("input CSV must contain exactly one data row")

    row = rows[0]
    problem = Problem(
        N=int(row["N"]),
        D=int(row["D"]),
        Ns=int(row["N_s"]),
        Ng=int(row["N_g"]),
        morning_required=int(row["m"]),
        afternoon_required=int(row["a"]),
        evening_required=int(row["e"]),
        time_limit=float(row["T"]),
        day_types=row["days"],
        max_shifts=int(row["K"]),
        leaves=row["leaves"],
    )
    validate_problem(problem)
    return problem


def validate_problem(problem: Problem) -> None:
    """Reject malformed instances before starting search."""
    if (
        min(
            problem.N,
            problem.D,
            problem.Ns,
            problem.Ng,
            problem.morning_required,
            problem.afternoon_required,
            problem.evening_required,
            problem.max_shifts,
        )
        < 0
    ):
        raise ValueError("numeric instance values must be non-negative")
    if problem.Ns + problem.Ng != problem.N:
        raise ValueError("N_s + N_g must equal N")
    if len(problem.day_types) != problem.D or set(problem.day_types) - {"G", "S"}:
        raise ValueError("days must be a length-D string over G and S")
    if len(problem.leaves) != problem.N * problem.D:
        raise ValueError("leaves must contain exactly N*D characters")
    if set(problem.leaves) - {"L", "W"}:
        raise ValueError("leaves must contain only L and W")


def initial_domain(problem: Problem, nurse: int, day: int) -> int:
    """Return the static domain (bitmask) before search-dependent pruning.

    Leave cells are forced to R. B is available only to surgical nurses on
    surgical days; the supplied verifier rejects B on general days.
    """
    if problem.is_on_leave(nurse, day):
        return R_BIT
    if problem.is_surgical_nurse(nurse) and problem.is_surgical_day(day):
        return SURGICAL_DOMAIN
    return NON_SURGICAL_DOMAIN


def build_initial_state(problem: Problem) -> SearchState:
    """Create an empty roster and its initial domains/counters."""
    domains = [
        [initial_domain(problem, nurse, day) for day in range(problem.D)]
        for nurse in range(problem.N)
    ]
    domain_buckets: list[set[Variable]] = [set() for _ in range(6)]
    morning_candidates = [set() for _ in range(problem.D)]
    afternoon_candidates = [set() for _ in range(problem.D)]
    evening_candidates = [set() for _ in range(problem.D)]
    surgery_candidates = [set() for _ in range(problem.D)]

    for nurse in range(problem.N):
        for day in range(problem.D):
            domain_buckets[domains[nurse][day].bit_count()].add((nurse, day))
            if domains[nurse][day] & MB:
                morning_candidates[day].add(nurse)
            if domains[nurse][day] & AB:
                afternoon_candidates[day].add(nurse)
            if domains[nurse][day] & E_BIT:
                evening_candidates[day].add(nurse)
            if domains[nurse][day] & B_BIT:
                surgery_candidates[day].add(nurse)

    return SearchState(
        roster=[[None for _ in range(problem.D)] for _ in range(problem.N)],
        domains=domains,
        domain_buckets=domain_buckets,
        morning_candidates=morning_candidates,
        afternoon_candidates=afternoon_candidates,
        evening_candidates=evening_candidates,
        surgery_candidates=surgery_candidates,
        morning_coverage=[0] * problem.D,
        afternoon_coverage=[0] * problem.D,
        evening_coverage=[0] * problem.D,
        surgery_coverage=[0] * problem.D,
        unassigned_on_day=[problem.N] * problem.D,
        nurse_shift_load=[0] * problem.N,
        unassigned_count=problem.N * problem.D,
    )


def shift_load(shift: Shift) -> int:
    """Return the number of H8 shift slots consumed by a value."""
    if shift == "B":
        return 2
    if shift == "R":
        return 0
    return 1


def update_coverage_candidates(
    state: SearchState, nurse: int, day: int
) -> None:
    """Synchronize one cell with the three daily coverage-candidate sets."""
    if state.roster[nurse][day] is not None:
        state.morning_candidates[day].discard(nurse)
        state.afternoon_candidates[day].discard(nurse)
        state.evening_candidates[day].discard(nurse)
        state.surgery_candidates[day].discard(nurse)
        return

    domain = state.domains[nurse][day]

    if domain & MB:
        state.morning_candidates[day].add(nurse)
    else:
        state.morning_candidates[day].discard(nurse)

    if domain & AB:
        state.afternoon_candidates[day].add(nurse)
    else:
        state.afternoon_candidates[day].discard(nurse)

    if domain & E_BIT:
        state.evening_candidates[day].add(nurse)
    else:
        state.evening_candidates[day].discard(nurse)

    if domain & B_BIT:
        state.surgery_candidates[day].add(nurse)
    else:
        state.surgery_candidates[day].discard(nurse)


def basic_feasibility_checks(p: Problem) -> bool:
    """Leave-aware global capacity bound (derivation and a validated
    experiments/part_a_matching_prune.py for the full derivation and a
    validated counter-example). Strictly tighter than, never looser than,
    the original N*K bound."""
    leaves_count = [0] * p.D
    surgical_leaves_count = [0] * p.D
    nurse_leave_count = [0] * p.N
    for i in range(p.N * p.D):
        if p.leaves[i] == "L":
            nurse, day = divmod(i, p.D)
            leaves_count[day] += 1
            nurse_leave_count[nurse] += 1
            if nurse < p.Ns:
                surgical_leaves_count[day] += 1

    daily_requirement = p.morning_required + p.afternoon_required + p.evening_required
    for day in range(p.D):
        available_nurses = p.N - leaves_count[day]
        if p.is_surgical_day(day):
            available_surgical_nurses = p.Ns - surgical_leaves_count[day]
            possible_b_shifts = min(
                p.morning_required,
                p.afternoon_required,
                available_surgical_nurses,
            )
            nurses_required = daily_requirement - possible_b_shifts
        else:
            nurses_required = daily_requirement

        if available_nurses < nurses_required:
            return False

    if p.day_types.count("S") > 0 and (
        p.Ns == 0 or p.morning_required == 0 or p.afternoon_required == 0
    ):
        return False

    total_capacity = 0
    for nurse in range(p.N):
        available_days = p.D - nurse_leave_count[nurse]
        per_day_cap = 2 if p.is_surgical_nurse(nurse) else 1
        total_capacity += min(p.max_shifts, per_day_cap * available_days)
    if total_capacity < daily_requirement * p.D:
        return False
    return True


def select_unassigned_variable(
    problem: Problem, state: SearchState
) -> Optional[Variable]:
    """Choose an unassigned cell using minimum remaining values.

    When _RNG is set (randomized-restart mode), break MRV
    ties randomly instead of by arbitrary set-iteration order, so repeated
    restarts explore genuinely different regions of the search tree.
    """
    for bucket in state.domain_buckets:
        if bucket:
            if _RNG is not None and len(bucket) > 1:
                return _RNG.choice(list(bucket))
            return next(iter(bucket))
    return None


def score_domain_value(
    problem: Problem,
    state: SearchState,
    nurse: int,
    day: int,
    shift: Shift,
) -> float:
    """Estimate how restrictive a value is without modifying the state."""
    score = 0

    # Count the values this choice would remove from adjacent-day domains.
    if day > 0 and state.roster[nurse][day - 1] is None:
        if shift in {"M", "B"}:
            score += (state.domains[nurse][day - 1] & MBE).bit_count()
        elif shift == "A":
            score += int(bool(state.domains[nurse][day - 1] & B_BIT))

    if day + 1 < problem.D and state.roster[nurse][day + 1] is None:
        if shift in {"M", "E"}:
            score += (state.domains[nurse][day + 1] & MB).bit_count()
        elif shift == "B":
            score += (state.domains[nurse][day + 1] & MAB).bit_count()

    # Penalize consuming a candidate from a coverage requirement that has
    # little slack. A value that provides the coverage does not consume it.
    def slack_penalty(candidate_count: int, needed: int) -> int:
        if needed <= 0:
            return 0
        slack = candidate_count - needed
        if slack <= 0:
            return 0
        if slack == 1:
            return 5
        if slack == 2:
            return 2
        return 0

    morning_needed = problem.morning_required - state.morning_coverage[day]
    if shift not in {"M", "B"} and nurse in state.morning_candidates[day]:
        score += slack_penalty(
            len(state.morning_candidates[day]), morning_needed
        )

    afternoon_needed = (
        problem.afternoon_required - state.afternoon_coverage[day]
    )
    if shift not in {"A", "B"} and nurse in state.afternoon_candidates[day]:
        score += slack_penalty(
            len(state.afternoon_candidates[day]), afternoon_needed
        )

    evening_needed = problem.evening_required - state.evening_coverage[day]
    if shift != "E" and nurse in state.evening_candidates[day]:
        score += slack_penalty(
            len(state.evening_candidates[day]), evening_needed
        )

    # Reaching K forces every remaining day for this nurse to R.
    if (
        shift != "R"
        and state.nurse_shift_load[nurse] + shift_load(shift)
        == problem.max_shifts
    ):
        score += 5

    # Prefer satisfying an uncovered surgical day with B.
    if shift == "B" and problem.is_surgical_day(day):
        if state.surgery_coverage[day] == 0:
            score -= 5

    return score


def order_domain_values(
    problem: Problem,
    state: SearchState,
    nurse: int,
    day: int,
    scorer: ValueScorer = score_domain_value,
) -> list[Shift]:
    """Order consistent values using the supplied estimated-cost function.

    In randomized-restart mode (_RNG set), IGNORE the
    heuristic scorer entirely and use a uniformly random order instead of
    a randomized tiebreak on top of it. Empirically (see the `test25`
    thrashing case in NOTES_correctness_and_approaches.md /
    NOTES_experiment_results.md), the current heuristic scorer actively
    misleads the search on some slack-rich, symmetric-nurse instances --
    pure random ordering solved that case on the very first restart
    attempt, while randomizing only score-ties (keeping the heuristic in
    charge) did not solve it even after ~10 restarts. The deterministic
    first attempt still uses the real scorer unchanged, so already-fast
    cases are unaffected; only instances where the heuristic-guided
    attempt times out fall back to this.
    """
    consistent_values: list[Shift] = []

    for shift in domain_bits(state.domains[nurse][day]):
        if not is_consistent(problem, state, nurse, day, shift):
            continue
        consistent_values.append(shift)

    if _RNG is not None:
        shuffled = list(consistent_values)
        _RNG.shuffle(shuffled)
        return shuffled

    scored_values = [
        (scorer(problem, state, nurse, day, shift), order, shift)
        for order, shift in enumerate(consistent_values)
    ]
    scored_values.sort()
    return [shift for _, _, shift in scored_values]


def is_consistent(
    problem: Problem,
    state: SearchState,
    nurse: int,
    day: int,
    shift: Shift,
) -> bool:

    # check for H1
    if state.roster[nurse][day] is not None:
        return False
    elif not (state.domains[nurse][day] & BIT_OF[shift]):
        return False
    elif not problem.is_surgical_nurse(nurse) and shift == "B":
        return False
    # check for H9
    elif problem.is_on_leave(nurse, day) and shift != "R":
        return False
    # check for H2, H3
    # if adjoining cells have been filled already with M/B, M/B are already removed from domain,
    # so the check is already completed above; similarly, H3 is checked by domain removal above
    # check for H4
    if (
        state.morning_coverage[day] == problem.morning_required
        or state.afternoon_coverage[day] == problem.afternoon_required
    ) and shift == "B":
        return False
    elif state.morning_coverage[day] == problem.morning_required and shift == "M":
        return False
    elif state.afternoon_coverage[day] == problem.afternoon_required and shift == "A":
        return False
    elif state.evening_coverage[day] == problem.evening_required and shift == "E":
        return False
    # check for H5
    if shift != "R":
        first_window_start = max(0, day - 5)
        last_window_start = min(day, problem.D - 6)

        for start in range(first_window_start, last_window_start + 1):
            works_all_six_days = True
            for window_day in range(start, start + 6):
                assigned_shift = (
                    shift if window_day == day else state.roster[nurse][window_day]
                )
                if assigned_shift is None or assigned_shift == "R":
                    works_all_six_days = False
                    break

            if works_all_six_days:
                return False
    # check for H6 is also based on domain removal, and is covered above
    # partial check for H7
    if problem.is_surgical_nurse(nurse) and problem.is_surgical_day(day):
        if (
            state.surgery_coverage[day] == 0
            and state.surgery_candidates[day] == {nurse}
            and shift != "B"
        ):
            return False

    # check for H8
    if state.nurse_shift_load[nurse] + shift_load(shift) > problem.max_shifts:
        return False

    return True


def assign(state: SearchState, nurse: int, day: int, shift: Shift) -> None:
    """Place one value and update incremental counters."""
    if state.roster[nurse][day] is not None:
        raise ValueError("attempted to assign an already assigned cell")

    state.domain_buckets[state.domains[nurse][day].bit_count()].remove((nurse, day))
    state.roster[nurse][day] = shift
    update_coverage_candidates(state, nurse, day)
    if shift in {"M", "B"}:
        state.morning_coverage[day] += 1
    if shift in {"A", "B"}:
        state.afternoon_coverage[day] += 1
    if shift == "E":
        state.evening_coverage[day] += 1
    if shift == "B":
        state.surgery_coverage[day] += 1
    state.unassigned_on_day[day] -= 1
    state.nurse_shift_load[nurse] += shift_load(shift)
    state.unassigned_count -= 1


def unassign(state: SearchState, nurse: int, day: int, shift: Shift) -> None:
    """Undo exactly one assignment and its counter changes."""
    if state.roster[nurse][day] != shift:
        raise ValueError("assignment rollback does not match current value")

    state.roster[nurse][day] = None
    if shift in {"M", "B"}:
        state.morning_coverage[day] -= 1
    if shift in {"A", "B"}:
        state.afternoon_coverage[day] -= 1
    if shift == "E":
        state.evening_coverage[day] -= 1
    if shift == "B":
        state.surgery_coverage[day] -= 1
    state.unassigned_on_day[day] += 1
    state.nurse_shift_load[nurse] -= shift_load(shift)
    state.unassigned_count += 1
    state.domain_buckets[state.domains[nurse][day].bit_count()].add((nurse, day))
    update_coverage_candidates(state, nurse, day)


def forward_check(
    problem: Problem,
    state: SearchState,
    nurse: int,
    day: int,
    shift: Shift,
) -> Optional[list[DomainChange]]:
    """Prune neighboring domains after an assignment.

    Return a trail of removed ``(nurse, day, value)`` triples. Return None
    when any unassigned variable loses its entire domain.
    """
    changes: list[DomainChange] = []
    dirty_days = {day}

    def remove_values(target_nurse: int, target_day: int, values_mask: int) -> None:
        """Batch update_coverage_candidates (and the domain_buckets move)
        to once per cell touched, using a single bitmask AND-NOT instead
        of removing bits one at a time -- see NOTES_python_perf_experiments.md
        (and experiments/part_a_lazy_candidates.py for the original,
        set-based version of this same batching idea)."""
        if state.roster[target_nurse][target_day] is not None:
            return
        domain = state.domains[target_nurse][target_day]
        to_remove = domain & values_mask
        if not to_remove:
            return
        cell = (target_nurse, target_day)
        old_size = domain.bit_count()
        new_domain = domain & ~values_mask
        state.domain_buckets[old_size].remove(cell)
        state.domains[target_nurse][target_day] = new_domain
        state.domain_buckets[new_domain.bit_count()].add(cell)
        bit = 1
        while bit <= to_remove:
            if to_remove & bit:
                changes.append((target_nurse, target_day, SHIFT_OF[bit]))
            bit <<= 1
        dirty_days.add(target_day)
        update_coverage_candidates(state, target_nurse, target_day)

    # H2, H3, H6: prune the previous and next day for this nurse.
    if day > 0:
        if shift in {"M", "B"}:
            remove_values(nurse, day - 1, MBE)
        elif shift == "A":
            remove_values(nurse, day - 1, B_BIT)

    if day + 1 < problem.D:
        if shift == "M":
            remove_values(nurse, day + 1, MB)
        elif shift == "E":
            remove_values(nurse, day + 1, MB)
        elif shift == "B":
            remove_values(nurse, day + 1, MAB)

    # H8: once this nurse has reached K, every remaining cell must be R.
    if state.nurse_shift_load[nurse] == problem.max_shifts:
        for other_day in range(problem.D):
            remove_values(nurse, other_day, MAEB)

    # H5: five consecutive assigned working days force each adjoining
    # unassigned day, if it exists, to R.
    first_window_start = max(0, day - 4)
    last_window_start = min(day, problem.D - 5)
    for start in range(first_window_start, last_window_start + 1):
        if all(
            state.roster[nurse][window_day] not in {None, "R"}
            for window_day in range(start, start + 5)
        ):
            if start > 0:
                remove_values(nurse, start - 1, MAEB)
            if start + 5 < problem.D:
                remove_values(nurse, start + 5, MAEB)

    # H4: process only days whose candidate sets changed. Domain removals on
    # a day add that day back to the worklist, allowing forced values to
    # propagate until no affected day remains.
    while dirty_days:
        target_day = dirty_days.pop()

        # H7: an uncovered surgical day must retain at least one B candidate;
        # if exactly one remains, force that cell to B.
        if (
            problem.is_surgical_day(target_day)
            and state.surgery_coverage[target_day] == 0
        ):
            if not state.surgery_candidates[target_day]:
                restore_domains(state, changes)
                return None
            if len(state.surgery_candidates[target_day]) == 1:
                last_surgical_nurse = next(
                    iter(state.surgery_candidates[target_day])
                )
                remove_values(
                    last_surgical_nurse,
                    target_day,
                    MAER,
                )

        morning_needed = (
            problem.morning_required - state.morning_coverage[target_day]
        )
        afternoon_needed = (
            problem.afternoon_required - state.afternoon_coverage[target_day]
        )
        evening_needed = (
            problem.evening_required - state.evening_coverage[target_day]
        )

        if (
            morning_needed < 0
            or afternoon_needed < 0
            or evening_needed < 0
            or len(state.morning_candidates[target_day]) < morning_needed
            or len(state.afternoon_candidates[target_day]) < afternoon_needed
            or len(state.evening_candidates[target_day]) < evening_needed
        ):
            restore_domains(state, changes)
            return None

        if morning_needed == 0:
            for candidate in list(state.morning_candidates[target_day]):
                remove_values(candidate, target_day, MB)
        elif len(state.morning_candidates[target_day]) == morning_needed:
            for candidate in list(state.morning_candidates[target_day]):
                remove_values(candidate, target_day, AER)

        if afternoon_needed == 0:
            for candidate in list(state.afternoon_candidates[target_day]):
                remove_values(candidate, target_day, AB)
        elif len(state.afternoon_candidates[target_day]) == afternoon_needed:
            for candidate in list(state.afternoon_candidates[target_day]):
                remove_values(candidate, target_day, MER)

        if evening_needed == 0:
            for candidate in list(state.evening_candidates[target_day]):
                remove_values(candidate, target_day, E_BIT)
        elif len(state.evening_candidates[target_day]) == evening_needed:
            for candidate in list(state.evening_candidates[target_day]):
                remove_values(candidate, target_day, MABR)

        if state.domain_buckets[0]:
            restore_domains(state, changes)
            return None

    # A failed propagation must restore its own removals because None does
    # not carry a trail back to the caller.
    if state.domain_buckets[0]:
        restore_domains(state, changes)
        return None

    return changes


def restore_domains(state: SearchState, changes: list[DomainChange]) -> None:
    """Undo domain removals in reverse order.

    Defer update_coverage_candidates to once per unique cell
    touched (see experiments/part_a_lazy_candidates.py)."""
    touched_cells: set[Variable] = set()
    for nurse, day, shift in reversed(changes):
        old_size = state.domains[nurse][day].bit_count()
        cell = (nurse, day)
        state.domain_buckets[old_size].remove(cell)
        state.domains[nurse][day] |= BIT_OF[shift]
        state.domain_buckets[old_size + 1].add(cell)
        touched_cells.add(cell)
    for nurse, day in touched_cells:
        update_coverage_candidates(state, nurse, day)


def final_constraints_hold(problem: Problem, state: SearchState) -> bool:
    """Check exact daily coverage after all incremental constraints pass."""
    if state.unassigned_count != 0:
        return False

    for day in range(problem.D):
        if state.morning_coverage[day] != problem.morning_required:
            return False
        if state.afternoon_coverage[day] != problem.afternoon_required:
            return False
        if state.evening_coverage[day] != problem.evening_required:
            return False

    return True


def backtrack(problem: Problem, state: SearchState, deadline: float) -> bool:
    """Run depth-first backtracking with forward checking."""
    if time.monotonic() >= deadline:
        raise SearchTimeout

    if state.unassigned_count == 0:
        return final_constraints_hold(problem, state)

    variable = select_unassigned_variable(problem, state)
    if variable is None:
        return False
    nurse, day = variable

    for shift in order_domain_values(problem, state, nurse, day):
        if not is_consistent(problem, state, nurse, day, shift):
            continue

        assign(state, nurse, day, shift)
        changes = forward_check(problem, state, nurse, day, shift)

        if changes is not None:
            if backtrack(problem, state, deadline):
                return True
            restore_domains(state, changes)

        unassign(state, nurse, day, shift)

    return False


def solve(problem: Problem) -> Optional[list[list[Shift]]]:
    """Return a valid N-by-D roster, or None if none is found in time.

    After a deterministic first attempt (identical to the
    real part_a.py, so already-fast cases are unaffected), fall back to
    randomized-tiebreak restarts with the remaining time budget if that
    attempt times out without a definite conclusion (L05: random restarts).
    A restart's own backtrack() completing WITHOUT hitting its slice's
    deadline is still a valid exhaustive proof of infeasibility regardless
    of tie-break ordering (forward-checking pruning never removes a true
    solution, only provably-inconsistent partial assignments), so any
    restart that returns False definitively -- not via SearchTimeout --
    ends the search immediately.
    """
    global _RNG

    if not basic_feasibility_checks(problem):
        return None

    overall_deadline = time.monotonic() + max(0.0, problem.time_limit)
    restart_slice = max(0.5, problem.time_limit * 0.1)

    # The deterministic first attempt also gets only a bounded slice, not
    # the whole budget -- otherwise a slow deterministic run would consume
    # 100% of the time and restarts would never get a chance to run at all.
    _RNG = None
    state = build_initial_state(problem)
    first_deadline = min(overall_deadline, time.monotonic() + restart_slice)
    try:
        solved = backtrack(problem, state, first_deadline)
    except SearchTimeout:
        solved = None  # ran out of its slice without a conclusion

    if solved:
        return [[shift for shift in row] for row in state.roster]  # type: ignore[misc]
    if solved is False:
        return None  # exhaustively proven infeasible

    attempt = 0
    while time.monotonic() < overall_deadline:
        attempt += 1
        _RNG = random.Random(attempt)
        state = build_initial_state(problem)
        restart_deadline = min(overall_deadline, time.monotonic() + restart_slice)
        try:
            solved = backtrack(problem, state, restart_deadline)
        except SearchTimeout:
            continue
        if solved:
            return [[shift for shift in row] for row in state.roster]  # type: ignore[misc]
        if solved is False:
            return None  # exhaustively proven infeasible within this slice

    return None


def roster_to_json(roster: list[list[Shift]]) -> dict[str, Shift]:
    """Convert roster[nurse][day] to the required flat JSON object."""
    return {
        f"N{nurse}_{day}": shift
        for nurse, row in enumerate(roster)
        for day, shift in enumerate(row)
    }


def write_solution(output_json: str, roster: Optional[list[list[Shift]]]) -> None:
    """Write exactly one JSON object; None is represented by {}."""
    payload = {} if roster is None else roster_to_json(roster)
    with open(output_json, "w", encoding="utf-8") as json_file:
        json.dump(payload, json_file)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python part_a.py <input_csv_path> <output_json_path>")

    sys.setrecursionlimit(5000)
    problem = parse_input(sys.argv[1])
    roster = solve(problem)
    write_solution(sys.argv[2], roster)


if __name__ == "__main__":
    main()
