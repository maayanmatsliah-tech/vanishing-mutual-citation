#!/usr/bin/env python3
"""
Number of papers published per year.

Uses:
  data/attributes.duckdb

Counts every paper in the attributes table for each publication year.
No filtering based on citations or reference lists.

Output:
  figures/csvs/papers_per_year.csv

Env:
  ATTR  default data/attributes.duckdb
  OUT   default figures/csvs/papers_per_year.csv
  START default 1975
  END   default 2023

The attributes database is opened read-only and is never modified.
"""

import os

import duckdb

ATTR = os.environ.get("ATTR", "data/attributes.duckdb")
OUT = os.environ.get(
    "OUT",
    "figures/csvs/papers_per_year.csv",
)
START = int(os.environ.get("START", "1975"))
END = int(os.environ.get("END", "2023"))


def compute():
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)

    con = duckdb.connect()

    try:
        con.execute("SET enable_progress_bar=false")

        con.execute(f"ATTACH '{ATTR}' AS a (READ_ONLY)")

        print(
            f"Counting papers published from {START} through {END}...",
            flush=True,
        )

        rows = con.execute(f"""
            SELECT
                year,
                COUNT(*) AS n_papers
            FROM a.attributes
            WHERE year BETWEEN {START} AND {END}
            GROUP BY year
            ORDER BY year
            """).fetchall()

    finally:
        con.close()

    return rows


def write_output(rows):
    import csv

    with open(OUT, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["year", "n_papers"])

        for year, n_papers in rows:
            writer.writerow([year, n_papers])

    print(f"wrote {OUT}")


def main():
    rows = compute()

    print()
    print(f"{'year':>6} {'n_papers':>12}")

    for year, n_papers in rows:
        print(f"{year:>6} {n_papers:>12,}")

    if rows:
        first_year, first_n = rows[0]
        last_year, last_n = rows[-1]

        growth = 100 * (last_n - first_n) / first_n

        print(f"\n{first_year} -> {last_year}:")
        print(f"  papers: {first_n:,} -> {last_n:,}")
        print(f"  growth: {growth:.1f}%")

    write_output(rows)


if __name__ == "__main__":
    main()
