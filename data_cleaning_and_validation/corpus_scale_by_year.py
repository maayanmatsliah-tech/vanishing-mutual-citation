"""
Corpus scale by year: total papers published, and average reference-list length.

Backs the paper's claims:
  "output rose from 515,931 papers in 1975 to 6,031,157 in 2023" (1,069% growth)
  "average reference list lengthened from 7.7 to 32.6 works" (4.2-fold growth)

Definitions:
  n_papers        every paper in attributes for that year (not filtered to
                   citing papers only -- a paper with zero references is still
                   a paper, and belongs in the denominator below).
  total_refs      sum of RAW reference-list length (len(string_split(targets,';'))
                   per source row) for papers published that year. This is
                   raw list length, NOT deduplicated/self-citation-corrected
                   n_cited -- "reference list length" means what's actually in
                   the reference list, so no dedup here on purpose.
  avg_ref_length  total_refs / n_papers. Papers with no edges.csv row
                   (0 references) are included via the LEFT JOIN + COALESCE,
                   so they correctly pull the average down.

IMPORTANT: point ATTR/EDGES at whichever stage of the pipeline you've decided
is authoritative for the paper's headline numbers (raw vs _clean). Defaults
below match the other original scripts (raw), NOT the _clean versions -- see
the reproducibility checklist note about clean_dataset.py's outputs not being
wired into the other analysis scripts by default. Override via env vars if
you want the cleaned corpus instead, e.g.:
  ATTR=data/attributes_clean... EDGES=data/edges_clean.csv python corpus_scale_by_year.py

Reads CSVs directly, no persistent DuckDB file required, so this is read-only
with respect to everything upstream.

Env:
  ATTR        default data/attributes.csv
  EDGES       default data/edges.csv
  OUT         default outputs/corpus_scale/corpus_scale_by_year.csv
  MEM         default 12GB
  START/END   year bounds, default 1975 / 2023 (paper's effective corpus end)
"""

import os

import duckdb

ATTR = os.environ.get("ATTR", "data/attributes.duckdb")
EDGES = os.environ.get("EDGES", "data/edges.csv")
OUT = os.environ.get("OUT", "outputs/corpus_scale/corpus_scale_by_year.csv")
MEM = os.environ.get("MEM", "12GB")
DUCKDB_TMP = os.environ.get("DUCKDB_TMP", "data/_duckdb_tmp")
START = int(os.environ.get("START", "1975"))
END = int(os.environ.get("END", "2023"))


def compute():
    os.makedirs(DUCKDB_TMP, exist_ok=True)
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute(f"SET temp_directory='{DUCKDB_TMP}'")
    con.execute("SET preserve_insertion_order=false")

    print("1/2 loading attributes (id, year) ...", flush=True)
    con.execute(f"ATTACH '{ATTR}' AS a (READ_ONLY)")
    con.execute(f"""
        CREATE TEMP TABLE attr AS
        SELECT CAST(ltrim(id, 'W') AS BIGINT) AS id,
               year                            AS year
        FROM a.attributes
        WHERE year BETWEEN {START} AND {END}
    """)
    con.execute("DETACH a")

    # Raw per-source reference-list length: len(split(';')) directly off the
    # edges row, no unnest. Cheap: one row scanned per source, not per citation.
    print("2/2 computing raw reference-list length per source ...", flush=True)
    con.execute(f"""
        CREATE TEMP TABLE reflen AS
        SELECT TRY_CAST(ltrim(source, 'W') AS BIGINT) AS id,
               len(string_split(targets, ';'))         AS n_refs
        FROM read_csv('{EDGES}', header=true, all_varchar=true, ignore_errors=true)
    """)

    rows = con.execute("""
        SELECT a.year                              AS year,
               count(*)                             AS n_papers,
               sum(COALESCE(r.n_refs, 0))            AS total_refs,
               avg(COALESCE(r.n_refs, 0))            AS avg_ref_length
        FROM attr a
        LEFT JOIN reflen r ON r.id = a.id
        GROUP BY a.year
        ORDER BY a.year
    """).fetchall()
    con.close()
    return rows


def write_outputs(rows):
    import csv

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "n_papers", "total_refs", "avg_ref_length"])
        for year, n, total_refs, avg_len in rows:
            w.writerow([year, n, total_refs, f"{avg_len:.4f}"])
    print(f"wrote {OUT}")


def main():
    rows = compute()
    print(f"\n{'year':>6} {'n_papers':>12} {'total_refs':>14} {'avg_ref_length':>16}")
    for year, n, total_refs, avg_len in rows:
        print(f"{year:>6} {n:>12,} {total_refs:>14,} {avg_len:>16.2f}")

    if rows:
        first, last = rows[0], rows[-1]
        n0, n1 = first[1], last[1]
        a0, a1 = first[3], last[3]
        print(f"\n{first[0]} -> {last[0]}:")
        print(f"  n_papers:       {n0:,} -> {n1:,}  ({100*(n1-n0)/n0:.1f}% growth)")
        print(f"  avg_ref_length: {a0:.2f} -> {a1:.2f}  ({a1/a0:.2f}x)")

    write_outputs(rows)


if __name__ == "__main__":
    main()