"""
Find mutual-citation pairs -> data/mutual_pairs.csv (one row per mutual pair).

Method (exactly as specified):
  - A "source" = a paper that cites something (appears in edges.source).
  - source->source filter (temporary, for this calc only): keep a directed edge
    A->B only if B is also a source; an edge to a non-citing paper can never be
    reciprocated, so dropping it is lossless and shrinks the work.
  - For each directed citation, write the canonical pair (smaller id, larger id)
    plus a direction: edge small->large = Forward, edge large->small = Backward.
  - Group by pair. A pair is MUTUAL iff it has BOTH a Forward and a Backward edge.
  - Output one line per mutual pair: paper_a,paper_b (W-prefixed, a < b numerically).

Integer keys (strip W) + the source-filter keep this tractable; the heavy step
is the GROUP BY over the filtered edges, which spills to disk under the mem cap.

Env: EDGES, OUT, DB (scratch), MEM (default 12GB).
"""

import os
import time

import duckdb

EDGES = os.environ.get("EDGES", "data/edges.csv")
OUT = os.environ.get("OUT", "data/mutual_pairs.csv")
DB = os.environ.get("DB", "data/_mutual.duckdb")
MEM = os.environ.get("MEM", "12GB")


def main():
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)
    t = time.perf_counter()
    con = duckdb.connect(DB)
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute("SET preserve_insertion_order=false")

    print("1/2 building sources set (papers that cite something) ...", flush=True)
    con.execute(f"""
        CREATE TABLE sources AS
        SELECT DISTINCT CAST(ltrim(source, 'W') AS BIGINT) AS id
        FROM read_csv('{EDGES}', header=true, all_varchar=true)
    """)

    print("2/2 unnest -> source-filter -> canonical group -> write mutual pairs ...", flush=True)
    con.execute(f"""
        COPY (
            WITH de AS (
                SELECT CAST(ltrim(source, 'W') AS BIGINT) AS s,
                       CAST(ltrim(unnest(string_split(targets, ';')), 'W') AS BIGINT) AS t
                FROM read_csv('{EDGES}', header=true, all_varchar=true)
            ),
            filtered AS (
                SELECT s, t FROM de
                WHERE s <> t AND t IN (SELECT id FROM sources)   -- src is always a source
            ),
            pairs AS (
                SELECT least(s, t) AS a, greatest(s, t) AS b,
                       bool_or(s < t) AS has_fwd,   -- a -> b exists
                       bool_or(s > t) AS has_bwd    -- b -> a exists
                FROM filtered
                GROUP BY 1, 2
            )
            SELECT 'W' || a AS paper_a, 'W' || b AS paper_b
            FROM pairs
            WHERE has_fwd AND has_bwd
        ) TO '{OUT}' (HEADER, DELIMITER ',')
    """)
    con.close()

    # count the output lines (minus header)
    n = duckdb.connect().execute(
        f"SELECT count(*) FROM read_csv('{OUT}', header=true, all_varchar=true)"
    ).fetchone()[0]
    print(f"\nwrote {n:,} mutual pairs to {OUT}")
    print(f"done in {time.perf_counter()-t:.0f}s")


if __name__ == "__main__":
    main()
