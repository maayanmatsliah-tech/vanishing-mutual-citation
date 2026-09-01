#!/usr/bin/env python3
"""
Mutual-citation rate by publication year.

Uses the precomputed:
  - data/_n_cited.csv
  - data/_n_mutual.csv

Cohort:
  Papers with n_cited 1.

For each year, the pooled mutual-citation rate is:

    rate = 100 * sum(n_mutual) / sum(n_cited)

Interpretation:
  Of all citations made by papers in a given publication year,
  what percentage are reciprocated?

Definitions:
  - n_cited  = precomputed number of distinct papers cited by a paper,
               excluding self-citations.
  - n_mutual = precomputed number of mutual-citation pairs a paper
               belongs to. Each mutual pair contributes +1 to both papers.
  - year     = publication year from attributes.duckdb.

Important:
  This script READS attributes.duckdb but never modifies it.
  It does not recompute n_cited or n_mutual from the large raw files.

Outputs:
  figures/csvs/mutual_citation_rate_per_year.csv
  figures/graphs/mutual_citation_rate_per_year.png

Env:
  ATTR       default data/attributes.duckdb
  NCITED     default data/_n_cited.csv
  NMUTUAL    default data/_n_mutual.csv
  MEM        default 10GB
  MIN_PAPERS default 10000
  MIN_YEAR   default 1975
  MAX_YEAR   default 2023
"""

import os

import duckdb


ATTR = os.environ.get("ATTR", "data/attributes.duckdb")
NCITED = os.environ.get("NCITED", "data/_n_cited.csv")
NMUTUAL = os.environ.get("NMUTUAL", "data/_n_mutual.csv")

OUT_CSV = os.environ.get(
    "OUT_CSV",
    "figures/csvs/mutual_citation_rate_per_year.csv",
)
OUT_PNG = os.environ.get(
    "OUT_PNG",
    "figures/graphs/mutual_citation_rate_per_year.png",
)

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

    # Attach read-only: this script never modifies the attributes database.
    con.execute(f"ATTACH '{ATTR}' AS a (READ_ONLY)")

    print("Loading precomputed n_cited and n_mutual...", flush=True)

    # Only papers with n_cited 1 are part of the cohort.
    #
    # IDs in _n_cited.csv and _n_mutual.csv are already bare integers.
    con.execute(
        f"""
        CREATE TEMP TABLE ncited AS
        SELECT
            CAST(id AS BIGINT) AS id,
            CAST(n_cited AS BIGINT) AS n_cited
        FROM read_csv(
            '{NCITED}',
            header=true,
            all_varchar=true
        )
        WHERE CAST(n_cited AS BIGINT) >= 1
        """
    )

    # Papers absent from _n_mutual.csv have zero mutual citations.
    con.execute(
        f"""
        CREATE TEMP TABLE nmut AS
        SELECT
            CAST(id AS BIGINT) AS id,
            CAST(n_mutual AS BIGINT) AS n_mutual
        FROM read_csv(
            '{NMUTUAL}',
            header=true,
            all_varchar=true
        )
        """
    )

    print("Joining to publication year and aggregating...", flush=True)

    rows = con.execute(
        f"""
        WITH per_paper AS (
            SELECT
                att.year AS year,
                c.id,
                c.n_cited,
                COALESCE(m.n_mutual, 0) AS n_mutual
            FROM ncited c
            JOIN a.attributes att
              ON CAST(ltrim(att.id::VARCHAR, 'W') AS BIGINT) = c.id
            LEFT JOIN nmut m
              ON m.id = c.id
            WHERE att.year BETWEEN {MIN_YEAR} AND {MAX_YEAR}
        )
        SELECT
            year,
            count(*) AS n_papers,
            sum(n_cited) AS sum_cited,
            sum(n_mutual) AS sum_mutual,
            100.0 * sum(n_mutual) / sum(n_cited) AS rate
        FROM per_paper
        GROUP BY year
        ORDER BY year
        """
    ).fetchall()

    con.close()

    return rows


def write_outputs(rows):
    import csv

    # Drop years with too few papers.
    rows = [r for r in rows if r[1] >= MIN_PAPERS]

    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)

        writer.writerow(
            [
                "year",
                "n_papers",
                "sum_cited",
                "sum_mutual",
                "rate_pct",
            ]
        )

        for year, n, sum_cited, sum_mutual, rate in rows:
            writer.writerow(
                [
                    year,
                    n,
                    sum_cited,
                    sum_mutual,
                    f"{rate:.6f}",
                ]
            )

    print(f"wrote {OUT_CSV}")

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

    except Exception as e:
        print(f"(matplotlib unavailable: {e}; wrote CSV only)")
        return

    pts = [(r[0], r[4]) for r in rows]

    fig, ax = plt.subplots(figsize=(12, 7))

    if pts:
        xs, ys = zip(*pts)

        ax.plot(
            xs,
            ys,
            marker="o",
            markersize=3,
            linewidth=1.6,
            color="C0",
        )

    ax.set_xlabel("Publication year")
    ax.set_ylabel("Mutual-citation rate (%)")
    ax.set_title(
        "Mutual-citation rate by publication year\n"
        "(papers citing ≥1 papers)"
    )

    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=MIN_YEAR, right=MAX_YEAR)

    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    plt.close(fig)

    print(f"wrote {OUT_PNG}")


def main():
    rows = compute()

    print()
    print(
        f"{'year':>6} "
        f"{'n_papers':>12} "
        f"{'sum_cited':>14} "
        f"{'sum_mutual':>12} "
        f"{'rate%':>10}"
    )

    for year, n, sum_cited, sum_mutual, rate in rows:
        if n >= MIN_PAPERS:
            print(
                f"{year:>6} "
                f"{n:>12,} "
                f"{sum_cited:>14,} "
                f"{sum_mutual:>12,} "
                f"{rate:>10.6f}"
            )

    write_outputs(rows)


if __name__ == "__main__":
    main()
