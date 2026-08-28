"""
Add `diversity_count` to attributes.duckdb — Strategy B (streaming).

diversity_count = number of DISTINCT fields a paper cites OTHER papers on,
excluding self-citations and not counting 'Unknown'. Papers that cite nothing,
or only Unknown / only out-of-set papers, get 0.

Why streaming: the only thing that must be resident is the id->field lookup
(~4 GB); the 2.96B citations are streamed one source-row at a time from the
adjacency CSV, so there is no large hash-join and no big disk spill.

  Phase 1  load sorted (id_int, field_code) into RAM from attributes.duckdb.
           field_code: non-Unknown fields -> 0..N-1; Unknown -> -1.
  Phase 2  stream edges.csv once; per source, look up each target's code via
           binary search, drop self / out-of-set / Unknown, OR the surviving
           field bits into one integer, popcount -> count. Write (id_int,count).
  Phase 3  DuckDB rewrites attributes with the new column (LEFT JOIN counts,
           default 0) into a fresh db file. Caller verifies + swaps it in.

Fixed ~4-5 GB RAM; the heavy pass writes only a small counts CSV (no spill).
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
    print(f"  loaded {ids.shape[0]:,} papers; "
          f"{int((codes >= 0).sum()):,} have a known (non-Unknown) field", flush=True)
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
                ck = pc[(pc >= 0) & (pt != src)]   # non-Unknown, non-self
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
    print("rows:", f"{n:,}", "| expected", f"{EXPECT:,}", "|",
          "OK" if n == EXPECT else "MISMATCH - DO NOT SWAP")
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
