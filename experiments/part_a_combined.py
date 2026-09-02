#!/usr/bin/env python3
"""EXPERIMENTAL variant of part_a.py: degree-heuristic MRV tiebreak PLUS
hybrid true-LCV value ordering, combined.

Forked from the real part_a.py; combines the two independently-benchmarked
experiments (part_a_degree_heuristic.py, part_a_hybrid_lcv.py) to measure
their joint effect. Everything else is unmodified from the current,
checker-verified-sound part_a.py.

Part A: nurse rostering as a constraint satisfaction problem.

The intended CSP model is:

    variable:       (nurse, day)
    value/domain:   one of M, A, E, R, B
    assignment:     roster[nurse][day]
"""

from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional


Shift = str
Variable = tuple[int, int]
DomainChange = tuple[int, int, Shift]
ValueScorer = Callable[["Problem", "SearchState", int, int, Shift], float]


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
    domains: list[list[set[Shift]]]
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


def initial_domain(problem: Problem, nurse: int, day: int) -> set[Shift]:
    """Return the static domain before search-dependent pruning.

    Leave cells are forced to R. B is available only to surgical nurses on
    surgical days; the supplied verifier rejects B on general days.
    """
    if problem.is_on_leave(nurse, day):
        return {"R"}
    if problem.is_surgical_nurse(nurse) and problem.is_surgical_day(day):
        return set(["M", "A", "E", "R", "B"])
    return set(["M", "A", "E", "R"])


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
            domain_buckets[len(domains[nurse][day])].add((nurse, day))
            if domains[nurse][day] & {"M", "B"}:
                morning_candidates[day].add(nurse)
            if domains[nurse][day] & {"A", "B"}:
                afternoon_candidates[day].add(nurse)
            if "E" in domains[nurse][day]:
                evening_candidates[day].add(nurse)
            if "B" in domains[nurse][day]:
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

    if domain & {"M", "B"}:
        state.morning_candidates[day].add(nurse)
    else:
        state.morning_candidates[day].discard(nurse)

    if domain & {"A", "B"}:
        state.afternoon_candidates[day].add(nurse)
    else:
        state.afternoon_candidates[day].discard(nurse)

    if "E" in domain:
        state.evening_candidates[day].add(nurse)
    else:
        state.evening_candidates[day].discard(nurse)

    if "B" in domain:
        state.surgery_candidates[day].add(nurse)
    else:
        state.surgery_candidates[day].discard(nurse)


def basic_feasibility_checks(p: Problem) -> bool:
    leaves_count = [0] * p.D
    surgical_leaves_count = [0] * p.D
    for i in range(p.N * p.D):
        if p.leaves[i] == "L":
            leaves_count[i % p.D] += 1
            if i // p.D < p.Ns:
                surgical_leaves_count[i % p.D] += 1

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
    elif p.N * p.max_shifts < daily_requirement * p.D:
        return False
    return True


def select_unassigned_variable(
    problem: Problem, state: SearchState
) -> Optional[Variable]:
    """Choose an unassigned cell using minimum remaining values (MRV),
    breaking ties with a degree-heuristic proxy: among cells tied for the
    smallest domain, prefer the one whose day has the most other still-
    unassigned cells.

    EXPERIMENTAL VARIANT of select_unassigned_variable in part_a.py.
    """
    for bucket in state.domain_buckets:
        if bucket:
            return max(bucket, key=lambda cell: state.unassigned_on_day[cell[1]])
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
            score += len(state.domains[nurse][day - 1] & {"M", "B", "E"})
        elif shift == "A":
            score += int("B" in state.domains[nurse][day - 1])

    if day + 1 < problem.D and state.roster[nurse][day + 1] is None:
        if shift in {"M", "E"}:
            score += len(state.domains[nurse][day + 1] & {"M", "B"})
        elif shift == "B":
            score += len(state.domains[nurse][day + 1] & {"M", "A", "B"})

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


LCV_CANDIDATE_THRESHOLD = 3


def true_lcv_score(
    problem: Problem,
    state: SearchState,
    nurse: int,
    day: int,
    shift: Shift,
) -> int:
    """Speculatively assign+forward-check a value and count domain removals.

    This is the textbook LCV cost: the number of values ruled out in
    neighboring domains. A wipeout (search dead end) is scored as a large
    sentinel so it sorts last. Affordable only when few candidates remain,
    since it pays the full forward_check cost per candidate.
    """
    assign(state, nurse, day, shift)
    changes = forward_check(problem, state, nurse, day, shift)
    if changes is None:
        cost = 10**6
    else:
        cost = len(changes)
        restore_domains(state, changes)
    unassign(state, nurse, day, shift)
    return cost


