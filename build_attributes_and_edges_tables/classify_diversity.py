"""
Add a `diverse` column to the papers attribute table.

For each paper, count the number of DISTINCT fields it cites across
ALL its outbound references. Classify:

  diverse     = TRUE   if the paper cites work from 3 or more distinct fields
  diverse     = FALSE  if the paper cites work from 2 or fewer distinct fields
                       (also FALSE if no cited papers have known field info)

Field lookup uses a unified source — papers in our 10k-per-year
attribute table contribute their field directly, and cited papers
outside the sample have their fields looked up by
data/backfill_cited_fields.py. Run that script before this one for
accurate diversity. Without the backfill, diversity is computed only
on the small intersection of cited papers that happen to be in the
sample, and will systematically undercount.

Inputs:
  data/clean_dataset.duckdb (with both `papers` and ideally
                             `cited_paper_fields` tables present)

Outputs:
  data/clean_dataset.duckdb  -- papers table updated in place with new column
  data/papers.parquet        -- re-exported with the new column
  prints diversity distribution and coverage diagnostic
"""

import duckdb
from pathlib import Path

DB = "data/clean_dataset.duckdb"
PAPERS_PARQUET = "data/papers.parquet"

if not Path(DB).exists():
    raise SystemExit(
        f"{DB} does not exist. Run data/build_clean_dataset.py first."
    )

con = duckdb.connect(DB)

n_papers = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
n_edges = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
print(f"Loaded {n_papers:,} papers, {n_edges:,} edges from {DB}")

# Detect whether cited_paper_fields backfill has run
has_backfill = con.execute("""
    SELECT COUNT(*) FROM information_schema.tables
    WHERE table_name = 'cited_paper_fields'
""").fetchone()[0] > 0

if has_backfill:
    n_backfilled = con.execute("SELECT COUNT(*) FROM cited_paper_fields").fetchone()[0]
    print(f"  cited_paper_fields backfill found: {n_backfilled:,} rows")
else:
    print("  WARNING: cited_paper_fields table not found.")
    print("  Run data/backfill_cited_fields.py first for accurate diversity.")
    print("  Falling back to in-set citations only (will undercount).\n")

# Build a unified field-lookup CTE. The papers table has the field for
# its own rows; cited_paper_fields covers the rest. UNION ALL combined
# with COALESCE is the cleanest expression.
print("\nComputing edge coverage diagnostic...")
if has_backfill:
    coverage_q = """
        SELECT COUNT(*) FROM edges e
        LEFT JOIN papers p ON e.target = p.id
        LEFT JOIN cited_paper_fields f ON e.target = f.id
        WHERE p.field IS NOT NULL OR f.field IS NOT NULL
    """
else:
    coverage_q = """
        SELECT COUNT(*) FROM edges e
        JOIN papers p ON e.target = p.id
        WHERE p.field IS NOT NULL
    """
covered = con.execute(coverage_q).fetchone()[0]
print(f"  edges with target field known: {covered:,} of {n_edges:,} "
      f"({covered/n_edges*100:.1f}%)")

# Rebuild the papers table with the new column derived in one CTE.
# unified_fields gives one row per cited paper with a known field,
# pulling from both papers and cited_paper_fields. Then the diversity
# count is COUNT(DISTINCT field) per source.
print("\nComputing distinct-field-cited per paper and rebuilding papers table...")

if has_backfill:
    con.execute("""
        CREATE OR REPLACE TABLE papers_new AS
        WITH unified_fields AS (
            SELECT id, field FROM papers WHERE field IS NOT NULL
            UNION ALL
            SELECT id, field FROM cited_paper_fields WHERE field IS NOT NULL
        ),
        diversity AS (
            SELECT
                e.source AS pid,
                COUNT(DISTINCT uf.field) AS n_fields_cited
            FROM edges e
            JOIN unified_fields uf ON e.target = uf.id
            GROUP BY e.source
        )
        SELECT
            p.id,
            p.year,
            p.field,
            p.title,
            COALESCE(d.n_fields_cited, 0) >= 3 AS diverse
        FROM papers p
        LEFT JOIN diversity d ON p.id = d.pid
    """)
else:
    con.execute("""
        CREATE OR REPLACE TABLE papers_new AS
        WITH diversity AS (
            SELECT
                e.source AS pid,
                COUNT(DISTINCT p_cited.field) AS n_fields_cited
            FROM edges e
            JOIN papers p_cited ON e.target = p_cited.id
            WHERE p_cited.field IS NOT NULL
            GROUP BY e.source
        )
        SELECT
            p.id,
            p.year,
            p.field,
            p.title,
            COALESCE(d.n_fields_cited, 0) >= 3 AS diverse
        FROM papers p
        LEFT JOIN diversity d ON p.id = d.pid
    """)

con.execute("DROP TABLE papers")
con.execute("ALTER TABLE papers_new RENAME TO papers")
con.execute("CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year)")

# Summary
print("\nOverall diversity distribution:")
totals = con.execute("""
    SELECT diverse, COUNT(*) FROM papers GROUP BY diverse ORDER BY diverse DESC
""").fetchall()
total = sum(c for _, c in totals)
for d, c in totals:
    label = "diverse (cites 3+ fields)" if d else "not diverse (cites <=2 fields or 0 in-set refs)"
    print(f"  {label:<55} {c:>9,}  ({c/total*100:>5.1f}%)")

print("\nDiversity by year (sample of every 10th year):")
rows = con.execute("""
    SELECT year,
           COUNT(*) AS n,
           SUM(CASE WHEN diverse THEN 1 ELSE 0 END) AS n_diverse
    FROM papers
    WHERE year IS NOT NULL
    GROUP BY year ORDER BY year
""").fetchall()
print(f"  {'year':<6}{'n papers':>10}{'diverse':>10}{'pct diverse':>14}")
for y, n, nd in rows:
    if y % 10 == 0 or y >= 2020:
        print(f"  {y:<6}{n:>10,}{nd:>10,}{nd/n*100:>13.1f}%")

# Re-export to parquet
print(f"\nRe-exporting papers table with the new column to {PAPERS_PARQUET}...")
con.execute(
    f"COPY (SELECT * FROM papers ORDER BY year, id) TO '{PAPERS_PARQUET}' "
    "(FORMAT PARQUET, COMPRESSION ZSTD)"
)

size_mb = Path(PAPERS_PARQUET).stat().st_size / 1e6
print(f"  papers.parquet: {size_mb:.1f} MB")
print("Done.")
