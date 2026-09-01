"""
Compute per-paper citation count (n_cited) and mutual citation count (n_mutual).

Outputs:
  data/_n_cited.csv   (id, n_cited): distinct non-self references per paper (n_cited > 0)
  data/_n_mutual.csv  (id, n_mutual): number of reciprocal pairs a paper participates in

Env:
  EDGES / PAIRS            Input paths (default: data/edges.csv, data/mutual_pairs.csv)
  OUT_NCITED / OUT_NMUTUAL Output paths (default: data/_n_cited.csv, data/_n_mutual.csv)
  MEM                      DuckDB memory limit (default: 10GB)
  DEDUPE                   1 = distinct targets (default), 0 = raw count
  STEPS                    'both' (default), 'ncited', or 'nmutual'
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
STEPS = os.environ.get("STEPS", "both")
if STEPS not in ("both", "ncited", "nmutual"):
    raise SystemExit(f"STEPS must be one of both/ncited/nmutual, got {STEPS!r}")


def main():
    os.makedirs(DUCKDB_TMP, exist_ok=True)
    os.makedirs(os.path.dirname(OUT_NCITED) or ".", exist_ok=True)

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute(f"SET temp_directory='{DUCKDB_TMP}'")
    con.execute("SET preserve_insertion_order=false")

    if STEPS in ("both", "ncited"):
        build_n_cited(con)
    else:
        print(
            f"skipping n_cited (STEPS={STEPS}) -- {OUT_NCITED} left untouched",
            flush=True,
        )

    if STEPS in ("both", "nmutual"):
        build_n_mutual(con)
    else:
        print(
            f"skipping n_mutual (STEPS={STEPS}) -- {OUT_NMUTUAL} left untouched",
            flush=True,
        )

    if STEPS in ("both", "ncited"):
        n = con.execute(
            f"SELECT count(*) FROM read_csv('{OUT_NCITED}', header=true)"
        ).fetchone()[0]
        print(f"\nwrote {n:,} rows to {OUT_NCITED}")
    if STEPS in ("both", "nmutual"):
        n = con.execute(
            f"SELECT count(*) FROM read_csv('{OUT_NMUTUAL}', header=true)"
        ).fetchone()[0]
        print(f"wrote {n:,} rows to {OUT_NMUTUAL}")
    con.close()
    print("\nNEXT STEP: validate with data_validation/validate_n_cited_n_mutual.py")


def build_n_cited(con):
    print(
        f"computing n_cited per source (dedupe={DEDUPE}) -> {OUT_NCITED} ...",
        flush=True,
    )
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
    # CONFIRMED via validation against the real data/_n_cited.csv: the original
    # script excluded n_cited=0 rows (papers whose entire target list was
    # self-citations / exact duplicates, leaving nothing after dedup). Without
    # this filter, sums matched exactly but row count was off by precisely
    # 108,151 -- the count of n_cited=0 rows. Confirms this filter, not a
    # different n_cited definition, was the source of the discrepancy.
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


def build_n_mutual(con):
    print(f"computing n_mutual per paper from {PAIRS} -> {OUT_NMUTUAL} ...", flush=True)
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


if __name__ == "__main__":
    main()
