"""
Validate precomputed _n_cited.csv and _n_mutual.csv.

Checks:
  1. Parse validity, non-negative values, row counts, and summary sums.
  2. n_cited parity against independent recomputation from edges.csv.
  3. n_mutual invariant: sum(n_mutual) == 2 * count(mutual_pairs).

Env:
  NCITED / NMUTUAL  Input metric CSVs (default: data/_n_cited.csv, data/_n_mutual.csv)
  EDGES / PAIRS     Input edges / mutual pairs (default: data/edges.csv, data/mutual_pairs.csv)
"""

import csv
import os
import sys

import duckdb

NCITED = os.environ.get("NCITED", "data/_n_cited.csv")
NMUTUAL = os.environ.get("NMUTUAL", "data/_n_mutual.csv")
EDGES = os.environ.get("EDGES", "data/edges.csv")
PAIRS = os.environ.get("PAIRS", "data/mutual_pairs.csv")

DUCKDB_TMP = os.environ.get("DUCKDB_TMP", "data/_duckdb_tmp")
MEM = os.environ.get("MEM", "10GB")


def validate_metric_file(path, value_col):
    """Validate one metric CSV and return basic statistics."""
    count = 0
    total = 0
    min_val = None
    max_val = None
    bad_rows = 0

    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)

            expected_columns = {"id", value_col}
            if not reader.fieldnames or not expected_columns.issubset(
                reader.fieldnames
            ):
                print(
                    f"  FAIL: expected columns {expected_columns}, "
                    f"found {reader.fieldnames}"
                )
                return None

            for line_no, row in enumerate(reader, start=2):
                try:
                    paper_id = int(row["id"])
                    value = int(row[value_col])

                    if paper_id < 0 or value < 0:
                        raise ValueError("negative ID/value")

                except (ValueError, TypeError):
                    bad_rows += 1
                    if bad_rows <= 5:
                        print(f"  BAD ROW {line_no}: {row}")
                    continue

                count += 1
                total += value
                min_val = value if min_val is None else min(min_val, value)
                max_val = value if max_val is None else max(max_val, value)

    except FileNotFoundError:
        print(f"  FAIL: file not found: {path}")
        return None
    except Exception as e:
        print(f"  FAIL: could not read {path}: {e}")
        return None

    return {
        "rows": count,
        "sum": total,
        "min": min_val,
        "max": max_val,
        "bad_rows": bad_rows,
    }


def count_mutual_pairs(path):
    """Count rows in mutual_pairs.csv."""
    count = 0

    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)

            expected_columns = {"paper_a", "paper_b"}
            if not reader.fieldnames or not expected_columns.issubset(
                reader.fieldnames
            ):
                print(
                    f"  FAIL: expected columns {expected_columns}, "
                    f"found {reader.fieldnames}"
                )
                return None

            for _ in reader:
                count += 1

    except FileNotFoundError:
        print(f"  FAIL: file not found: {path}")
        return None
    except Exception as e:
        print(f"  FAIL: could not read {path}: {e}")
        return None

    return count


def compute_expected_n_cited():
    """
    Independently compute the expected n_cited row count and sum from
    edges.csv using the same explicit definition as the build script.
    """
    os.makedirs(DUCKDB_TMP, exist_ok=True)

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute(f"SET temp_directory='{DUCKDB_TMP}'")
    con.execute("SET preserve_insertion_order=false")

    try:
        result = con.execute(f"""
            SELECT
                count(*) FILTER (WHERE n_cited > 0) AS positive_rows,
                sum(n_cited) FILTER (WHERE n_cited > 0) AS total_n_cited
            FROM (
                SELECT
                    len(list_distinct(string_split(targets, ';')))
                    - CASE
                        WHEN list_contains(
                            list_distinct(string_split(targets, ';')),
                            source
                        )
                        THEN 1
                        ELSE 0
                      END AS n_cited
                FROM read_csv(
                    '{EDGES}',
                    header=true,
                    all_varchar=true
                )
            )
        """).fetchone()

        return result

    finally:
        con.close()


def main():
    print("Validating n_cited / n_mutual files...\n")

    failures = 0

    # ------------------------------------------------------------
    # n_cited basic validation
    # ------------------------------------------------------------
    print(f"[1] {NCITED}")
    ncited = validate_metric_file(NCITED, "n_cited")

    if ncited is None:
        failures += 1
    else:
        print(f"  rows:       {ncited['rows']:,}")
        print(f"  min:        {ncited['min']:,}")
        print(f"  max:        {ncited['max']:,}")
        print(f"  sum:        {ncited['sum']:,}")
        print(f"  bad rows:   {ncited['bad_rows']:,}")

        if ncited["bad_rows"] == 0:
            print("  PASS: CSV and values look valid")
        else:
            print("  FAIL: invalid rows found")
            failures += 1

    # ------------------------------------------------------------
    # Independently recompute n_cited from edges.csv
    # ------------------------------------------------------------
    print(f"\n[2] Independently checking n_cited against {EDGES}")

    try:
        expected_rows, expected_sum = compute_expected_n_cited()

        print(f"  expected positive rows: {expected_rows:,}")
        print(f"  actual rows:            {ncited['rows']:,}")
        print(f"  expected sum:           {expected_sum:,}")
        print(f"  actual sum:             {ncited['sum']:,}")

        if ncited["rows"] == expected_rows:
            print("  PASS: n_cited row count matches")
        else:
            print("  FAIL: n_cited row count does not match")
            failures += 1

        if ncited["sum"] == expected_sum:
            print("  PASS: n_cited sum matches")
        else:
            print("  FAIL: n_cited sum does not match")
            failures += 1

    except Exception as e:
        print(f"  FAIL: could not independently compute n_cited: {e}")
        failures += 1

    # ------------------------------------------------------------
    # n_mutual basic validation
    # ------------------------------------------------------------
    print(f"\n[3] {NMUTUAL}")
    nmutual = validate_metric_file(NMUTUAL, "n_mutual")

    if nmutual is None:
        failures += 1
    else:
        print(f"  rows:       {nmutual['rows']:,}")
        print(f"  min:        {nmutual['min']:,}")
        print(f"  max:        {nmutual['max']:,}")
        print(f"  sum:        {nmutual['sum']:,}")
        print(f"  bad rows:   {nmutual['bad_rows']:,}")

        if nmutual["bad_rows"] == 0:
            print("  PASS: CSV and values look valid")
        else:
            print("  FAIL: invalid rows found")
            failures += 1

    # ------------------------------------------------------------
    # n_mutual invariant
    # ------------------------------------------------------------
    print(f"\n[4] Checking n_mutual against {PAIRS}")

    pair_count = count_mutual_pairs(PAIRS)

    if pair_count is None or nmutual is None:
        failures += 1
    else:
        expected_mutual_sum = 2 * pair_count

        print(f"  mutual pairs:     {pair_count:,}")
        print(f"  2 × pairs:        {expected_mutual_sum:,}")
        print(f"  sum(n_mutual):    {nmutual['sum']:,}")

        if nmutual["sum"] == expected_mutual_sum:
            print("  PASS: n_mutual invariant holds")
        else:
            print("  FAIL: n_mutual sum does not match 2 × pairs")
            failures += 1

    # ------------------------------------------------------------
    # Final result
    # ------------------------------------------------------------
    print()

    if failures == 0:
        print("========================================")
        print("ALL VALIDATIONS PASSED")
        print("========================================")
        return 0

    print("========================================")
    print(f"VALIDATION FAILED ({failures} issue(s))")
    print("========================================")
    return 1


if __name__ == "__main__":
    sys.exit(main())
