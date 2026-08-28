"""
Validate the collected snapshot (attributes.csv + edges.csv) before any research.

Tiers 1 & 2:
  T1 completeness      every bucket part is in the checkpoint (nothing skipped)
  T1 row parity        DuckDB's logical row count matches the csv-reader count
  T1 id/year validity  ids parse as W+digits; years all within [START,END], none null
  T1 referential       every edges.source exists in attributes
  T1 zero-citation     how many papers have no outbound citations
  T1 target coverage   fraction of the ~2B citations whose target's field we know
  T2 structural        malformed/rejected rows in either file
  T2 edges shape       one row per source; self-loops; duplicate targets within a list
  T2 field domain      distinct fields, "Unknown" share, null fields

Storage policy: on-disk DuckDB (db file + temp dir on disk), memory_limit caps RAM.
Reads the CSVs directly; nothing in the CSVs is modified.

Env:
  ATTR/EDGES   CSV paths            (default data/attributes.csv, data/edges.csv)
  PROGRESS     checkpoint tsv       (default data/.snapshot_progress.tsv)
  VALDB        scratch db path      (default data/_validate.duckdb)
  DUCKDB_TMP   spill dir            (default data/_duckdb_tmp)
  MEM          memory_limit         (default 16GB)
  START/END    expected year bounds (default 1975 / 2025)
  EXPECT_ROWS  known csv-reader row count for parity (default 413392893)
"""

import os

import boto3
import duckdb
from botocore import UNSIGNED
from botocore.config import Config

ATTR = os.environ.get("ATTR", "data/attributes.csv")
EDGES = os.environ.get("EDGES", "data/edges.csv")
PROGRESS = os.environ.get("PROGRESS", "data/.snapshot_progress.tsv")
VALDB = os.environ.get("VALDB", "data/_validate.duckdb")
DUCKDB_TMP = os.environ.get("DUCKDB_TMP", "data/_duckdb_tmp")
MEM = os.environ.get("MEM", "16GB")
START = int(os.environ.get("START", "1975"))
END = int(os.environ.get("END", "2025"))
EXPECT_ROWS = int(os.environ.get("EXPECT_ROWS", "413392893"))
# edges.csv has no quoted fields, so physical lines == logical rows
EXPECT_EDGE_ROWS = int(os.environ.get("EXPECT_EDGE_ROWS", "117055340"))

BUCKET = "openalex"
WORKS_PREFIX = "data/works/"

results = []  # (status, label, detail)


def record(status, label, detail):
    results.append((status, label, detail))
    print(f"[{status:4}] {label}: {detail}", flush=True)


def check_completeness():
    """Every .gz part in the bucket must appear in the checkpoint."""
    print("\n--- T1 completeness: bucket parts vs checkpoint ---", flush=True)
    done = set()
    with open(PROGRESS, encoding="utf-8") as f:
        for line in f:
            k = line.split("\t")[0]
            if k:
                done.add(k)
    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))
    p = s3.get_paginator("list_objects_v2")
    bucket_parts = set()
    for folder_page in p.paginate(Bucket=BUCKET, Prefix=WORKS_PREFIX, Delimiter="/"):
        for cp in folder_page.get("CommonPrefixes", []):
            for page in p.paginate(Bucket=BUCKET, Prefix=cp["Prefix"]):
                for o in page.get("Contents", []):
                    if o["Key"].endswith(".gz"):
                        bucket_parts.add(o["Key"])
    missing = bucket_parts - done
    extra = done - bucket_parts
    detail = f"{len(bucket_parts):,} bucket parts, {len(done):,} checkpointed, {len(missing):,} missing"
    record("PASS" if not missing else "FAIL", "completeness", detail)
    if missing:
        for k in list(sorted(missing))[:5]:
            print(f"        missing: {k}", flush=True)
    if extra:
        print(f"        note: {len(extra):,} checkpointed keys not in bucket (stale)", flush=True)


