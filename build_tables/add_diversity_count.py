"""
Add diversity_count to the attributes table via streaming bitset aggregation.

diversity_count: Number of distinct non-Unknown fields a paper cites (excluding self-citations).

Outputs:
  data/_div_counts.csv       Intermediate per-paper diversity counts
  data/attributes_new.duckdb Attributes DuckDB with diversity_count column added

Env:
  SRC     Source attributes DuckDB (default: data/attributes.duckdb)
  EDGES   Edges CSV (default: data/edges.csv)
  COUNTS  Intermediate counts CSV path (default: data/_div_counts.csv)
  NEW     New attributes DuckDB path (default: data/attributes_new.duckdb)
"""

import csv
import os
import sys
import time

import duckdb
import numpy as np

SRC = os.environ.get("SRC", "data/attributes.duckdb")
EDGES = os.environ.get("EDGES", "data/edges.csv")
COUNTS = os.environ.get("COUNTS", "data/_div_counts.csv")
NEW = os.environ.get("NEW", "data/attributes_new.duckdb")
EXPECT = int(os.environ.get("EXPECT", "148726765"))
csv.field_size_limit(sys.maxsize)


def phase1_lookup():
    print("phase 1: loading id->field-code lookup into RAM ...", flush=True)
    con = duckdb.connect(SRC, read_only=True)
    con.execute("SET enable_progress_bar=false")
    con.execute("SET memory_limit='10GB'")
    res = con.execute("""
        WITH fcode AS (
            SELECT field, ROW_NUMBER() OVER (ORDER BY field) - 1 AS code
            FROM (SELECT DISTINCT field FROM attributes WHERE field <> 'Unknown')
        )
        SELECT CAST(ltrim(a.id, 'W') AS BIGINT)        AS id,
               CAST(COALESCE(f.code, -1) AS SMALLINT)  AS code
        FROM attributes a LEFT JOIN fcode f ON f.field = a.field
    """).fetchnumpy()
    con.close()
    ids = res["id"]
    codes = res["code"].astype(np.int16)
    order = np.argsort(ids, kind="stable")
    ids = ids[order]
    codes = codes[order]
    print(
        f"  loaded {ids.shape[0]:,} papers; "
        f"{int((codes >= 0).sum()):,} have a known (non-Unknown) field",
        flush=True,
    )
    return ids, codes


def phase2_stream(ids, codes):
    print("phase 2: streaming edges.csv (one pass) ...", flush=True)
    N = ids.shape[0]
    one = np.int64(1)
    n_src = 0
    with open(EDGES, newline="") as f, open(COUNTS, "w", newline="") as out:
        r = csv.reader(f)
        w = csv.writer(out)
        next(r)  # header
        w.writerow(["id", "diversity_count"])
        for row in r:
            src = int(row[0][1:])
            t = np.fromiter((int(x[1:]) for x in row[1].split(";")), dtype=np.int64)
            idx = np.searchsorted(ids, t)
            np.clip(idx, 0, N - 1, out=idx)
            present = ids[idx] == t
            cnt = 0
            if present.any():
                pt = t[present]
                pc = codes[idx[present]]
                ck = pc[(pc >= 0) & (pt != src)]  # non-Unknown, non-self
                if ck.size:
                    mask = int(np.bitwise_or.reduce(one << ck.astype(np.int64)))
                    cnt = mask.bit_count()
            w.writerow([src, cnt])
            n_src += 1
            if n_src % 5_000_000 == 0:
                print(f"  {n_src:,} sources processed", flush=True)
    print(f"  done: {n_src:,} sources written to {COUNTS}", flush=True)


def phase3_merge():
    print("phase 3: rewriting attributes with diversity_count ...", flush=True)
    if os.path.exists(NEW):
        os.remove(NEW)
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    con = duckdb.connect(NEW)
    con.execute("SET enable_progress_bar=false")
    con.execute("SET memory_limit='12GB'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"ATTACH '{SRC}' AS src (READ_ONLY)")
    con.execute(f"""
        CREATE TABLE attributes AS
        SELECT a.id, a.year, a.field, a.author,
               COALESCE(d.diversity_count, 0) AS diversity_count
        FROM src.attributes a
        LEFT JOIN read_csv('{COUNTS}', header=true,
                           columns={{'id': 'BIGINT', 'diversity_count': 'INTEGER'}}) d
          ON d.id = CAST(ltrim(a.id, 'W') AS BIGINT)
    """)
    con.execute("DETACH src")
    n = con.execute("SELECT count(*) FROM attributes").fetchone()[0]
    print(
        "rows:",
        f"{n:,}",
        "| expected",
        f"{EXPECT:,}",
        "|",
        "OK" if n == EXPECT else "MISMATCH - DO NOT SWAP",
    )
    print("schema:", con.execute("DESCRIBE attributes").fetchall())
    print("diversity_count distribution (0..14):")
    for r in con.execute(
        "SELECT diversity_count, count(*) FROM attributes GROUP BY 1 ORDER BY 1 LIMIT 15"
    ).fetchall():
        print(f"   count={r[0]:<3} papers={r[1]:,}")
    mx = con.execute("SELECT max(diversity_count) FROM attributes").fetchone()[0]
    print(f"   max diversity_count = {mx}")
    con.close()


def main():
    t = time.perf_counter()
    ids, codes = phase1_lookup()
    phase2_stream(ids, codes)
    del ids, codes
    phase3_merge()
    print(f"done in {time.perf_counter()-t:.0f}s")


if __name__ == "__main__":
    main()
