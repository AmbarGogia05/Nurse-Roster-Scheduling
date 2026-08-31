#!/usr/bin/env python3
"""Part A: nurse rostering as a constraint satisfaction problem.

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
from typing import Optional


Shift = str
Variable = tuple[int, int]
DomainChange = tuple[int, int, Shift]


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

    # Current coverage contributed by assigned cells on each day.
    morning_coverage: list[int]
    afternoon_coverage: list[int]
    evening_coverage: list[int]
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
    return SearchState(
        roster=[[None for _ in range(problem.D)] for _ in range(problem.N)],
        domains=[
            [initial_domain(problem, nurse, day) for day in range(problem.D)]
            for nurse in range(problem.N)
        ],
        morning_coverage=[0] * problem.D,
        afternoon_coverage=[0] * problem.D,
        evening_coverage=[0] * problem.D,
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
    """Choose an unassigned cell using minimum remaining values."""
    selected: Optional[Variable] = None
    smallest_domain = 6

    for nurse in range(problem.N):
        for day in range(problem.D):
            if state.roster[nurse][day] is None:
                domain_size = len(state.domains[nurse][day])
                if domain_size < smallest_domain:
                    smallest_domain = domain_size
                    selected = (nurse, day)

    return selected


def order_domain_values(
    problem: Problem, state: SearchState, nurse: int, day: int
) -> list[Shift]:
    """Order consistent values by the number of domain values they remove."""
    shift_order = ("M", "A", "E", "R", "B")
    scored_values: list[tuple[int, int, Shift]] = []

    for order, shift in enumerate(shift_order):
        if shift not in state.domains[nurse][day]:
            continue
        if not is_consistent(problem, state, nurse, day, shift):
            continue

        assign(state, nurse, day, shift)
        changes = forward_check(problem, state, nurse, day, shift)

        if changes is not None:
            scored_values.append((len(changes), order, shift))
            restore_domains(state, changes)

        unassign(state, nurse, day, shift)

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
        has_surgery_shift = any(
            state.roster[surgical_nurse][day] == "B"
            for surgical_nurse in range(problem.Ns)
        )
        if not has_surgery_shift:
            unassigned_surgical_nurses = sum(
                state.roster[surgical_nurse][day] is None
                for surgical_nurse in range(problem.Ns)
            )
            if unassigned_surgical_nurses == 1 and shift != "B":
                return False

    # check for H8
    if state.nurse_shift_load[nurse] + shift_load(shift) > problem.max_shifts:
        return False

    return True


def assign(state: SearchState, nurse: int, day: int, shift: Shift) -> None:
    """Place one value and update incremental counters."""
    if state.roster[nurse][day] is not None:
        raise ValueError("attempted to assign an already assigned cell")

    state.roster[nurse][day] = shift
    if shift in {"M", "B"}:
        state.morning_coverage[day] += 1
    if shift in {"A", "B"}:
        state.afternoon_coverage[day] += 1
    if shift == "E":
        state.evening_coverage[day] += 1
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
    state.unassigned_on_day[day] += 1
    state.nurse_shift_load[nurse] -= shift_load(shift)
    state.unassigned_count += 1


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

    def remove_values(target_nurse: int, target_day: int, values: set[Shift]) -> None:
        if state.roster[target_nurse][target_day] is not None:
            return
        for value in values:
            if value in state.domains[target_nurse][target_day]:
                state.domains[target_nurse][target_day].remove(value)
                changes.append((target_nurse, target_day, value))

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

    # H4: once a daily coverage target is full, no unassigned nurse may
    # contribute to that target.
    for other_nurse in range(problem.N):
        if state.roster[other_nurse][day] is not None:
            continue
        if state.morning_coverage[day] == problem.morning_required:
            remove_values(other_nurse, day, {"M", "B"})
        if state.afternoon_coverage[day] == problem.afternoon_required:
            remove_values(other_nurse, day, {"A", "B"})
        if state.evening_coverage[day] == problem.evening_required:
            remove_values(other_nurse, day, {"E"})

    # H7: if an uncovered surgical day has only one unassigned surgical
    # nurse left, that nurse must take B.
    if problem.is_surgical_day(day):
        has_surgery_shift = any(
            state.roster[surgical_nurse][day] == "B"
            for surgical_nurse in range(problem.Ns)
        )
        if not has_surgery_shift:
            remaining_surgical_nurses = [
                surgical_nurse
                for surgical_nurse in range(problem.Ns)
                if state.roster[surgical_nurse][day] is None
            ]
            if len(remaining_surgical_nurses) == 1:
                last_surgical_nurse = remaining_surgical_nurses[0]
                remove_values(
                    last_surgical_nurse,
                    day,
                    {"M", "A", "E", "R"},
                )

    # H8: once this nurse has reached K, every remaining cell must be R.
    if state.nurse_shift_load[nurse] == problem.max_shifts:
        for other_day in range(problem.D):
            remove_values(nurse, other_day, {"M", "A", "E", "B"})

    # H5: five consecutive assigned working days force each adjoining
    # unassigned day, if it exists, to R.
    for start in range(problem.D - 4):
        if all(
            state.roster[nurse][window_day] not in {None, "R"}
            for window_day in range(start, start + 5)
        ):
            if start > 0:
                remove_values(nurse, start - 1, {"M", "A", "E", "B"})
            if start + 5 < problem.D:
                remove_values(nurse, start + 5, {"M", "A", "E", "B"})

    # A failed propagation must restore its own removals because None does
    # not carry a trail back to the caller.
    for target_nurse in range(problem.N):
        for target_day in range(problem.D):
            if (
                state.roster[target_nurse][target_day] is None
                and not state.domains[target_nurse][target_day]
            ):
                restore_domains(state, changes)
                return None

    return changes


def restore_domains(state: SearchState, changes: list[DomainChange]) -> None:
    """Undo domain removals in reverse order."""
    for nurse, day, shift in reversed(changes):
        state.domains[nurse][day].add(shift)


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

    problem = parse_input(sys.argv[1])
    roster = solve(problem)
    write_solution(sys.argv[2], roster)


if __name__ == "__main__":
    main()
