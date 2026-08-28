"""
Stages 2-4 of the plan: classify diverse, count mutual citations, plot.

Inputs (CSV or Parquet; DuckDB reads either):
  attributes : columns id, year, field  (extra columns ignored)
  edges      : columns source, targets (";"-joined target ids, one row per source)

Steps:
  1. diverse: a paper is `diverse` if the DISTINCT fields of the papers it cites
     (targets present in attributes) is >= 3. Self-citations (source==target)
     are excluded. Papers citing <=2 fields (or nothing in-set) are non-diverse.
  2. mutual: a pair {A,B} is mutual iff A->B AND B->A exist (A != B). Each pair
     counted once (collapse to unordered pair, keep pairs seen in both directions).
     Per paper, n_mut = number of mutual pairs it belongs to.
  3. aggregate per (year, diverse): mean mutual citations per paper, 1975-2025.
  4. plot two lines (diverse vs non-diverse) + write per-year CSV.

Env:
  ATTR       attributes path (default data/attributes.csv)
  EDGES      edges path       (default data/edges.csv)
  OUT_PNG    chart path       (default outputs/mutual_by_diversity.png)
  OUT_CSV    per-year means   (default outputs/mutual_by_diversity_per_year.csv)
  ATTR_OUT   attributes + diverse column (default: none; set a path to write it)
"""

import os
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ATTR = os.environ.get("ATTR", "data/attributes.csv")
EDGES = os.environ.get("EDGES", "data/edges.csv")
OUT_PNG = os.environ.get("OUT_PNG", "outputs/mutual_by_diversity.png")
OUT_CSV = os.environ.get("OUT_CSV", "outputs/mutual_by_diversity_per_year.csv")
ATTR_OUT = os.environ.get("ATTR_OUT", "")

con = duckdb.connect()  # in-memory

print(f"Loading attributes from {ATTR} and edges from {EDGES} ...")
con.execute(f"""
    CREATE TABLE attr AS
    SELECT CAST(id AS VARCHAR) AS id, CAST(year AS INTEGER) AS year,
           CAST(field AS VARCHAR) AS field
    FROM read_csv_auto('{ATTR}')
""")
con.execute(f"""
    CREATE TABLE edges AS
    SELECT CAST(source AS VARCHAR) AS source,
           UNNEST(string_split(CAST(targets AS VARCHAR), ';')) AS target
    FROM read_csv_auto('{EDGES}')
""")
n_attr = con.execute("SELECT COUNT(*) FROM attr").fetchone()[0]
n_edge = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
print(f"  {n_attr:,} papers, {n_edge:,} edges")

# ---- Stage 2: diverse ----
print("Classifying diverse (distinct cited fields >= 3, self-citations excluded)...")
con.execute("""
    CREATE TABLE attr_div AS
    WITH div AS (
        SELECT e.source AS id, COUNT(DISTINCT a.field) AS n_fields
        FROM edges e
        JOIN attr a ON a.id = e.target
        WHERE e.source <> e.target
        GROUP BY e.source
    )
    SELECT t.id, t.year, t.field,
           COALESCE(d.n_fields, 0) >= 3 AS diverse
    FROM attr t
    LEFT JOIN div d ON d.id = t.id
""")
dist = con.execute(
    "SELECT diverse, COUNT(*) FROM attr_div GROUP BY diverse ORDER BY diverse"
).fetchall()
print(f"  diversity split: {dict(dist)}")

# ---- Stage 3: mutual citations ----
print("Finding mutual pairs (each pair once, no self-citations)...")
con.execute("""
    CREATE TABLE mutual AS
    WITH de AS (SELECT DISTINCT source, target FROM edges WHERE source <> target)
    SELECT least(source, target) AS a, greatest(source, target) AS b
    FROM de
    GROUP BY 1, 2
    HAVING COUNT(*) = 2
""")
n_mutual = con.execute("SELECT COUNT(*) FROM mutual").fetchone()[0]
print(f"  {n_mutual:,} mutual pairs")
con.execute("""
    CREATE TABLE mut_count AS
    SELECT id, COUNT(*) AS n_mut FROM (
        SELECT a AS id FROM mutual
        UNION ALL
        SELECT b AS id FROM mutual
    ) GROUP BY id
""")

# ---- Stage 4: aggregate per (year, diverse) ----
agg = con.execute("""
    SELECT year, diverse,
           AVG(n_mut) AS mean_mutual,
           COUNT(*)   AS n_papers
    FROM (
        SELECT ad.year, ad.diverse, COALESCE(mc.n_mut, 0) AS n_mut
        FROM attr_div ad
        LEFT JOIN mut_count mc ON mc.id = ad.id
        WHERE ad.year BETWEEN 1975 AND 2025
    )
    GROUP BY year, diverse
    ORDER BY year, diverse
""").fetchall()

# write per-year CSV
Path(OUT_CSV).parent.mkdir(parents=True, exist_ok=True)
import csv as _csv
with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
    w = _csv.writer(f)
    w.writerow(["year", "diverse", "mean_mutual", "n_papers"])
    w.writerows(agg)
print(f"Wrote {OUT_CSV}")

# optionally write attributes + diverse
if ATTR_OUT:
    con.execute(
        f"COPY (SELECT * FROM attr_div ORDER BY year, id) TO '{ATTR_OUT}' (HEADER, DELIMITER ',')"
    )
    print(f"Wrote {ATTR_OUT}")

# ---- plot ----
d = {(y, bool(div)): (mm, n) for y, div, mm, n in agg}
years = sorted({y for (y, _) in d})
MIN_N = int(os.environ.get("MIN_N", "30"))
years = [y for y in years
         if d.get((y, True), (0, 0))[1] >= MIN_N and d.get((y, False), (0, 0))[1] >= MIN_N]
if not years:
    print(f"\nNOT ENOUGH DATA to plot: no year has >= {MIN_N} papers in BOTH "
          f"groups. This happens on random subsamples — diversity and mutual "
          f"citations are whole-graph properties (need the cited papers in-set). "
          f"See {OUT_CSV} for the raw per-year counts.")
    raise SystemExit(0)

div_y = [d[(y, True)][0] for y in years]
non_y = [d[(y, False)][0] for y in years]

fig, ax = plt.subplots(figsize=(13, 7))
ax.plot(years, non_y, "o-", color="steelblue", linewidth=2.5, markersize=6,
        label="Non-diverse (cites <=2 fields)")
ax.plot(years, div_y, "x-", color="coral", linewidth=2.5, markersize=7,
        label="Diverse (cites 3+ fields)")
ax.set_xlabel("Publication year")
ax.set_ylabel("Mean mutual citations per paper")
ax.set_title("Mean mutual citations per paper by year, diverse vs non-diverse\n"
             f"({years[0]}–{years[-1]}, >= {MIN_N} papers/group/year)")
ax.set_ylim(bottom=0)
ax.grid(True, alpha=0.3)
ax.legend(loc="upper left", fontsize=11)
plt.tight_layout()
Path(OUT_PNG).parent.mkdir(parents=True, exist_ok=True)
plt.savefig(OUT_PNG, dpi=150)
print(f"Saved {OUT_PNG}")
