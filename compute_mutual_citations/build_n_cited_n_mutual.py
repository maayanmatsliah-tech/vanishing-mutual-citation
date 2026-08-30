"""
14. Build per-paper n_cited / n_mutual counts, feeding
    refcount_decile_value_binned.py.

Reads:  data/edges.csv, data/mutual_pairs.csv
Writes: data/_n_cited.csv   (id, n_cited)
        data/_n_mutual.csv  (id, n_mutual)

Definitions:
  n_cited   number of DISTINCT papers a source cites, excluding self-citation.
            Rows where n_cited = 0 are dropped.
  n_mutual  number of mutual pairs a paper belongs to (each pair contributes
            +1 to BOTH of its papers; a paper absent from the output has 0).

id format: bare integer, 'W' prefix stripped.

Env:
  EDGES         default data/edges.csv
  PAIRS         default data/mutual_pairs.csv
  OUT_NCITED    default data/_n_cited.csv
  OUT_NMUTUAL   default data/_n_mutual.csv
  MEM           default 10GB
  DEDUPE        default 1 (distinct targets)
"""

import os

import duckdb

EDGES = os.environ.get("EDGES", "data/edges.csv")
PAIRS = os.environ.get("PAIRS", "data/mutual_pairs.csv")
OUT_NCITED = os.environ.get("OUT_NCITED", "data/_n_cited.csv")
OUT_NMUTUAL = os.environ.get("OUT_NMUTUAL", "data/_n_mutual.csv")
MEM = os.environ.get("MEM", "10GB")
DUCKDB_TMP = os.environ.get("DUCKDB_TMP", "data/_duckdb_tmp")
DEDUPE = os.environ.get("DEDUPE", "1") == "1"


def main():
    os.makedirs(DUCKDB_TMP, exist_ok=True)
    os.makedirs(os.path.dirname(OUT_NCITED) or ".", exist_ok=True)

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute(f"SET temp_directory='{DUCKDB_TMP}'")
    con.execute("SET preserve_insertion_order=false")

    print(f"1/2 computing n_cited per source (dedupe={DEDUPE}) -> {OUT_NCITED} ...",
          flush=True)
    if DEDUPE:
        n_cited_expr = """
            len(list_distinct(string_split(targets, ';')))
              - CASE WHEN list_contains(list_distinct(string_split(targets, ';')), source)
                     THEN 1 ELSE 0 END
        """
    else:
        n_cited_expr = """
            len(string_split(targets, ';'))
              - CASE WHEN list_contains(string_split(targets, ';'), source)
                     THEN 1 ELSE 0 END
        """
    # n_cited=0 rows (papers whose entire target list was self-citations or
    # exact duplicates) are excluded, matching downstream consumers which
    # filter to n_cited >= 3 anyway.
    con.execute(f"""
        COPY (
            SELECT id, n_cited FROM (
                SELECT CAST(ltrim(source, 'W') AS BIGINT) AS id,
                       ({n_cited_expr})                    AS n_cited
                FROM read_csv('{EDGES}', header=true, all_varchar=true, ignore_errors=true)
            )
            WHERE n_cited > 0
        ) TO '{OUT_NCITED}' (HEADER, DELIMITER ',')
    """)

    print(f"2/2 computing n_mutual per paper -> {OUT_NMUTUAL} ...", flush=True)
    con.execute(f"""
        COPY (
            SELECT id, count(*) AS n_mutual FROM (
                SELECT CAST(ltrim(paper_a, 'W') AS BIGINT) AS id
                FROM read_csv('{PAIRS}', header=true, all_varchar=true)
                UNION ALL
                SELECT CAST(ltrim(paper_b, 'W') AS BIGINT) AS id
                FROM read_csv('{PAIRS}', header=true, all_varchar=true)
            )
            GROUP BY id
        ) TO '{OUT_NMUTUAL}' (HEADER, DELIMITER ',')
    """)

    n1 = con.execute(f"SELECT count(*) FROM read_csv('{OUT_NCITED}', header=true)").fetchone()[0]
    n2 = con.execute(f"SELECT count(*) FROM read_csv('{OUT_NMUTUAL}', header=true)").fetchone()[0]
    con.close()
    print(f"\nwrote {n1:,} rows to {OUT_NCITED}")
    print(f"wrote {n2:,} rows to {OUT_NMUTUAL}")


if __name__ == "__main__":
    main()