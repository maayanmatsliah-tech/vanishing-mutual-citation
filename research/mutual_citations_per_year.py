"""
Count mutual citations per year using the edge list from the clean dataset.

A "mutual pair" between papers A and B exists when both edges
(A -> B) and (B -> A) are present in the edge list. Each unordered pair
{A, B} is counted once. Each pair is anchored to the later paper's
publication year, matching the convention used in the paper.

The edge list contains all outbound edges from each paper in the
attribute table (~750k papers, 1950-2024). A mutual pair can only be
detected when BOTH endpoints are in the attribute table (otherwise we
have no reverse edge to find).

Inputs:
  data/clean_dataset.duckdb (created by data/build_clean_dataset.py)

Outputs:
  data/mutual_citations_per_year.csv  (printable, viewable in GitHub)
  prints a summary table to stdout
"""

import duckdb
import csv
from pathlib import Path

DB = "data/clean_dataset.duckdb"
OUT_CSV = "data/mutual_citations_per_year.csv"

if not Path(DB).exists():
    raise SystemExit(
        f"{DB} does not exist. Run data/build_clean_dataset.py first."
    )

con = duckdb.connect(DB, read_only=True)

n_papers = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
n_edges = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
print(f"Loaded {n_papers:,} papers, {n_edges:,} edges from {DB}")

# Self-join the edge list against itself to find mutual pairs.
#   a.source = b.target AND a.target = b.source
# means "the reverse of edge a exists as some edge b".
# The a.source < a.target filter excludes self-cites (X = X is false)
# and uniquely orders each unordered pair {X, Y} to one row.
print("\nFinding mutual pairs (this can take a minute on millions of edges)...")
rows = con.execute("""
    WITH mutual_pairs AS (
        SELECT a.source AS p1, a.target AS p2
        FROM edges a
        JOIN edges b
          ON a.source = b.target
         AND a.target = b.source
        WHERE a.source < a.target
    )
    SELECT
        GREATEST(w1.year, w2.year) AS year,
        COUNT(*) AS mutual_pairs
    FROM mutual_pairs m
    JOIN papers w1 ON m.p1 = w1.id
    JOIN papers w2 ON m.p2 = w2.id
    GROUP BY GREATEST(w1.year, w2.year)
    ORDER BY year
""").fetchall()

# Also pull paper counts per year for normalization
papers_by_year = dict(con.execute(
    "SELECT year, COUNT(*) FROM papers GROUP BY year ORDER BY year"
).fetchall())

# Pretty print
print(f"\n{'year':<6}{'mutual pairs':>14}{'papers':>10}{'pairs / 1000':>14}")
print("-" * 44)
total_pairs = 0
out_rows = []
for year, pairs in rows:
    n_p = papers_by_year.get(year, 0)
    rate = pairs / n_p * 1000 if n_p else 0.0
    print(f"{year:<6}{pairs:>14,}{n_p:>10,}{rate:>13.2f}")
    out_rows.append([year, pairs, n_p, round(rate, 4)])
    total_pairs += pairs

print("-" * 44)
print(f"{'TOTAL':<6}{total_pairs:>14,}{sum(papers_by_year.values()):>10,}")

# Write CSV
with open(OUT_CSV, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["year", "mutual_pairs", "papers_in_year", "pairs_per_1000"])
    writer.writerows(out_rows)

print(f"\nSaved {OUT_CSV}")
