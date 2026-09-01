"""
Build a NEW attributes DB with the left-boundary-repaired diversity_count swapped
in (from recompute_diversity_backfilled.py). Non-destructive: the original
attributes.duckdb is left untouched.

  SRC      original attributes db   (default data/attributes.duckdb)
  COUNTS   repaired per-paper counts (default data/_div_backfilled_counts.csv)
  NEW      output db                (default data/attributes_backfilled.duckdb)
"""

import os, time
import duckdb

SRC = os.environ.get("SRC", "data/attributes.duckdb")
COUNTS = os.environ.get("COUNTS", "data/_div_backfilled_counts.csv")
NEW = os.environ.get("NEW", "data/attributes_backfilled.duckdb")
MEM = os.environ.get("MEM", "12GB")


def main():
    t0 = time.perf_counter()
    if os.path.exists(NEW):
        os.remove(NEW)
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    con = duckdb.connect(NEW)
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"ATTACH '{SRC}' AS src (READ_ONLY)")
    print("rewriting attributes with backfilled diversity_count ...", flush=True)
    con.execute(f"""
        CREATE TABLE attributes AS
        SELECT a.id, a.year, a.field, a.author,
               COALESCE(d.diversity_count, 0) AS diversity_count
        FROM src.attributes a
        LEFT JOIN read_csv('{COUNTS}', header=true,
                  columns={{'id':'BIGINT','diversity_count':'INTEGER'}}) d
          ON d.id = CAST(ltrim(a.id,'W') AS BIGINT)
    """)
    con.execute("DETACH src")
    n = con.execute("SELECT count(*) FROM attributes").fetchone()[0]
    av = con.execute("SELECT avg(diversity_count) FROM attributes").fetchone()[0]
    mx = con.execute("SELECT max(diversity_count) FROM attributes").fetchone()[0]
    print(
        f"rows={n:,}  mean_diversity={av:.3f}  max={mx}  ({time.perf_counter()-t0:.0f}s)"
    )
    con.close()


if __name__ == "__main__":
    main()
