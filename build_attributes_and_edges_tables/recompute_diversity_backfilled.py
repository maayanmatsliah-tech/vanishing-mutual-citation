"""
Recompute diversity_count with the left-boundary repaired: the id->field lookup
is AUGMENTED with the 34M pre-1975 fields (data/pre1975_fields/), so citations to
pre-1975 papers -- previously 'out-of-set' and fieldless -- now contribute their
field. Everything else matches add_diversity_count.py exactly.

Does NOT overwrite attributes.duckdb. Emits:
  COUNTS   per-paper new diversity_count           (data/_div_backfilled_counts.csv)
  CMP      before/after by year (mean + group dist) (OUT_CMP, printed too)

Env: SRC, EDGES, PRE, COUNTS, OUT_CMP, MEM.
"""
import csv, os, sys, time
import numpy as np
import duckdb

SRC     = os.environ.get("SRC", "data/attributes.duckdb")
EDGES   = os.environ.get("EDGES", "data/edges.csv")
PRE     = os.environ.get("PRE", "data/pre1975_fields/batch_*.parquet")
COUNTS  = os.environ.get("COUNTS", "data/_div_backfilled_counts.csv")
OUT_CMP = os.environ.get("OUT_CMP", "data/diversity_before_after_by_year.csv")
MEM     = os.environ.get("MEM", "12GB")
csv.field_size_limit(sys.maxsize)


def phase1():
    """Unified id->field-code lookup over in-set (attributes) + pre-1975 works.
    Real fields -> 0..N-1 (shared code space); Unknown/absent -> -1."""
    print("phase 1: building augmented id->field lookup ...", flush=True)
    con = duckdb.connect(SRC, read_only=True)
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    # shared field->code map from the union of real fields
    con.execute(f"""
        CREATE TEMP TABLE fcode AS
        SELECT field, ROW_NUMBER() OVER (ORDER BY field) - 1 AS code FROM (
            SELECT DISTINCT field FROM attributes WHERE field <> 'Unknown'
            UNION
            SELECT DISTINCT field FROM read_parquet('{PRE}')
        )
    """)
    n_fields = con.execute("SELECT count(*) FROM fcode").fetchone()[0]
    a = con.execute("""
        SELECT CAST(ltrim(a.id,'W') AS BIGINT) AS id,
               CAST(COALESCE(f.code,-1) AS SMALLINT) AS code
        FROM attributes a LEFT JOIN fcode f ON f.field = a.field
    """).fetchnumpy()
    p = con.execute(f"""
        SELECT pre.id AS id, CAST(f.code AS SMALLINT) AS code
        FROM read_parquet('{PRE}') pre JOIN fcode f ON f.field = pre.field
    """).fetchnumpy()
    con.close()
    ids  = np.concatenate([a["id"],  p["id"]])
    code = np.concatenate([a["code"].astype(np.int16), p["code"].astype(np.int16)])
    order = np.argsort(ids, kind="stable")
    ids, code = ids[order], code[order]
    print(f"  {n_fields} field codes; lookup = {ids.shape[0]:,} ids "
          f"({a['id'].shape[0]:,} in-set + {p['id'].shape[0]:,} pre-1975)", flush=True)
    return ids, code


CHUNK = int(os.environ.get("CHUNK", "200000"))  # source rows per vectorized batch


