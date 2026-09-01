#!/usr/bin/env python3
"""
Reference-count decile analysis with value-based bins.

Cohort:
  Papers with n_cited >= 3 AND published in [MIN_YEAR, MAX_YEAR] (default
  1975-2023).

  The 2023 cap matters: cleaning only dropped field='Unknown', so ~15.5M
  papers dated 2024-2025 survive in attributes.duckdb with a real field.
  Uncapped they were 12.9% of this cohort, and they are heavily
  right-censored -- a 2024/2025 paper contributes its full n_cited but its
  reciprocal citations mostly postdate the snapshot, so n_mutual is
  systematically depressed. That biases the mutual rate downward, and it
  does so unevenly across deciles.

  The deciles are computed AFTER this filter, so the bins describe the
  analysed population rather than being inherited from a wider one.

Decile definition:
  Papers with the same n_cited value MUST remain in the same decile.

  We therefore:
    1. Count papers at each distinct n_cited value.
    2. Treat each distinct n_cited value as an indivisible block.
    3. Assign the block using the midpoint of its position in the
       cumulative paper distribution.
    4. Map that midpoint to deciles 1-10.

  This produces approximately equal-sized deciles while ensuring that
  identical n_cited values are never split across deciles.

Diversity grouping:
  diversity_count 1-2 -> non-diverse
  diversity_count 3+  -> diverse
  diversity_count 0   -> excluded

Inputs:
  data/_n_cited.csv
  data/_n_mutual.csv
  data/attributes.duckdb

Env:
  MIN_YEAR  default 1975
  MAX_YEAR  default 2023

Outputs:
  figures/csvs/refcount_decile_dvn_share.csv
  figures/csvs/refcount_decile_dvn_rate.csv
  figures/graphs/refcount_decile_dvn_share.png
  figures/graphs/refcount_decile_dvn_rate.png

The attributes database is opened READ_ONLY and is never modified.
"""

import os
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = ROOT / "data" / "attributes.duckdb"
NC_PATH = ROOT / "data" / "_n_cited.csv"
NM_PATH = ROOT / "data" / "_n_mutual.csv"

DUCKDB_TMP = ROOT / "data" / "_duckdb_tmp"

OUT_CSV_DIR = ROOT / "figures" / "csvs"
OUT_GRAPH_DIR = ROOT / "figures" / "graphs"

MIN_YEAR = int(os.environ.get("MIN_YEAR", "1975"))
MAX_YEAR = int(os.environ.get("MAX_YEAR", "2023"))


