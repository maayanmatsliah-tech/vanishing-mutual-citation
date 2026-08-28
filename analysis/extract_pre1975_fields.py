"""
Extract id -> field for all pre-1975 works from the OpenAlex PARQUET snapshot,
so diversity_count can be recomputed without the left-boundary undercount (cited
pre-1975 papers are currently 'out-of-set' and contribute no field).

Reads only 3 columns (id, publication_year, primary_topic.field) straight from
s3://openalex via httpfs -- no full-snapshot download, no local storage.

RESILIENT: parts are processed in batches; each batch is retried on network
errors and checkpointed, so a dropped connection (S3 DNS blips are common on
long runs) resumes instead of restarting the whole scan. Re-run to resume.

Output: one parquet per batch under OUTDIR (columns: id BIGINT, field VARCHAR),
readable downstream as a glob 'data/pre1975_fields/batch_*.parquet'.

Env: OUTDIR (default data/pre1975_fields), MEM (10GB), MAXYEAR (1975),
     BATCH (parts per batch, default 25), RETRIES (per batch, default 15).
"""
import os, time, json
import boto3
from botocore import UNSIGNED
from botocore.config import Config
import duckdb

OUTDIR   = os.environ.get("OUTDIR", "data/pre1975_fields")
MEM      = os.environ.get("MEM", "10GB")
MAXYEAR  = int(os.environ.get("MAXYEAR", "1975"))
BATCH    = int(os.environ.get("BATCH", "25"))
RETRIES  = int(os.environ.get("RETRIES", "15"))
DONEFILE = os.path.join(OUTDIR, ".done")


def part_urls():
    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED,
                                           connect_timeout=30, read_timeout=120))
    m = json.loads(s3.get_object(Bucket="openalex",
                   Key="data/parquet/works/manifest.json")["Body"].read())
    return [e["url"] for e in m["files"]]


def new_con():
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-east-1';")
    con.execute(f"SET memory_limit='{MEM}';")
    con.execute("SET temp_directory='data/_duckdb_tmp';")
    con.execute("SET preserve_insertion_order=false;")
    con.execute("SET enable_progress_bar=false;")
    con.execute("SET http_retries=20;")
    con.execute("SET http_retry_backoff=4;")
    con.execute("SET http_timeout=120000;")
    return con


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    urls = part_urls()
    batches = [urls[i:i + BATCH] for i in range(0, len(urls), BATCH)]
    done = set()
    if os.path.exists(DONEFILE):
        with open(DONEFILE) as f:
            done = {int(x) for x in f.read().split()}
    print(f"{len(urls)} parts -> {len(batches)} batches; {len(done)} already done", flush=True)

    con = new_con()
    t0 = time.perf_counter()
    for bi, burls in enumerate(batches):
        if bi in done:
            continue
        out = os.path.join(OUTDIR, f"batch_{bi:04d}.parquet")
        lst = "[" + ",".join(f"'{u}'" for u in burls) + "]"
        for attempt in range(1, RETRIES + 1):
            try:
                con.execute(f"""
                    COPY (
                        SELECT CAST(regexp_extract(id, '(\\d+)$', 1) AS BIGINT) AS id,
                               primary_topic.field.display_name              AS field
                        FROM read_parquet({lst})
                        WHERE publication_year < {MAXYEAR}
                          AND primary_topic.field.display_name IS NOT NULL
                    ) TO '{out}' (FORMAT parquet)
                """)
                with open(DONEFILE, "a") as f:
                    f.write(f"{bi}\n")
                done.add(bi)
                print(f"  batch {bi+1}/{len(batches)} ok  "
                      f"({time.perf_counter()-t0:.0f}s elapsed)", flush=True)
                break
            except Exception as ex:
                if attempt == RETRIES:
                    print(f"  batch {bi} FAILED after {RETRIES} tries: {ex}", flush=True)
                    raise
                wait = min(60, 2 ** attempt)
                print(f"  batch {bi} {type(ex).__name__} (try {attempt}/{RETRIES}); "
                      f"reconnect+retry in {wait}s", flush=True)
                # a failed COPY may leave a partial file; drop it before retry
                try:
                    if os.path.exists(out):
                        os.remove(out)
                except OSError:
                    pass
                time.sleep(wait)
                try:
                    con.close()
                except Exception:
                    pass
                con = new_con()

    n = con.execute(
        f"SELECT count(*) FROM read_parquet('{OUTDIR}/batch_*.parquet')").fetchone()[0]
    print(f"\nDONE: {n:,} pre-{MAXYEAR} id->field rows  "
          f"({time.perf_counter()-t0:.0f}s)", flush=True)
    print("field distribution (top 12):", flush=True)
    for r in con.execute(f"""SELECT field, count(*) c
                             FROM read_parquet('{OUTDIR}/batch_*.parquet')
                             GROUP BY 1 ORDER BY c DESC LIMIT 12""").fetchall():
        print(f"   {r[0]:<45} {r[1]:>12,}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
