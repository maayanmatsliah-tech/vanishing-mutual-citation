"""
Identify connected vs isolated papers (read-only on attributes).

connected = sources (papers that cite something) UNION cited (papers that get
cited by something). isolated = attributes papers that are neither.

Builds the `connected` id set into a scratch DB (data/_connected.duckdb) so the
later removal step can reuse it without re-scanning, and reports the counts.
Does NOT modify attributes.duckdb or edges.csv.
"""

import os
import time

import duckdb

SRC = "data/attributes.duckdb"
EDGES = "data/edges.csv"
CONN = "data/_connected.duckdb"


def main():
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    if os.path.exists(CONN):
        os.remove(CONN)
    t = time.perf_counter()
    con = duckdb.connect(CONN)
    con.execute("SET enable_progress_bar=false")
    con.execute("SET memory_limit='10GB'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute("SET preserve_insertion_order=false")

    print("1/3 sources (papers that cite something) ...", flush=True)
    con.execute(f"""
        CREATE TABLE sources AS
        SELECT DISTINCT CAST(ltrim(source, 'W') AS BIGINT) AS id
        FROM read_csv('{EDGES}', header=true, all_varchar=true)
    """)
    n_src = con.execute("SELECT count(*) FROM sources").fetchone()[0]
    print(f"     sources: {n_src:,}", flush=True)

    print("2/3 cited (distinct targets — heavy unnest+distinct) ...", flush=True)
    con.execute(f"""
        CREATE TABLE cited AS
        SELECT DISTINCT CAST(ltrim(unnest(string_split(targets, ';')), 'W') AS BIGINT) AS id
        FROM read_csv('{EDGES}', header=true, all_varchar=true)
    """)
    n_cited = con.execute("SELECT count(*) FROM cited").fetchone()[0]
    print(f"     distinct cited (incl out-of-set): {n_cited:,}", flush=True)

    print("3/3 connected = sources UNION cited ...", flush=True)
    con.execute(
        "CREATE TABLE connected AS SELECT id FROM sources UNION SELECT id FROM cited"
    )
    n_conn = con.execute("SELECT count(*) FROM connected").fetchone()[0]
    print(f"     connected ids (incl out-of-set): {n_conn:,}", flush=True)

    # Report isolated among the in-set attributes papers.
    con.execute(f"ATTACH '{SRC}' AS a (READ_ONLY)")
    total = con.execute("SELECT count(*) FROM a.attributes").fetchone()[0]
    isolated = con.execute("""
        SELECT count(*)
        FROM a.attributes p
        LEFT JOIN connected c ON c.id = CAST(ltrim(p.id, 'W') AS BIGINT)
        WHERE c.id IS NULL
    """).fetchone()[0]
    con.execute("DETACH a")
    con.close()

    kept = total - isolated
    print("\n=== RESULT ===")
    print(f"  total papers in attributes : {total:,}")
    print(f"  connected (keep)           : {kept:,} ({kept/total*100:.1f}%)")
    print(f"  ISOLATED (would remove)    : {isolated:,} ({isolated/total*100:.1f}%)")
    print(f"\n(connected id set persisted in {CONN} for the removal step)")
    print(f"done in {time.perf_counter()-t:.0f}s")


if __name__ == "__main__":
    main()