def compute_share_and_rate():
    OUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
    OUT_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    DUCKDB_TMP.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        con.execute("SET enable_progress_bar=false")
        con.execute("SET preserve_insertion_order=false")
        con.execute(f"SET temp_directory='{DUCKDB_TMP}'")

        print("Loading and aggregating papers in DuckDB...", flush=True)

        # ------------------------------------------------------------------
        # 1. Build the paper-level cohort.
        #
        # ONLY n_cited >= 3 AND year in [MIN_YEAR, MAX_YEAR] enters the
        # analysis. The year bound excludes the right-censored 2024/2025
        # papers that survived cleaning (see module docstring); it is applied
        # here, before deciles are computed, so the bins are derived from the
        # analysed population.
        #
        # Cast both CSV IDs and n_cited explicitly because read_csv with
        # all_varchar=true returns VARCHAR columns.
        # ------------------------------------------------------------------

        # in_window: everything inside the year bound, BEFORE the n_cited cut,
        # so the "excluded because n_cited < 3" diagnostic below is scoped to
        # the same population rather than silently counting other years too.
        con.execute(
            """
            CREATE TEMP TABLE in_window AS
            SELECT
                CAST(nc.id AS BIGINT) AS id,
                CAST(nc.n_cited AS BIGINT) AS n_cited,
                COALESCE(CAST(nm.n_mutual AS BIGINT), 0) AS n_mutual,
                a.year,
                CAST(a.diversity_count AS BIGINT) AS diversity_count
            FROM read_csv(
                ?,
                header=true,
                all_varchar=true
            ) nc
            JOIN attributes a
              ON CAST(ltrim(a.id::VARCHAR, 'W') AS BIGINT)
               = CAST(nc.id AS BIGINT)
            LEFT JOIN read_csv(
                ?,
                header=true,
                all_varchar=true
            ) nm
              ON CAST(nm.id AS BIGINT) = CAST(nc.id AS BIGINT)
            WHERE a.year BETWEEN ? AND ?
            """,
            [str(NC_PATH), str(NM_PATH), MIN_YEAR, MAX_YEAR],
        )

        con.execute("""
            CREATE TEMP TABLE papers AS
            SELECT * FROM in_window WHERE n_cited >= 3
            """)

        # ------------------------------------------------------------------
        # 2. Count papers at every distinct n_cited value.
        # ------------------------------------------------------------------

        con.execute("""
            CREATE TEMP TABLE value_counts AS
            SELECT
                n_cited,
                COUNT(*) AS n_papers
            FROM papers
            GROUP BY n_cited
            ORDER BY n_cited
            """)

        # ------------------------------------------------------------------
        # 3. Assign value-based deciles.
        #
        # IMPORTANT:
        #   The midpoint of each n_cited block is used.
        #
        # Example:
        #   if a particular n_cited value accounts for papers 9%-12% of
        #   the cohort, its midpoint is 10.5%, so that entire value is
        #   assigned to decile 1 rather than being pushed wholly into
        #   decile 2 just because its upper edge crossed 10%.
        #
        # No distinct n_cited value can ever be split.
        # ------------------------------------------------------------------

        con.execute("""
            CREATE TEMP TABLE value_deciles AS
            WITH positioned AS (
                SELECT
                    n_cited,
                    n_papers,

                    COALESCE(
                        SUM(n_papers) OVER (
                            ORDER BY n_cited
                            ROWS BETWEEN UNBOUNDED PRECEDING
                                 AND 1 PRECEDING
                        ),
                        0
                    ) AS papers_before,

                    SUM(n_papers) OVER () AS total_papers

                FROM value_counts
            ),
            midpoint AS (
                SELECT
                    n_cited,
                    n_papers,
                    total_papers,

                    (
                        papers_before + n_papers / 2.0
                    ) / total_papers AS midpoint_fraction

                FROM positioned
            )
            SELECT
                n_cited,
                n_papers,
                LEAST(
                    10,
                    GREATEST(
                        1,
                        CAST(
                            FLOOR(midpoint_fraction * 10.0)
                            AS INTEGER
                        ) + 1
                    )
                ) AS decile
            FROM midpoint
            """)

        # ------------------------------------------------------------------
        # 4. Join the decile back to every paper.
        # ------------------------------------------------------------------

        con.execute("""
            CREATE TEMP TABLE grouped AS
            SELECT
                p.id,
                p.n_cited,
                p.n_mutual,
                d.decile,
                CASE
                    WHEN p.diversity_count BETWEEN 1 AND 2
                        THEN 'non-diverse'
                    WHEN p.diversity_count >= 3
                        THEN 'diverse'
                    ELSE NULL
                END AS group_name
            FROM papers p
            JOIN value_deciles d
              ON p.n_cited = d.n_cited
            """)

        # ------------------------------------------------------------------
        # 5. Share of papers with any mutual citation.
        # ------------------------------------------------------------------

        share = con.execute("""
            SELECT
                decile,
                group_name AS group,
                COUNT(*) AS n_papers,
                SUM(
                    CASE
                        WHEN n_mutual > 0 THEN 1
                        ELSE 0
                    END
                ) AS n_with_mutual,
                100.0
                * SUM(
                    CASE
                        WHEN n_mutual > 0 THEN 1
                        ELSE 0
                    END
                )
                / COUNT(*) AS share_pct
            FROM grouped
            WHERE group_name IS NOT NULL
            GROUP BY decile, group_name
            ORDER BY decile, group_name
            """).fetch_df()

        # ------------------------------------------------------------------
        # 6. Mutual-citation rate.
        #
        # Pooled rate:
        #   sum(n_mutual) / sum(n_cited)
        #
        # This is NOT the mean of per-paper rates.
        # ------------------------------------------------------------------

        rate = con.execute("""
            SELECT
                decile,
                group_name AS group,
                COUNT(*) AS n_papers,
                SUM(CAST(n_cited AS BIGINT)) AS sum_cited,
                SUM(CAST(n_mutual AS BIGINT)) AS sum_mutual,
                100.0
                * SUM(CAST(n_mutual AS BIGINT))
                / NULLIF(
                    SUM(CAST(n_cited AS BIGINT)),
                    0
                ) AS rate_pct
            FROM grouped
            WHERE group_name IS NOT NULL
            GROUP BY decile, group_name
            ORDER BY decile, group_name
            """).fetch_df()

        # ------------------------------------------------------------------
        # 7. Validation / diagnostics.
        # ------------------------------------------------------------------

        n_total = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

        n_under_3 = con.execute("""
            SELECT COUNT(*)
            FROM in_window
            WHERE n_cited < 3
            """).fetchone()[0]

        # Papers that would have entered the cohort but for the year bound.
        # Derived by subtraction rather than a second join: validate_data.py
        # confirms every edges.csv source resolves in attributes, so the
        # all-years n_cited>=3 count needs no join to be comparable.
        n_ge3_all_years = con.execute(
            """
            SELECT COUNT(*)
            FROM read_csv(
                ?,
                header=true,
                all_varchar=true
            )
            WHERE CAST(n_cited AS BIGINT) >= 3
            """,
            [str(NC_PATH)],
        ).fetchone()[0]
        n_year_excluded = n_ge3_all_years - n_total

        n_zero_diversity = con.execute("""
            SELECT COUNT(*)
            FROM papers
            WHERE diversity_count = 0
            """).fetchone()[0]

        # Every n_cited value must map to exactly one decile.
        n_split = con.execute("""
            SELECT COUNT(*)
            FROM (
                SELECT
                    n_cited,
                    COUNT(DISTINCT decile) AS n_deciles
                FROM grouped
                GROUP BY n_cited
                HAVING COUNT(DISTINCT decile) > 1
            )
            """).fetchone()[0]

        # Overall paper count by decile, BEFORE diversity exclusion.
        decile_sizes = con.execute("""
            SELECT
                decile,
                COUNT(*) AS n_papers
            FROM grouped
            GROUP BY decile
            ORDER BY decile
            """).fetchall()

    finally:
        con.close()

    print()
    print(f"year window: {MIN_YEAR}-{MAX_YEAR}")
    print(f"papers included (n_cited >= 3, in window): {n_total:,}")
    print(
        f"papers excluded by the year bound (n_cited >= 3, outside window): "
        f"{n_year_excluded:,}"
    )
    print(f"papers excluded because n_cited < 3 (in window): {n_under_3:,}")
    print(
        "diversity_count=0 papers excluded from "
        f"diverse/non-diverse comparison: {n_zero_diversity:,}"
    )
    print(f"n_cited values split across multiple deciles: {n_split}")

    print()
    print("Paper counts by value-based decile:")
    print(f"{'decile':>8} {'n_papers':>14} {'share':>10}")

    for decile, n_papers in decile_sizes:
        pct = 100.0 * n_papers / n_total
        print(f"{decile:>8} " f"{n_papers:>14,} " f"{pct:>9.2f}%")

    return share, rate