def _flush_chunk(srcs, tgt_str, ids, code, N, w):
    """Vectorized diversity for one batch of rows. srcs: list[int]; tgt_str:
    list[str] of ';'-joined 'W..' targets. Writes (src, distinct_field_count)."""
    counts = np.fromiter((s.count(";") + 1 for s in tgt_str), dtype=np.int64,
                         count=len(tgt_str))
    S = np.fromiter(srcs, dtype=np.int64, count=len(srcs))
    # one parse of all targets in the batch: strip 'W', split on ';'
    T = np.fromstring(";".join(tgt_str).replace("W", ""), dtype=np.int64, sep=";")
    idx = np.searchsorted(ids, T); np.clip(idx, 0, N - 1, out=idx)
    codes = code[idx]
    valid = (ids[idx] == T) & (codes >= 0) & (T != np.repeat(S, counts))
    bit = np.where(valid, np.int64(1) << np.where(codes >= 0, codes, 0).astype(np.int64),
                   np.int64(0))
    starts = np.empty(counts.shape[0], dtype=np.int64)
    starts[0] = 0
    np.cumsum(counts[:-1], out=starts[1:])
    masks = np.bitwise_or.reduceat(bit, starts)
    cnts = np.bitwise_count(masks)
    for s, c in zip(srcs, cnts.tolist()):
        w.writerow([s, c])


def phase2(ids, code):
    print("phase 2: streaming edges.csv (augmented lookup, vectorized) ...", flush=True)
    N = ids.shape[0]
    n_src = 0
    t0 = time.perf_counter()
    with open(EDGES, newline="") as f, open(COUNTS, "w", newline="") as out:
        r = csv.reader(f); w = csv.writer(out)
        next(r); w.writerow(["id", "diversity_count"])
        srcs, tgts = [], []
        for row in r:
            srcs.append(int(row[0][1:])); tgts.append(row[1])
            if len(srcs) >= CHUNK:
                _flush_chunk(srcs, tgts, ids, code, N, w)
                n_src += len(srcs); srcs, tgts = [], []
                dt = time.perf_counter() - t0
                print(f"  {n_src:,} sources ({dt:.0f}s, {n_src/dt:,.0f}/s)", flush=True)
        if srcs:
            _flush_chunk(srcs, tgts, ids, code, N, w); n_src += len(srcs)
    print(f"  done: {n_src:,} sources ({time.perf_counter()-t0:.0f}s)", flush=True)


def phase3():
    print("phase 3: before/after comparison by year ...", flush=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute(f"ATTACH '{SRC}' AS a (READ_ONLY)")
    con.execute(f"""
        CREATE TEMP TABLE cmp AS
        SELECT att.year AS year,
               att.diversity_count AS old_dc,
               COALESCE(n.diversity_count, 0) AS new_dc
        FROM a.attributes att
        JOIN read_csv('{COUNTS}', header=true,
                      columns={{'id':'BIGINT','diversity_count':'INTEGER'}}) n
          ON CAST(ltrim(att.id,'W') AS BIGINT) = n.id
    """)
    rows = con.execute("""
        SELECT year, count(*) AS n_papers,
               avg(old_dc) AS mean_old, avg(new_dc) AS mean_new,
               avg(new_dc - old_dc) AS mean_gain,
               100.0*sum(CASE WHEN new_dc > old_dc THEN 1 ELSE 0 END)/count(*) AS pct_raised
        FROM cmp GROUP BY year ORDER BY year
    """).fetchall()
    con.execute(f"""COPY (
        SELECT year, count(*) n_papers, avg(old_dc) mean_old, avg(new_dc) mean_new,
               avg(new_dc-old_dc) mean_gain,
               100.0*sum(CASE WHEN new_dc>old_dc THEN 1 ELSE 0 END)/count(*) pct_raised
        FROM cmp GROUP BY year ORDER BY year
    ) TO '{OUT_CMP}' (HEADER, DELIMITER ',')""")
    con.close()
    print(f"\n{'year':>5} {'n_papers':>12} {'mean_old':>9} {'mean_new':>9} "
          f"{'gain':>7} {'%raised':>8}")
    for y, n, mo, mn, g, pr in rows:
        print(f"{y:>5} {n:>12,} {mo:>9.3f} {mn:>9.3f} {g:>7.3f} {pr:>7.1f}%")
    print(f"\nwrote {OUT_CMP}")


def main():
    t = time.perf_counter()
    ids, code = phase1()
    phase2(ids, code)
    del ids, code
    phase3()
    print(f"total {time.perf_counter()-t:.0f}s")


if __name__ == "__main__":
    main()
