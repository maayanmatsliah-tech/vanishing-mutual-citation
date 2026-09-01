"""
Clean non-paper records (field='Unknown') and identify mutual citation pairs.

Executes three sequential stages:
  1. attributes: Filter out non-paper records (field='Unknown') from attributes.duckdb.
  2. edges: Filter edges.csv to retain only rows where the citing source paper exists
     in the cleaned attributes table.
  3. pairs: Identify reciprocated mutual citation pairs on the cleaned citation graph
     using partitioned batch processing to manage memory efficiently.

Outputs are written to temporary files and atomically renamed upon completion to
support resuming interrupted runs.

Inputs:
  data/attributes.duckdb
  data/edges.csv

Outputs:
  data/attributes_clean.duckdb
  data/edges_clean.csv
  data/mutual_pairs_clean.csv

Env:
  ATTR_IN        Input attributes database (default: data/attributes.duckdb)
  ATTR_OUT       Output cleaned attributes database (default: data/attributes_clean.duckdb)
  EDGES_IN       Input edges CSV (default: data/edges.csv)
  EDGES_OUT      Output cleaned edges CSV (default: data/edges_clean.csv)
  PAIRS_OUT      Output mutual pairs CSV (default: data/mutual_pairs_clean.csv)
  MUT_DB         Scratch database for pair computation (default: data/_mutual_clean.duckdb)
  BATCH_DIR      Directory for pair partition batches (default: data/mutual_pairs_batches)
  N_BATCHES      Number of partitions for pair extraction (default: 20)
  MEM            DuckDB memory limit (default: 12GB)
  PAIRS_MEM      DuckDB memory limit for pair processing (default: 4GB)
  PAIRS_THREADS  DuckDB threads for pair processing (default: 2)
  STAGES         Stages to run ('all' or comma-separated subset: attributes,edges,pairs)
"""

import csv
import glob
import os
import time

import duckdb

ATTR_IN = os.environ.get("ATTR_IN", "data/attributes.duckdb")
ATTR_OUT = os.environ.get("ATTR_OUT", "data/attributes_clean.duckdb")
EDGES_IN = os.environ.get("EDGES_IN", "data/edges.csv")
EDGES_OUT = os.environ.get("EDGES_OUT", "data/edges_clean.csv")
PAIRS_OUT = os.environ.get("PAIRS_OUT", "data/mutual_pairs_clean.csv")
MUT_DB = os.environ.get("MUT_DB", "data/_mutual_clean.duckdb")
BATCH_DIR = os.environ.get("BATCH_DIR", "data/mutual_pairs_batches")
N_BATCHES = int(os.environ.get("N_BATCHES", "20"))
MEM = os.environ.get("MEM", "12GB")
# the unnest stage is the memory-sensitive one; keep it deliberately small so it
# spills to disk in controlled chunks instead of trying to hold ~2.9B rows.
PAIRS_MEM = os.environ.get("PAIRS_MEM", "4GB")
PAIRS_THREADS = os.environ.get("PAIRS_THREADS", "2")
TMP = "data/_duckdb_tmp"

ALL_STAGES = ("attributes", "edges", "pairs")
STAGES = [s.strip() for s in os.environ.get("STAGES", "all").split(",")]
if STAGES == ["all"]:
    STAGES = list(ALL_STAGES)
for s in STAGES:
    if s not in ALL_STAGES:
        raise SystemExit(f"STAGES must be 'all' or a subset of {ALL_STAGES}, got {s!r}")


def _rm(path):
    if os.path.exists(path):
        os.remove(path)


def _require(path, stage):
    if not os.path.exists(path):
        raise SystemExit(f"{stage}: required input {path} does not exist")


def _connect(path=None, mem=MEM, threads=None):
    con = duckdb.connect(path) if path else duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{mem}'")
    con.execute(f"SET temp_directory='{TMP}'")
    con.execute("SET preserve_insertion_order=false")
    if threads:
        con.execute(f"SET threads={threads}")
    return con


def stage_attributes():
    """attributes minus field='Unknown' -> ATTR_OUT."""
    if os.path.exists(ATTR_OUT):
        print(f"1/3 attributes: {ATTR_OUT} exists, skipping (delete it to rebuild)")
        return
    _require(ATTR_IN, "1/3 attributes")
    print("1/3 building clean attributes (dropping field='Unknown') ...", flush=True)
    tmp = ATTR_OUT + ".tmp"
    _rm(tmp)
    con = _connect(tmp)
    con.execute(f"ATTACH '{ATTR_IN}' AS orig (READ_ONLY)")
    con.execute(
        "CREATE TABLE attributes AS SELECT * FROM orig.attributes WHERE field <> 'Unknown'"
    )
    n_orig = con.execute("SELECT count(*) FROM orig.attributes").fetchone()[0]
    n_keep = con.execute("SELECT count(*) FROM attributes").fetchone()[0]
    con.close()
    os.replace(tmp, ATTR_OUT)
    print(
        f"    attributes: {n_orig:,} -> {n_keep:,}  (dropped {n_orig - n_keep:,})",
        flush=True,
    )


