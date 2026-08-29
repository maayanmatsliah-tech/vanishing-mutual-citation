"""
Mean mutual citations per paper by year.

This keeps the same cohort as before: papers that cite at least one work
(n_cited >= 1). It reports only the mean mutual-citation count per paper and
omits the diversity overlay.

Per paper we need: year, diversity_count, n_mutual.
  - n_mutual = number of mutual pairs it belongs to        (from mutual_pairs.csv;
               each pair contributes +1 to BOTH of its papers; 0 if none).
  - diversity_count, year                                  (from attributes.duckdb)
  - n_cited (only used to define the cohort)               (from edges.csv)

Outputs OUT_CSV (per-year table) and OUT_PNG (the single-line chart).

Env: ATTR, EDGES, PAIRS, OUT_CSV, OUT_PNG, MEM (default 10GB),
     MIN_PAPERS (drop a year with fewer papers than this; default 10000).
"""

import os

import duckdb

ATTR = os.environ.get("ATTR", "data/attributes.duckdb")
EDGES = os.environ.get("EDGES", "data/edges.csv")
PAIRS = os.environ.get("PAIRS", "data/mutual_pairs.csv")
OUT_CSV = os.environ.get(
    "OUT_CSV", "outputs/mean_mutual_vs_diversity/mean_mutual_and_diversity.csv"
)
OUT_PNG = os.environ.get(
    "OUT_PNG", "outputs/mean_mutual_vs_diversity/mean_mutual_and_diversity.png"
)
MEM = os.environ.get("MEM", "10GB")
MIN_PAPERS = int(os.environ.get("MIN_PAPERS", "10000"))
MIN_YEAR = int(os.environ.get("MIN_YEAR", "1975"))
MAX_YEAR = int(os.environ.get("MAX_YEAR", "2023"))


def compute():
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    os.makedirs(os.path.dirname(OUT_CSV) or ".", exist_ok=True)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute(f"ATTACH '{ATTR}' AS a (READ_ONLY)")

    # n_cited per source: DISTINCT cited works minus self-citation (cohort filter).
    con.execute(f"""
        CREATE TEMP TABLE ncited AS
        SELECT CAST(ltrim(source,'W') AS BIGINT) AS id,
               len(list_distinct(string_split(targets,';')))
                 - CASE WHEN list_contains(list_distinct(string_split(targets,';')), source) THEN 1 ELSE 0 END
               AS n_cited
        FROM read_csv('{EDGES}', header=true, all_varchar=true)
    """)

    # n_mutual per paper (each pair counts for both endpoints)
    con.execute(f"""
        CREATE TEMP TABLE nmut AS
        SELECT id, count(*) AS n_mutual FROM (
            SELECT CAST(ltrim(paper_a,'W') AS BIGINT) AS id FROM read_csv('{PAIRS}', header=true, all_varchar=true)
            UNION ALL
            SELECT CAST(ltrim(paper_b,'W') AS BIGINT) AS id FROM read_csv('{PAIRS}', header=true, all_varchar=true)
        ) GROUP BY id
    """)

    # join to year + diversity_count, mean over the cohort, by year.
    # diversity_count used RAW (no 6+ bucketing); 0 included.
    rows = con.execute(f"""
        WITH per_paper AS (
            SELECT att.year AS year,
                   att.diversity_count AS dc,
                   COALESCE(m.n_mutual, 0) AS n_mutual
            FROM ncited c
            JOIN a.attributes att ON CAST(ltrim(att.id,'W') AS BIGINT) = c.id
            LEFT JOIN nmut m ON m.id = c.id
            WHERE c.n_cited >= 1
              AND att.year BETWEEN {MIN_YEAR} AND {MAX_YEAR}
        )
        SELECT year,
               count(*) AS n_papers,
               avg(n_mutual) AS mean_mutual,
               avg(dc) AS mean_diversity
        FROM per_paper
        GROUP BY 1
        ORDER BY 1
    """).fetchall()
    con.close()
    return rows


def write_outputs(rows):
    import csv

    rows = [r for r in rows if r[1] >= MIN_PAPERS]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "n_papers", "mean_mutual"])
        for year, n, mm, md in rows:
            w.writerow([year, n, f"{mm:.6f}"])
    print(f"wrote {OUT_CSV}")

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"(matplotlib unavailable: {e}; wrote CSV only)")
        return

    pts = sorted([(r[0], r[2]) for r in rows])
    xs = [p[0] for p in pts]
    mutual = [p[1] for p in pts]

    fig, ax = plt.subplots(figsize=(12, 7))
    ax.plot(
        xs,
        mutual,
        marker="o",
        markersize=3,
        linewidth=1.6,
        color="C0",
        label="mean mutual citations per paper",
    )
    ax.set_xlabel("Publication year")
    ax.set_ylabel("Mean mutual citations per paper")
    ax.set_title(
        "Mean mutual citations per paper, by year\n" "(papers citing >=1 work)"
    )
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=MIN_YEAR, right=MAX_YEAR)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    print(f"wrote {OUT_PNG}")


def main():
    rows = compute()
    print(f"{'year':>6} {'n_papers':>12} {'mean_mutual':>12}")
    for year, n, mm, md in rows:
        if n >= MIN_PAPERS:
            print(f"{year:>6} {n:>12,} {mm:>12.6f}")
    write_outputs(rows)


if __name__ == "__main__":
    main()
