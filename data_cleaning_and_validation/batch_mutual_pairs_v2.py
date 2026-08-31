import duckdb
import os

DB = "data/_mutual_clean.duckdb"
EDGES = "data/edges.csv"
OUT_DIR = "data/mutual_pairs_batches"
N_BATCHES = 20

os.makedirs(OUT_DIR, exist_ok=True)

con = duckdb.connect(DB)
con.execute("SET enable_progress_bar=true")
con.execute("SET memory_limit='4GB'")
con.execute("SET threads=2")
con.execute("SET temp_directory='data/_duckdb_tmp'")
con.execute("SET preserve_insertion_order=false")

# Check if all_edges already exists from the previous run
existing = con.execute("""
    SELECT count(*) FROM information_schema.tables WHERE table_name = 'all_edges'
""").fetchone()[0]

if existing:
    print("all_edges already exists, skipping unnest step")
else:
    print("building sources set (one-time)...")
    con.execute(f"""
        CREATE TABLE sources AS
        SELECT DISTINCT CAST(ltrim(source,'W') AS BIGINT) AS id
        FROM read_csv('{EDGES}', header=true, all_varchar=true)
    """)

    print("unnesting all edges ONCE (this is the one-time heavy step)...")
    con.execute(f"""
        CREATE TABLE all_edges AS
        SELECT s, t, least(s, t) % {N_BATCHES} AS batch_num
        FROM (
            SELECT CAST(ltrim(source,'W') AS BIGINT) AS s,
                   CAST(ltrim(unnest(string_split(targets,';')),'W') AS BIGINT) AS t
            FROM read_csv('{EDGES}', header=true, all_varchar=true)
        )
        WHERE s <> t AND t IN (SELECT id FROM sources)
    """)
    con.execute("CHECKPOINT")
    print("unnest done")

print("now looping batches...")
for i in range(N_BATCHES):
    out_path = f"{OUT_DIR}/batch_{i:03d}.csv"
    if os.path.exists(out_path):
        print(f"batch {i+1}/{N_BATCHES} already done, skipping")
        continue
    print(f"batch {i+1}/{N_BATCHES}: grouping and writing...")
    con.execute(f"""
        COPY (
            SELECT 'W' || least(s,t) AS paper_a, 'W' || greatest(s,t) AS paper_b
            FROM all_edges
            WHERE batch_num = {i}
            GROUP BY least(s,t), greatest(s,t)
            HAVING bool_or(s < t) AND bool_or(s > t)
        ) TO '{out_path}' (HEADER, DELIMITER ',')
    """)
    con.execute("CHECKPOINT")
    print(f"batch {i+1}/{N_BATCHES} done")

con.close()
print("\nall batches complete — concatenating...")

import glob, csv
with open("data/mutual_pairs_clean.csv", "w", newline="") as out_f:
    w = csv.writer(out_f)
    w.writerow(["paper_a", "paper_b"])
    for batch_file in sorted(glob.glob(f"{OUT_DIR}/*.csv")):
        with open(batch_file) as f:
            next(f)
            out_f.writelines(f)
    out_f.flush()
    os.fsync(out_f.fileno())

n = sum(1 for _ in open("data/mutual_pairs_clean.csv")) - 1
print(f"wrote {n:,} mutual pairs to data/mutual_pairs_clean.csv")