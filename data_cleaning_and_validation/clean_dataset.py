"""
Produce a CLEAN copy of the dataset by dropping non-paper records.

Root cause (see docs / memory): the OpenAlex snapshot was ingested with NO
work-type filter, so ~17.7M non-paper records (datasets, author-profile "other"
records, paratext, peer-review) came in -- 94% of them dated 2024/2025. They
all lack a topic, so they carry field='Unknown'. We can't filter by `type`
(it was never stored), but `field='Unknown'` cleanly identifies this junk.

Outputs (originals are left untouched as backups):
  data/attributes_clean.duckdb   attributes minus field='Unknown'
  data/edges_clean.csv           edges whose SOURCE survives (targets kept intact,
                                 so the existing diversity_count stays consistent)
  data/mutual_pairs_clean.csv    mutual pairs rebuilt on the clean graph; both
                                 endpoints are guaranteed surviving papers because
                                 the source-filter keeps only targets that are
                                 themselves clean sources.

Env: ATTR_IN, ATTR_OUT, EDGES_IN, EDGES_OUT, PAIRS_OUT, MEM (default 12GB).
"""

import os
import time

import duckdb

ATTR_IN = os.environ.get("ATTR_IN", "data/attributes.duckdb")
ATTR_OUT = os.environ.get("ATTR_OUT", "data/attributes_clean.duckdb")
EDGES_IN = os.environ.get("EDGES_IN", "data/edges.csv")
EDGES_OUT = os.environ.get("EDGES_OUT", "data/edges_clean.csv")
PAIRS_OUT = os.environ.get("PAIRS_OUT", "data/mutual_pairs_clean.csv")
MUT_DB = os.environ.get("MUT_DB", "data/_mutual_clean.duckdb")
MEM = os.environ.get("MEM", "12GB")


def main():
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    for f in (ATTR_OUT, MUT_DB):
        if os.path.exists(f):
            os.remove(f)
    t0 = time.perf_counter()

    con = duckdb.connect(ATTR_OUT)
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"ATTACH '{ATTR_IN}' AS orig (READ_ONLY)")

    # 1. clean attributes: keep only rows with a real field (drops Unknown + NULL)
    print("1/4 building clean attributes (dropping field='Unknown') ...", flush=True)
    con.execute("CREATE TABLE attributes AS SELECT * FROM orig.attributes WHERE field <> 'Unknown'")
    n_orig = con.execute("SELECT count(*) FROM orig.attributes").fetchone()[0]
    n_keep = con.execute("SELECT count(*) FROM attributes").fetchone()[0]
    print(f"    attributes: {n_orig:,} -> {n_keep:,}  (dropped {n_orig-n_keep:,})", flush=True)

    # surviving ids as integers, for the edge filter
    con.execute("CREATE TEMP TABLE surv AS SELECT CAST(ltrim(id,'W') AS BIGINT) AS id FROM attributes")

    # 2. clean edges: keep rows whose SOURCE survives (targets left intact)
    print("2/4 writing clean edges (source must survive) ...", flush=True)
    con.execute(f"""
        COPY (
            SELECT source, targets
            FROM read_csv('{EDGES_IN}', header=true, all_varchar=true)
            WHERE CAST(ltrim(source,'W') AS BIGINT) IN (SELECT id FROM surv)
        ) TO '{EDGES_OUT}' (HEADER, DELIMITER ',')
    """)
    n_edges = con.execute(
        f"SELECT count(*) FROM read_csv('{EDGES_OUT}', header=true, all_varchar=true)"
    ).fetchone()[0]
    print(f"    edges_clean rows: {n_edges:,}", flush=True)
    con.close()

    # 3/4. rebuild mutual pairs on the clean graph (same method as find_mutual_pairs.py)
    print("3/4 building sources set from clean edges ...", flush=True)
    mcon = duckdb.connect(MUT_DB)
    mcon.execute("SET enable_progress_bar=false")
    mcon.execute(f"SET memory_limit='{MEM}'")
    mcon.execute("SET temp_directory='data/_duckdb_tmp'")
    mcon.execute("SET preserve_insertion_order=false")
    mcon.execute(f"""
        CREATE TABLE sources AS
        SELECT DISTINCT CAST(ltrim(source,'W') AS BIGINT) AS id
        FROM read_csv('{EDGES_OUT}', header=true, all_varchar=true)
    """)
    print("4/4 unnest -> source-filter -> canonical group -> write mutual pairs ...", flush=True)
    mcon.execute(f"""
        COPY (
            WITH de AS (
                SELECT CAST(ltrim(source,'W') AS BIGINT) AS s,
                       CAST(ltrim(unnest(string_split(targets,';')),'W') AS BIGINT) AS t
                FROM read_csv('{EDGES_OUT}', header=true, all_varchar=true)
            ),
            filtered AS (
                SELECT s, t FROM de
                WHERE s <> t AND t IN (SELECT id FROM sources)
            ),
            pairs AS (
                SELECT least(s,t) AS a, greatest(s,t) AS b,
                       bool_or(s < t) AS has_fwd,
                       bool_or(s > t) AS has_bwd
                FROM filtered GROUP BY 1, 2
            )
            SELECT 'W' || a AS paper_a, 'W' || b AS paper_b
            FROM pairs WHERE has_fwd AND has_bwd
        ) TO '{PAIRS_OUT}' (HEADER, DELIMITER ',')
    """)
    mcon.close()
    if os.path.exists(MUT_DB):
        os.remove(MUT_DB)

    n_pairs = duckdb.connect().execute(
        f"SELECT count(*) FROM read_csv('{PAIRS_OUT}', header=true, all_varchar=true)"
    ).fetchone()[0]
    print(f"\nDONE in {time.perf_counter()-t0:.0f}s", flush=True)
    print(f"  {ATTR_OUT}: {n_keep:,} papers", flush=True)
    print(f"  {EDGES_OUT}: {n_edges:,} rows", flush=True)
    print(f"  {PAIRS_OUT}: {n_pairs:,} mutual pairs (was 1,365,303 on dirty graph)", flush=True)


if __name__ == "__main__":
    main()
