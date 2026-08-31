#!/usr/bin/env python3
"""Verify a nurse-rostering solution against an assignment instance."""

import csv
import json
from pickle import TRUE
import sys
import pdb 

SHIFTS = {"M", "A", "E", "R", "B"}


def read_input(csv_path):
    """Read and validate the single instance stored in ``csv_path``."""
    with open(csv_path, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)

    required = {"N", "D", "N_s", "N_g", "m", "a", "e", "T", "days", "K", 'leaves'}
    if len(rows) != 1 or reader.fieldnames is None:
        raise ValueError("input CSV must contain exactly one data row")
    if set(reader.fieldnames) != required:
        raise ValueError("input CSV has unexpected columns")

    row = rows[0]
    instance = {
        name: int(row[name]) for name in ("N", "D", "N_s", "N_g", "m", "a", "e")
    }
    instance["T"] = float(row["T"])
    instance["days"] = row["days"]
    instance["K"] = int(row["K"])
    instance["leaves"] = row["leaves"]
    if any(instance[name] < 0 for name in ("N", "D", "N_s", "N_g", "m", "a", "e")):
        raise ValueError("instance values must be non-negative")
    if instance["N_s"] + instance["N_g"] != instance["N"]:
        raise ValueError("N_s + N_g must equal N")
    if len(instance["days"]) != instance["D"] or set(instance["days"]) - {"G", "S"}:
        raise ValueError("days must contain exactly D characters from G and S")

    return instance


def read_solution(json_path):
    """Read a solution JSON object."""
    with open(json_path, encoding="utf-8") as json_file:
        solution = json.load(json_file)
    if not isinstance(solution, dict):
        raise ValueError("solution must be a JSON object")
    return solution


def _expected_keys(instance):
    return {
        f"N{nurse}_{day}"
        for nurse in range(instance["N"])
        for day in range(instance["D"])
    }


def _shift(solution, nurse, day):
    return solution[f"N{nurse}_{day}"]


def verify_h1(instance, solution):
    """Every cell exists, has a legal shift, and B is surgical-only."""
    if set(solution) != _expected_keys(instance):
        return False
    print("done")
    for nurse in range(instance["N"]):
        for day in range(instance["D"]):
            shift = _shift(solution, nurse, day)
            if not isinstance(shift, str) or shift not in SHIFTS:
                print("not a string")
                return False
            if shift == "B" and nurse >= instance["N_s"]:
                print("Non surgical nurse assigned B")
                return False
    return True


def verify_h2(instance, solution):
    """No morning shift may be followed by another morning shift."""
    morning_shifts = {"M", "B"}
    for nurse in range(instance["N"]):
        for day in range(instance["D"] - 1):
            if (_shift(solution, nurse, day) in morning_shifts
                    and _shift(solution, nurse, day + 1) in morning_shifts):
                print(nurse, day)
                return False
    return True


def verify_h3(instance, solution):
    """An evening may not be followed by a morning shift."""
    for nurse in range(instance["N"]):
        for day in range(instance["D"] - 1):
            if (_shift(solution, nurse, day) == "E"
                    and _shift(solution, nurse, day + 1) in {"M", "B"}):
                return False
    return True


def verify_h4(instance, solution):
    """Check exact daily coverage, with B covering both M and A."""
    for day, day_type in enumerate(instance["days"]):
        counts = {shift: 0 for shift in SHIFTS}
        for nurse in range(instance["N"]):
            counts[_shift(solution, nurse, day)] += 1

        if day_type == "G" and counts["B"] != 0:
            return False
        if counts["M"] + counts["B"] != instance["m"]:
            return False
        if counts["A"] + counts["B"] != instance["a"]:
            return False
        if counts["E"] != instance["e"]:
            return False
    return True


def verify_h5(instance, solution):
    """Every six-day window for every nurse contains a rest day."""
    for nurse in range(instance["N"]):
        for start in range(instance["D"] - 5):
            if all(_shift(solution, nurse, day) != "R"
                   for day in range(start, start + 6)):
                return False
    return True


def verify_h6(instance, solution):
    """A B shift may only be followed by R or E."""
    for nurse in range(instance["N"]):
        for day in range(instance["D"] - 1):
            if (_shift(solution, nurse, day) == "B"
                    and _shift(solution, nurse, day + 1) not in {"R", "E"}):
                return False
    return True


def verify_h7(instance, solution):
    """Every surgery-day crew includes a surgical nurse."""
    for day, day_type in enumerate(instance["days"]):
        if day_type == "S" and not any(
            _shift(solution, nurse, day) == "B"
            for nurse in range(instance["N_s"])
        ):
            return False
    return True

def verify_h8(instance, solution):
    """Return the integer objective value 9 * cost."""
    objective = 0
    for nurse in range(instance["N"]):
        mornings = afternoons = evenings = 0
        for day in range(instance["D"]):
            shift = _shift(solution, nurse, day)
            mornings += shift in {"M", "B"}
            afternoons += shift in {"A", "B"}
            evenings += shift == "E"

        total = mornings + afternoons + evenings
        if(total > instance["K"]):
            return False 
    return True

def verify_h9(instance, solution):
    leaves = instance['leaves']
    ind = 0
    for nurse in range(instance["N"]):
        for day in range(instance["D"]):
            shift = _shift(solution, nurse, day)
            if(leaves[ind] == 'L' and shift != 'R'):
                return False
            ind += 1
    return True


def calculate_objective(instance, solution):
    """Return the integer objective value 9 * cost."""
    objective = 0
    for nurse in range(instance["N"]):
        mornings = afternoons = evenings = 0
        for day in range(instance["D"]):
            shift = _shift(solution, nurse, day)
            mornings += shift in {"M", "B"}
            afternoons += shift in {"A", "B"}
            evenings += shift == "E"

        total = mornings + afternoons + evenings
        objective += 3 * (mornings ** 2 + afternoons ** 2 + evenings ** 2) - total ** 2
    return objective



def verify_solution(instance, solution):
    """Run H1 through H7 and return whether the solution is valid."""
    if not verify_h1(instance, solution):
        return False
    checks = (verify_h2, verify_h3, verify_h4, verify_h5, verify_h6, verify_h7, verify_h8, verify_h9)
    tt = [check(instance, solution) for check in checks]
    print(tt)
    return all(tt)

def main():
    if len(sys.argv) != 3:
        print("INVALID")
        return

    try:
        instance = read_input(sys.argv[1])
        solution = read_solution(sys.argv[2])
        if verify_solution(instance, solution):
            print(f"VALID {calculate_objective(instance, solution)}")
        else:
            print("INVALID")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        print("INVALID")


if __name__ == "__main__":
    main()