def main():
    os.makedirs(DUCKDB_TMP, exist_ok=True)
    if os.path.exists(VALDB):
        os.remove(VALDB)

    check_completeness()

    con = duckdb.connect(VALDB)
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute(f"SET temp_directory='{DUCKDB_TMP}'")
    con.execute("SET preserve_insertion_order=false")

    # ---- T2 structural integrity via parser agreement ----
    # The robust, version-independent check: DuckDB (with ignore_errors) must
    # parse exactly as many rows as the authoritative csv reader. A malformed
    # row would be silently dropped here and the counts would diverge.
    print("\n--- materialize a compact attributes table on disk (id, year, field) ---",
          flush=True)
    print("\n--- building compact attributes table (on disk) ---", flush=True)
    con.execute(f"""
        CREATE OR REPLACE TABLE attr AS
        SELECT TRY_CAST(ltrim(id, 'W') AS BIGINT) AS id,
               TRY_CAST(year AS INTEGER)          AS year,
               field
        FROM read_csv('{ATTR}', header=true, all_varchar=true, ignore_errors=true)
    """)
    n_attr = con.execute("SELECT count(*) FROM attr").fetchone()[0]

    # ---- T1/T2 structural: parser agreement on attributes ----
    record("PASS" if n_attr == EXPECT_ROWS else "FAIL", "structural[attributes]",
           f"DuckDB parsed {n_attr:,} rows vs csv-reader {EXPECT_ROWS:,}")

    # ---- T1 id validity ----
    bad_id = con.execute("SELECT count(*) FROM attr WHERE id IS NULL").fetchone()[0]
    record("PASS" if bad_id == 0 else "FAIL", "id parse",
           f"{bad_id:,} ids not parseable as W+digits")

    # ---- T1 id uniqueness (re-confirm in DuckDB) ----
    n_uid = con.execute("SELECT count(DISTINCT id) FROM attr").fetchone()[0]
    record("PASS" if n_uid == n_attr else "FAIL", "id uniqueness",
           f"{n_uid:,} distinct of {n_attr:,}")

    # ---- T1 year validity ----
    ynull, ylo, yhi, ymin, ymax = con.execute(f"""
        SELECT count(*) FILTER (WHERE year IS NULL),
               count(*) FILTER (WHERE year < {START}),
               count(*) FILTER (WHERE year > {END}),
               min(year), max(year)
        FROM attr
    """).fetchone()
    ok = (ynull == 0 and ylo == 0 and yhi == 0)
    record("PASS" if ok else "FAIL", "year validity",
           f"range [{ymin},{ymax}]; null={ynull:,} below={ylo:,} above={yhi:,}")

    # ---- T2 field domain ----
    nfields, nfnull = con.execute(
        "SELECT count(DISTINCT field), count(*) FILTER (WHERE field IS NULL) FROM attr"
    ).fetchone()
    unk = con.execute(
        "SELECT count(*) FROM attr WHERE field = 'Unknown'"
    ).fetchone()[0]
    record("INFO", "field domain",
           f"{nfields} distinct fields; Unknown={unk:,} ({unk/n_attr*100:.1f}%); "
           f"null={nfnull:,}")

    # ---- per-year distribution (info; spot a missing year) ----
    rows = con.execute(
        "SELECT year, count(*) FROM attr GROUP BY year ORDER BY year"
    ).fetchall()
    empty_years = [y for y in range(START, END + 1)
                   if y not in {r[0] for r in rows}]
    record("PASS" if not empty_years else "WARN", "year coverage",
           f"{len(rows)} distinct years; empty years: {empty_years or 'none'}")

    # ---- edges views (no materialization; per-row list ops avoid the unnest) ----
    con.execute(f"""
        CREATE OR REPLACE VIEW edges_raw AS
        SELECT source, targets FROM read_csv('{EDGES}', header=true,
            all_varchar=true, ignore_errors=true)
    """)

    # ---- T2 edges shape (one scan, all per-row) ----
    print("\n--- T2 edges shape ---", flush=True)
    src_rows, dist_src, total_edges, self_in_list, dup_src_lists, dup_tgt_inst = (
        con.execute("""
            SELECT count(*),
                   count(DISTINCT source),
                   sum(len(string_split(targets, ';'))),
                   count(*) FILTER (WHERE list_contains(string_split(targets, ';'), source)),
                   count(*) FILTER (WHERE len(string_split(targets, ';'))
                                       <> len(list_distinct(string_split(targets, ';')))),
                   sum(len(string_split(targets, ';'))
                       - len(list_distinct(string_split(targets, ';'))))
            FROM edges_raw
        """).fetchone()
    )
    record("PASS" if src_rows == EXPECT_EDGE_ROWS else "FAIL", "structural[edges]",
           f"DuckDB parsed {src_rows:,} rows vs expected {EXPECT_EDGE_ROWS:,}")
    record("PASS" if src_rows == dist_src else "FAIL", "source uniqueness",
           f"{src_rows:,} rows, {dist_src:,} distinct sources")
    record("INFO", "total citations", f"{total_edges:,} directed edges")
    record("INFO", "self-loops", f"{self_in_list:,} sources list themselves as a target")
    record("INFO", "duplicate targets",
           f"{dup_src_lists:,} sources have repeated target ids ({dup_tgt_inst:,} dup instances)")

    # ---- T1 referential integrity: every source is a known paper ----
    print("\n--- T1 referential integrity (sources in attributes) ---", flush=True)
    miss_src = con.execute("""
        SELECT count(*) FROM (
            SELECT TRY_CAST(ltrim(source, 'W') AS BIGINT) AS s FROM edges_raw
        ) e LEFT JOIN attr a ON a.id = e.s
        WHERE a.id IS NULL
    """).fetchone()[0]
    record("PASS" if miss_src == 0 else "FAIL", "referential(sources)",
           f"{miss_src:,} sources not present in attributes")

    # ---- T1 zero-citation cliff ----
    papers_with_edges = dist_src
    zero = n_attr - papers_with_edges
    record("INFO", "zero-citation papers",
           f"{zero:,} of {n_attr:,} papers ({zero/n_attr*100:.1f}%) have no outbound citations")

    # ---- T1 target coverage (the heavy one: unnest ~2B + join to attr) ----
    print("\n--- T1 target coverage (unnesting ~2B citations; this is the slow step) ---",
          flush=True)
    total_t, parseable_t, known_t = con.execute("""
        WITH t AS (
            SELECT TRY_CAST(ltrim(unnest(string_split(targets, ';')), 'W') AS BIGINT) AS target
            FROM edges_raw
        )
        SELECT count(*),
               count(target),
               count(*) FILTER (WHERE a.id IS NOT NULL)
        FROM t LEFT JOIN attr a ON a.id = t.target
    """).fetchone()
    record("INFO", "target parse",
           f"{total_t - parseable_t:,} of {total_t:,} target ids unparseable")
    record("INFO", "target field coverage",
           f"{known_t:,} of {total_t:,} citations ({known_t/total_t*100:.1f}%) "
           f"point to a paper whose field we know")

    # ---- summary ----
    print("\n================ SUMMARY ================", flush=True)
    for status in ("FAIL", "WARN", "PASS", "INFO"):
        for st, label, detail in results:
            if st == status:
                print(f"[{st:4}] {label}: {detail}", flush=True)
    n_fail = sum(1 for st, _, _ in results if st == "FAIL")
    print(f"\n{n_fail} FAIL(s).", flush=True)

    con.close()
    # leave VALDB/tmp for inspection; they can be deleted to reclaim disk.


if __name__ == "__main__":
    main()
