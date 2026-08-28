"""
Script 1 of 2 — the heavy DuckDB pass.

Reads the CSVs directly (no persistent import) and produces a COMPACT per-paper
counts table that script 2 aggregates into the pooled per-year percentages.

For every paper that cites at least one other paper it emits:
  id        the paper (with its 'W' prefix restored)
  year      publication year
  diverse   True iff it cites papers spanning >= THRESHOLD distinct fields
            ('Unknown' is not counted as a field when EXCLUDE_UNKNOWN=1)
  n_cited   number of distinct papers it cites, EXCLUDING self-citations
  n_mutual  how many of those cited papers cite it back (each counted once)

A citation A->B is mutual iff B->A also exists. source == target is excluded
from both the citation set and the mutual set. Papers that cite nothing are
omitted (they contribute 0 to both sums in the pooled ratio, so they are
irrelevant to the graph).

Storage: on-disk DuckDB (db file + temp dir on disk); memory_limit caps RAM and
the rest spills to disk, so this does not eat your RAM.

Env
  ATTR/EDGES      CSV paths       (default data/attributes.csv, data/edges.csv)
  OUT             per-paper counts CSV (default data/mutual_counts_per_paper.csv)
  DB/DUCKDB_TMP   scratch db / spill dir (default data/_mutual.duckdb, data/_duckdb_tmp)
  MEM             memory_limit    (default 16GB)
  THRESHOLD       distinct fields = diverse   (default 3)
  EXCLUDE_UNKNOWN treat 'Unknown' as not-a-field (default 1)
"""

import os

import duckdb

ATTR = os.environ.get("ATTR", "data/attributes.csv")
EDGES = os.environ.get("EDGES", "data/edges.csv")
OUT = os.environ.get("OUT", "data/mutual_counts_per_paper.csv")
DB = os.environ.get("DB", "data/_mutual.duckdb")
DUCKDB_TMP = os.environ.get("DUCKDB_TMP", "data/_duckdb_tmp")
MEM = os.environ.get("MEM", "16GB")
THRESHOLD = int(os.environ.get("THRESHOLD", "3"))
EXCLUDE_UNKNOWN = os.environ.get("EXCLUDE_UNKNOWN", "1") == "1"


def main():
    os.makedirs(DUCKDB_TMP, exist_ok=True)
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)

    con = duckdb.connect(DB)
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute(f"SET temp_directory='{DUCKDB_TMP}'")
    con.execute("SET preserve_insertion_order=false")

    print("1/4 loading attributes ...", flush=True)
    con.execute(f"""
        CREATE TABLE attr AS
        SELECT TRY_CAST(ltrim(id, 'W') AS BIGINT) AS id,
               TRY_CAST(year AS INTEGER)          AS year,
               field
        FROM read_csv('{ATTR}', header=true, all_varchar=true, ignore_errors=true)
    """)

    print("2/4 building directed edges (self-citations excluded, deduped) ...", flush=True)
    con.execute(f"""
        CREATE TABLE edges AS
        SELECT DISTINCT s, t FROM (
            SELECT TRY_CAST(ltrim(source, 'W') AS BIGINT) AS s,
                   TRY_CAST(ltrim(unnest(string_split(targets, ';')), 'W') AS BIGINT) AS t
            FROM read_csv('{EDGES}', header=true, all_varchar=true, ignore_errors=true)
        )
        WHERE s IS NOT NULL AND t IS NOT NULL AND s <> t
    """)

    print("3/4 finding mutual edges (reverse citation exists) ...", flush=True)
    con.execute("""
        CREATE TABLE mutual AS
        SELECT e.s, e.t FROM edges e
        WHERE EXISTS (SELECT 1 FROM edges r WHERE r.s = e.t AND r.t = e.s)
    """)

    print("4/4 per-paper counts + diversity; writing counts ...", flush=True)
    field_filter = "AND a.field <> 'Unknown'" if EXCLUDE_UNKNOWN else ""
    con.execute(f"""
        COPY (
            WITH outc AS (SELECT s AS id, count(*) AS n_cited  FROM edges  GROUP BY s),
                 mutc AS (SELECT s AS id, count(*) AS n_mutual FROM mutual GROUP BY s),
                 divc AS (
                     SELECT e.s AS id, count(DISTINCT a.field) AS n_fields
                     FROM edges e JOIN attr a ON a.id = e.t
                     WHERE TRUE {field_filter}
                     GROUP BY e.s
                 )
            SELECT 'W' || o.id                          AS id,
                   p.year                               AS year,
                   (COALESCE(d.n_fields, 0) >= {THRESHOLD}) AS diverse,
                   o.n_cited                            AS n_cited,
                   COALESCE(m.n_mutual, 0)              AS n_mutual
            FROM outc o
            JOIN attr p     ON p.id = o.id
            LEFT JOIN mutc m ON m.id = o.id
            LEFT JOIN divc d ON d.id = o.id
        ) TO '{OUT}' (HEADER, DELIMITER ',')
    """)

    n_rows, n_div = con.execute(f"""
        SELECT count(*), count(*) FILTER (WHERE diverse)
        FROM read_csv('{OUT}', header=true)
    """).fetchone()
    print(f"\nwrote {n_rows:,} citing papers to {OUT} ({n_div:,} diverse)")
    con.close()


if __name__ == "__main__":
    main()