def write_outputs(share: pd.DataFrame, rate: pd.DataFrame):
    share_csv = OUT_CSV_DIR / "refcount_decile_dvn_share.csv"
    share_png = OUT_GRAPH_DIR / "refcount_decile_dvn_share.png"

    rate_csv = OUT_CSV_DIR / "refcount_decile_dvn_rate.csv"
    rate_png = OUT_GRAPH_DIR / "refcount_decile_dvn_rate.png"

    share.to_csv(share_csv, index=False)
    rate.to_csv(rate_csv, index=False)

    # ----------------------------------------------------------------------
    # Share plot
    # ----------------------------------------------------------------------

    fig, ax = plt.subplots(figsize=(10, 6))

    for group in ["non-diverse", "diverse"]:
        sub = share[share["group"] == group].sort_values("decile")

        ax.plot(
            sub["decile"],
            sub["share_pct"],
            marker="o",
            linewidth=2,
            label=group,
        )

    ax.set_xlim(0.5, 10.5)
    ax.set_xticks(range(1, 11))
    ax.set_xlabel("Reference-count decile")
    ax.set_ylabel("Share of papers with any mutual citation (%)")
    ax.set_title(
        "Share of papers with any mutual citation "
        "by reference-count decile\n"
        "(papers citing 3+ papers)"
    )
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(title="Group")

    fig.tight_layout()
    fig.savefig(share_png, dpi=200)
    plt.close(fig)

    # ----------------------------------------------------------------------
    # Rate plot
    # ----------------------------------------------------------------------

    fig, ax = plt.subplots(figsize=(10, 6))

    for group in ["non-diverse", "diverse"]:
        sub = rate[rate["group"] == group].sort_values("decile")

        ax.plot(
            sub["decile"],
            sub["rate_pct"],
            marker="o",
            linewidth=2,
            label=group,
        )

    ax.set_xlim(0.5, 10.5)
    ax.set_xticks(range(1, 11))
    ax.set_xlabel("Reference-count decile")
    ax.set_ylabel("Mutual-citation rate (% of references reciprocated)")
    ax.set_title(
        "Mutual-citation rate by reference-count decile\n" "(papers citing 3+ papers)"
    )
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(title="Group")

    fig.tight_layout()
    fig.savefig(rate_png, dpi=200)
    plt.close(fig)

    print()
    print(f"share csv: {share_csv}")
    print(f"rate csv:  {rate_csv}")
    print(f"share png: {share_png}")
    print(f"rate png:  {rate_png}")


def main():
    share, rate = compute_share_and_rate()
    write_outputs(share, rate)


if __name__ == "__main__":
    main()