def order_domain_values(
    problem: Problem,
    state: SearchState,
    nurse: int,
    day: int,
    scorer: ValueScorer = score_domain_value,
) -> list[Shift]:
    """Order consistent values using the supplied estimated-cost function.

    EXPERIMENTAL: once the number of consistent candidates for this cell is
    small (<= LCV_CANDIDATE_THRESHOLD), fall back to true LCV
    (speculative-assign + forward-check + count removed values) instead of
    the cheap heuristic scorer, since the exact count is affordable there
    and strictly more accurate than the proxy.
    """
    shift_order = ("M", "A", "E", "R", "B")
    candidates: list[Shift] = []

    for shift in shift_order:
        if shift not in state.domains[nurse][day]:
            continue
        if not is_consistent(problem, state, nurse, day, shift):
            continue
        candidates.append(shift)

    if len(candidates) <= LCV_CANDIDATE_THRESHOLD:
        scored_values = [
            (true_lcv_score(problem, state, nurse, day, shift), order, shift)
            for order, shift in enumerate(candidates)
        ]
    else:
        scored_values = [
            (scorer(problem, state, nurse, day, shift), order, shift)
            for order, shift in enumerate(candidates)
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
    elif shift not in state.domains[nurse][day]:
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

    state.domain_buckets[len(state.domains[nurse][day])].remove((nurse, day))
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
    state.domain_buckets[len(state.domains[nurse][day])].add((nurse, day))
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

    def remove_values(target_nurse: int, target_day: int, values: set[Shift]) -> None:
        if state.roster[target_nurse][target_day] is not None:
            return
        for value in values:
            if value in state.domains[target_nurse][target_day]:
                old_size = len(state.domains[target_nurse][target_day])
                cell = (target_nurse, target_day)
                state.domain_buckets[old_size].remove(cell)
                state.domains[target_nurse][target_day].remove(value)
                state.domain_buckets[old_size - 1].add(cell)
                update_coverage_candidates(state, target_nurse, target_day)
                changes.append((target_nurse, target_day, value))
                dirty_days.add(target_day)

    # H2, H3, H6: prune the previous and next day for this nurse.
    if day > 0:
        if shift in {"M", "B"}:
            remove_values(nurse, day - 1, {"M", "B", "E"})
        elif shift == "A":
            remove_values(nurse, day - 1, {"B"})

    if day + 1 < problem.D:
        if shift == "M":
            remove_values(nurse, day + 1, {"M", "B"})
        elif shift == "E":
            remove_values(nurse, day + 1, {"M", "B"})
        elif shift == "B":
            remove_values(nurse, day + 1, {"M", "A", "B"})

    # H8: once this nurse has reached K, every remaining cell must be R.
    if state.nurse_shift_load[nurse] == problem.max_shifts:
        for other_day in range(problem.D):
            remove_values(nurse, other_day, {"M", "A", "E", "B"})

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
                remove_values(nurse, start - 1, {"M", "A", "E", "B"})
            if start + 5 < problem.D:
                remove_values(nurse, start + 5, {"M", "A", "E", "B"})

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
                    {"M", "A", "E", "R"},
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
                remove_values(candidate, target_day, {"M", "B"})
        elif len(state.morning_candidates[target_day]) == morning_needed:
            for candidate in list(state.morning_candidates[target_day]):
                remove_values(candidate, target_day, {"A", "E", "R"})

        if afternoon_needed == 0:
            for candidate in list(state.afternoon_candidates[target_day]):
                remove_values(candidate, target_day, {"A", "B"})
        elif len(state.afternoon_candidates[target_day]) == afternoon_needed:
            for candidate in list(state.afternoon_candidates[target_day]):
                remove_values(candidate, target_day, {"M", "E", "R"})

        if evening_needed == 0:
            for candidate in list(state.evening_candidates[target_day]):
                remove_values(candidate, target_day, {"E"})
        elif len(state.evening_candidates[target_day]) == evening_needed:
            for candidate in list(state.evening_candidates[target_day]):
                remove_values(candidate, target_day, {"M", "A", "B", "R"})

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
    """Undo domain removals in reverse order."""
    for nurse, day, shift in reversed(changes):
        old_size = len(state.domains[nurse][day])
        cell = (nurse, day)
        state.domain_buckets[old_size].remove(cell)
        state.domains[nurse][day].add(shift)
        state.domain_buckets[old_size + 1].add(cell)
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
    """Return a valid N-by-D roster, or None if none is found in time."""
    if not basic_feasibility_checks(problem):
        return None

    state = build_initial_state(problem)
    deadline = time.monotonic() + max(0.0, problem.time_limit)

    try:
        solved = backtrack(problem, state, deadline)
    except SearchTimeout:
        return None

    if not solved:
        return None

    # A successful complete search guarantees that no entry is None.
    return [[shift for shift in row] for row in state.roster]  # type: ignore[misc]


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