def stage_edges():
    """edges whose SOURCE survives the attributes clean -> EDGES_OUT."""
    if os.path.exists(EDGES_OUT):
        print(f"2/3 edges: {EDGES_OUT} exists, skipping (delete it to rebuild)")
        return
    if not os.path.exists(ATTR_OUT):
        raise SystemExit(f"2/3 edges needs {ATTR_OUT}; run the attributes stage first")
    print("2/3 writing clean edges (source must survive) ...", flush=True)
    # read the surviving ids from ATTR_OUT rather than from stage 1's memory, so
    # this stage is runnable on its own.
    con = _connect()
    con.execute(f"ATTACH '{ATTR_OUT}' AS clean (READ_ONLY)")
    con.execute(
        "CREATE TEMP TABLE surv AS "
        "SELECT CAST(ltrim(id,'W') AS BIGINT) AS id FROM clean.attributes"
    )
    tmp = EDGES_OUT + ".tmp"
    _rm(tmp)
    con.execute(f"""
        COPY (
            SELECT source, targets
            FROM read_csv('{EDGES_IN}', header=true, all_varchar=true)
            WHERE CAST(ltrim(source,'W') AS BIGINT) IN (SELECT id FROM surv)
        ) TO '{tmp}' (HEADER, DELIMITER ',')
    """)
    n_edges = con.execute(
        f"SELECT count(*) FROM read_csv('{tmp}', header=true, all_varchar=true)"
    ).fetchone()[0]
    con.close()
    os.replace(tmp, EDGES_OUT)
    print(f"    edges_clean rows: {n_edges:,}", flush=True)


def stage_pairs():
    """mutual pairs on the clean graph, computed in partitions -> PAIRS_OUT."""
    if os.path.exists(PAIRS_OUT):
        print(f"3/3 pairs: {PAIRS_OUT} exists, skipping (delete it to rebuild)")
        return
    if not os.path.exists(EDGES_OUT):
        raise SystemExit(f"3/3 pairs needs {EDGES_OUT}; run the edges stage first")
    os.makedirs(BATCH_DIR, exist_ok=True)
    con = _connect(MUT_DB, mem=PAIRS_MEM, threads=PAIRS_THREADS)

    # reuse the materialized unnest if a previous run already built it
    existing = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'all_edges'"
    ).fetchone()[0]
    if existing:
        print("3/3 pairs: all_edges already materialized, skipping unnest", flush=True)
    else:
        print("3/3 pairs: building sources set ...", flush=True)
        con.execute(f"""
            CREATE TABLE sources AS
            SELECT DISTINCT CAST(ltrim(source,'W') AS BIGINT) AS id
            FROM read_csv('{EDGES_OUT}', header=true, all_varchar=true)
        """)
        print("     unnesting all edges ONCE (the heavy step) ...", flush=True)
        con.execute(f"""
            CREATE TABLE all_edges AS
            SELECT s, t, least(s, t) % {N_BATCHES} AS batch_num
            FROM (
                SELECT CAST(ltrim(source,'W') AS BIGINT) AS s,
                       CAST(ltrim(unnest(string_split(targets,';')),'W') AS BIGINT) AS t
                FROM read_csv('{EDGES_OUT}', header=true, all_varchar=true)
            )
            WHERE s <> t AND t IN (SELECT id FROM sources)
        """)
        con.execute("CREATE INDEX idx_batch ON all_edges(batch_num)")
        con.execute("CHECKPOINT")
        print("     unnest done", flush=True)

    for i in range(N_BATCHES):
        out_path = f"{BATCH_DIR}/batch_{i:03d}.csv"
        if os.path.exists(out_path):
            print(f"     batch {i + 1}/{N_BATCHES} already done, skipping", flush=True)
            continue
        print(f"     batch {i + 1}/{N_BATCHES}: grouping and writing ...", flush=True)
        tmp = out_path + ".tmp"
        _rm(tmp)
        # partitioned on least(s,t) and grouped on (least,greatest), so a pair can
        # never straddle two batches
        con.execute(f"""
            COPY (
                SELECT 'W' || least(s,t) AS paper_a, 'W' || greatest(s,t) AS paper_b
                FROM all_edges
                WHERE batch_num = {i}
                GROUP BY least(s,t), greatest(s,t)
                HAVING bool_or(s < t) AND bool_or(s > t)
            ) TO '{tmp}' (HEADER, DELIMITER ',')
        """)
        con.execute("CHECKPOINT")
        os.replace(tmp, out_path)
    con.close()

    batch_files = sorted(glob.glob(f"{BATCH_DIR}/batch_*.csv"))
    if len(batch_files) != N_BATCHES:
        raise SystemExit(
            f"expected {N_BATCHES} batch files in {BATCH_DIR}, found {len(batch_files)}"
        )
    print("     concatenating batches ...", flush=True)
    tmp = PAIRS_OUT + ".tmp"
    with open(tmp, "w", newline="") as out_f:
        csv.writer(out_f).writerow(["paper_a", "paper_b"])
        for batch_file in batch_files:
            with open(batch_file) as f:
                next(f)
                out_f.writelines(f)
        out_f.flush()
        os.fsync(out_f.fileno())
    os.replace(tmp, PAIRS_OUT)
    with open(PAIRS_OUT) as f:
        n_pairs = sum(1 for _ in f) - 1
    print(f"    mutual pairs: {n_pairs:,}", flush=True)


def main():
    os.makedirs(TMP, exist_ok=True)
    t0 = time.perf_counter()
    if "attributes" in STAGES:
        stage_attributes()
    if "edges" in STAGES:
        stage_edges()
    if "pairs" in STAGES:
        stage_pairs()
    print(f"\nDONE in {time.perf_counter() - t0:.0f}s", flush=True)
    for path in (ATTR_OUT, EDGES_OUT, PAIRS_OUT):
        if os.path.exists(path):
            print(f"  {path}")
    print(
        f"\n(the materialized unnest is left in {MUT_DB} for resume; "
        f"delete it to reclaim the space)"
    )


if __name__ == "__main__":
    main()
