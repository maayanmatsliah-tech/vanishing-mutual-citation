"""
Calculate and plot mean mutual citations per paper by publication year:
  mean = sum(n_mutual) / count(papers) for papers with n_cited >= 1.

Outputs:
  figures/csvs/mean_mutual_citations_per_year.csv
  figures/graphs/mean_mutual_citations_per_year.png

Env:
  ATTR / NCITED / NMUTUAL  Input paths (default: data/attributes.duckdb, data/_n_cited.csv, data/_n_mutual.csv)
  OUT_CSV / OUT_PNG        Output CSV and PNG plot paths
  MEM                      DuckDB memory limit (default: 10GB)
  MIN_PAPERS               Minimum papers per year to include (default: 10000)
  MIN_YEAR / MAX_YEAR      Year range (default: 1975 to 2023)
"""

import os

import duckdb

ATTR = os.environ.get("ATTR", "data/attributes.duckdb")
NCITED = os.environ.get("NCITED", "data/_n_cited.csv")
NMUTUAL = os.environ.get("NMUTUAL", "data/_n_mutual.csv")

OUT_CSV = os.environ.get("OUT_CSV", "figures/csvs/mean_mutual_citations_per_year.csv")
OUT_PNG = os.environ.get("OUT_PNG", "figures/graphs/mean_mutual_citations_per_year.png")

MEM = os.environ.get("MEM", "10GB")
MIN_PAPERS = int(os.environ.get("MIN_PAPERS", "10000"))
MIN_YEAR = int(os.environ.get("MIN_YEAR", "1975"))
MAX_YEAR = int(os.environ.get("MAX_YEAR", "2023"))


def compute():
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    os.makedirs(os.path.dirname(OUT_CSV) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(OUT_PNG) or ".", exist_ok=True)

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"ATTACH '{ATTR}' AS a (READ_ONLY)")

    # n_cited is already computed. Its presence defines the cohort:
    # papers with n_cited >= 1.
    con.execute(f"""
        CREATE TEMP TABLE ncited AS
        SELECT
            CAST(id AS BIGINT) AS id,
            CAST(n_cited AS BIGINT) AS n_cited
        FROM read_csv('{NCITED}', header=true, all_varchar=true)
        WHERE CAST(n_cited AS BIGINT) >= 1
    """)

    # n_mutual is already computed. Papers absent from this file have
    # zero mutual-citation relationships.
    con.execute(f"""
        CREATE TEMP TABLE nmut AS
        SELECT
            CAST(id AS BIGINT) AS id,
            CAST(n_mutual AS BIGINT) AS n_mutual
        FROM read_csv('{NMUTUAL}', header=true, all_varchar=true)
    """)

    # Join the precomputed metrics to publication year.
    rows = con.execute(f"""
        WITH per_paper AS (
            SELECT
                att.year AS year,
                COALESCE(m.n_mutual, 0) AS n_mutual
            FROM ncited c
            JOIN a.attributes att
              ON CAST(ltrim(att.id, 'W') AS BIGINT) = c.id
            LEFT JOIN nmut m
              ON m.id = c.id
            WHERE att.year BETWEEN {MIN_YEAR} AND {MAX_YEAR}
        )
        SELECT
            year,
            count(*) AS n_papers,
            avg(n_mutual) AS mean_mutual
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

        for year, n, mm in rows:
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

    for year, n, mm in rows:
        if n >= MIN_PAPERS:
            print(f"{year:>6} {n:>12,} {mm:>12.6f}")

    write_outputs(rows)


if __name__ == "__main__":
    main()
