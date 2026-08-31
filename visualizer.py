import csv
import json
import re
import sys

# def read_input_csv(input_csv):
#     """Reads the CSV and initializes problem variables."""
#     with open(input_csv, 'r') as f:
#         reader = csv.DictReader(f)
#         row = next(reader)
#         print(row)
    
#         N = int(row['N'])
#         D = int(row['D'])
#         N_s = int(row['N_s'])
#         N_g = int(row['N_g'])
#         m = int(row['m'])
#         a = int(row['a'])
#         e = int(row['e'])
#         T = float(row['T'])
#         days = row['days']
#         max_shifts = int(row['K'])
#         leaves = row['leaves']
#     return N, D, days

# simple ANSI colour codes for the terminal
RESET = "\033[0m"
BOLD = "\033[1m"
SURGICAL_NURSE_COLOR = "\033[1;32m"   # bold green
GENERAL_NURSE_COLOR = "\033[34m"      # blue
SURGICAL_DAY_COLOR = "\033[31m"       # red
GENERAL_DAY_COLOR = "\033[33m"        # yellow


def read_input_csv(input_csv):
    """Reads the single row from the input csv."""
    with open(input_csv, 'r') as f:
        reader = csv.DictReader(f)
        row = next(reader)

    N = int(row['N'])
    D = int(row['D'])
    N_s = int(row['N_s'])
    days = row['days']
    return N, D, N_s, days



def read_solution_json(solution_json):
    with open(solution_json, 'r') as f:
        solution = json.load(f)
    return solution


def color_nurse(nurse_id, N_s):
    # nurse ids look like "N0", "N1" ... surgical nurses are 0 to N_s-1
    nurse_num = int(nurse_id[1:])
    if nurse_num < N_s:
        return f"{SURGICAL_NURSE_COLOR}{nurse_id}{RESET}"
    return f"{GENERAL_NURSE_COLOR}{nurse_id}{RESET}"


def color_day_header(text, day_type):
    if day_type == 'S':
        return f"{SURGICAL_DAY_COLOR}{text}{RESET}"
    return f"{GENERAL_DAY_COLOR}{text}{RESET}"


def visible_len(text):
    # ansi colour codes don't take up space on screen, so strip them
    # before measuring how wide a piece of text actually is
    return len(re.sub(r'\033\[[0-9;]*m', '', text))


def visualize(input_csv, solution_json, days_per_block=7):
    N, D, N_s, days = read_input_csv(input_csv)
    solution = read_solution_json(solution_json)

    columns = [f"Day{d}({days[d]})" for d in range(D)]

    # figure out which nurses work which shift on which day
    cell_text = {'M': {}, 'A': {}, 'E': {}}
    for d in range(D):
        for shift in ['M', 'A', 'E']:
            nurses_here = []
            for n in range(N):
                key = f"N{n}_{d}"
                assigned_shift = solution.get(key)
                if assigned_shift == shift:
                    nurses_here.append(f"N{n}")
                elif assigned_shift == 'B' and shift in ('M', 'A'):
                    # a nurse on B works both morning and afternoon
                    nurses_here.append(f"N{n}")

            if nurses_here:
                cell_text[shift][d] = ', '.join(color_nurse(n, N_s) for n in nurses_here)
            else:
                cell_text[shift][d] = '-'

    # work out how wide each column needs to be, based on the visible text
    col_widths = []
    for d in range(D):
        width = visible_len(columns[d])
        for shift in ['M', 'A', 'E']:
            width = max(width, visible_len(cell_text[shift][d]))
        col_widths.append(width + 2)

    for block_start in range(0, D, days_per_block):
        block_end = min(block_start + days_per_block, D)

        # print the header row for this block of days
        header = "Shift".ljust(8)
        for d in range(block_start, block_end):
            text = color_day_header(columns[d], days[d])
            header += text + " " * (col_widths[d] - visible_len(columns[d]))
        print(header)

        # print the M, A, E rows for this block of days
        for shift in ['M', 'A', 'E']:
            row = shift.ljust(8)
            for d in range(block_start, block_end):
                text = cell_text[shift][d]
                row += text + " " * (col_widths[d] - visible_len(text))
            print(row)

        if block_end < D:
            print()

    print()
    print(f"Legend: {SURGICAL_NURSE_COLOR}Surgical Nurse{RESET}   {GENERAL_NURSE_COLOR}General Nurse{RESET}")
    print(f"Day type: {SURGICAL_DAY_COLOR}Surgical Day{RESET}   {GENERAL_DAY_COLOR}General Day{RESET}")
    print("M=Morning, A=Afternoon, E=Evening, B=Both (M+A)")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("Usage: python visualizer.py <input_csv> <solution_json> [days_per_block]")
        sys.exit(1)

    days_per_block = int(sys.argv[3]) if len(sys.argv) == 4 else 7
    if days_per_block <= 0:
        print("days_per_block must be greater than 0")
        sys.exit(1)

    visualize(sys.argv[1], sys.argv[2], days_per_block)
