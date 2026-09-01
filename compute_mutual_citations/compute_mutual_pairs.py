"""
Produce a CLEAN copy of the dataset by dropping non-paper records, then rebuild
the mutual-citation pairs on the cleaned graph. One script, three stages, no
hand-off to another file.

Root cause (see docs / memory): the OpenAlex snapshot was ingested with NO
work-type filter, so ~17.7M non-paper records (datasets, author-profile "other"
records, paratext, peer-review) came in -- 94% of them dated 2024/2025. They
all lack a topic, so they carry field='Unknown'. We can't filter by `type`
(it was never stored), but `field='Unknown'` cleanly identifies this junk.

Stages (originals are left untouched as backups):
  1 attributes  data/attributes_clean.duckdb  attributes minus field='Unknown'
  2 edges       data/edges_clean.csv          edges whose SOURCE survives (targets
                                              kept intact, so the existing
                                              diversity_count stays consistent)
  3 pairs       data/mutual_pairs_clean.csv   mutual pairs on the clean graph; both
                                              endpoints are guaranteed surviving
                                              papers because the source-filter keeps
                                              only targets that are themselves clean
                                              sources

Stage 3 reads the stage-2 output directly, so no intermediate rename is needed.

WHY STAGE 3 IS BATCHED. It used to be a single COPY: unnest all ~2.9B citations
-> filter -> group by (least,greatest) -> keep pairs reciprocated in both
directions. That always died with
    OutOfMemoryError: failed to offload data block (54.7 GiB/54.7 GiB used)
because the whole unnest had to be resident at once (see data/clean_dataset.log).
Instead the unnest is materialized ONCE into a persistent table tagged
`least(s,t) % N_BATCHES`, and each partition is grouped separately. Rows are
grouped by (least,greatest) and partitioned on least(s,t), so every row of a
given pair lands in the same batch -- the batches therefore concatenate to
exactly the one-shot result, they are not an approximation.

RESUME. Every stage skips itself if its output already exists, and stage 3
additionally skips individual finished batches and reuses the materialized
unnest. Delete an output to force that stage to rebuild. A run killed partway
through the heavy unnest can simply be relaunched.

Every output is built at <path>.tmp and atomically renamed into place on
success, so "the file exists" always means "that stage finished". Without this
a run killed mid-write would leave a truncated edges_clean.csv (or an empty
attributes db) that every later run would silently accept as complete.

Env: ATTR_IN, ATTR_OUT, EDGES_IN, EDGES_OUT, PAIRS_OUT, MUT_DB, BATCH_DIR,
     N_BATCHES (default 20), MEM (default 12GB), PAIRS_MEM (default 4GB),
     PAIRS_THREADS (default 2), STAGES (default all; comma-separated subset of
     attributes,edges,pairs).
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
    print(f"    attributes: {n_orig:,} -> {n_keep:,}  (dropped {n_orig - n_keep:,})",
          flush=True)


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
    print(f"\n(the materialized unnest is left in {MUT_DB} for resume; "
          f"delete it to reclaim the space)")


if __name__ == "__main__":
    main()
