"""
Mutual-citation rate by year, one line per diversity group.

Per citing paper we need: year, diversity_count, n_cited, n_mutual.
  - n_cited  = number of DISTINCT papers it cites, excluding self (from edges.csv;
               targets are de-duplicated via list_distinct before counting, so a
               work listed twice counts once -- matching mutual_pairs, which is
               also deduped to one row per pair).
  - n_mutual = number of mutual pairs it belongs to        (from mutual_pairs.csv;
               each pair contributes +1 to BOTH of its papers).
  - year, diversity_count                                  (from attributes.duckdb)

Diversity groups: 1,2,3,4,5 each on its own line, plus 6+.
For each (year, group): pooled rate = 100 * sum(n_mutual) / sum(n_cited)
  = of all citations that group made that year, what % were reciprocated.

Mirrors plot_mutual_paper_share_by_diversity.py so the two charts are directly
comparable: same groups (0 excluded), same <10K-cell filter, same labels/legend.

Outputs OUT_CSV (the per-year-per-group table) and OUT_PNG (the line chart).

Env: ATTR, EDGES, PAIRS, OUT_CSV, OUT_PNG, MEM (default 10GB),
     MIN_PAPERS (drop a (year,group) cell with fewer papers than this; default 10000).
"""

import os

import duckdb

ATTR = os.environ.get("ATTR", "data/attributes.duckdb")
EDGES = os.environ.get("EDGES", "data/edges.csv")
PAIRS = os.environ.get("PAIRS", "data/mutual_pairs.csv")
OUT_CSV = os.environ.get(
    "OUT_CSV", "outputs/mutual_citation_rate/mutual_rate_by_diversity.csv"
)
OUT_PNG = os.environ.get(
    "OUT_PNG", "outputs/mutual_citation_rate/rate_by_diversity.png"
)
MEM = os.environ.get("MEM", "10GB")
MIN_PAPERS = int(os.environ.get("MIN_PAPERS", "10000"))
MIN_YEAR = int(os.environ.get("MIN_YEAR", "1975"))
MAX_YEAR = int(os.environ.get("MAX_YEAR", "2023"))
GROUPS = ["1", "2", "3", "4", "5", "6+"]


def compute():
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    os.makedirs(os.path.dirname(OUT_CSV) or ".", exist_ok=True)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute(f"ATTACH '{ATTR}' AS a (READ_ONLY)")

    # n_cited per source: DISTINCT cited works minus self-citation, no unnest.
    # list_distinct dedupes targets so the denominator matches the numerator
    # (mutual_pairs is already deduped to one row per unordered pair).
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

    # join to year + diversity_count, group by (year, diversity group)
    rows = con.execute(f"""
        WITH per_paper AS (
            SELECT att.year AS year, att.diversity_count AS dc,
                   c.n_cited AS n_cited, COALESCE(m.n_mutual, 0) AS n_mutual
            FROM ncited c
            JOIN a.attributes att ON CAST(ltrim(att.id,'W') AS BIGINT) = c.id
            LEFT JOIN nmut m ON m.id = c.id
            WHERE c.n_cited >= 1
              AND att.year BETWEEN {MIN_YEAR} AND {MAX_YEAR}
        )
        SELECT year,
               CASE WHEN dc >= 6 THEN '6+' ELSE CAST(dc AS VARCHAR) END AS grp,
               count(*) AS n_papers,
               sum(n_cited) AS sum_cited,
               sum(n_mutual) AS sum_mutual,
               100.0 * sum(n_mutual) / sum(n_cited) AS rate
        FROM per_paper
        WHERE dc >= 1
        GROUP BY 1, 2
        ORDER BY 1, 2
    """).fetchall()
    con.close()
    return rows


def write_outputs(rows):
    import csv

    rows = [r for r in rows if r[2] >= MIN_PAPERS]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "year",
                "diversity_group",
                "n_papers",
                "sum_cited",
                "sum_mutual",
                "rate_pct",
            ]
        )
        for year, grp, n, sc, sm, rate in rows:
            w.writerow([year, grp, n, sc, sm, f"{rate:.4f}"])
    print(f"wrote {OUT_CSV}")

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"(matplotlib unavailable: {e}; wrote CSV only)")
        return

    fig, ax = plt.subplots(figsize=(12, 7))
    for grp in GROUPS:
        pts = sorted([(r[0], r[5]) for r in rows if r[1] == grp])
        if pts:
            xs, ys = zip(*pts)
            field = "field" if grp == "1" else "fields"
            ax.plot(
                xs,
                ys,
                marker="o",
                markersize=3,
                linewidth=1.6,
                label=f"cites {grp} {field}",
            )
    ax.set_xlabel("Publication year")
    ax.set_ylabel("Mutual-citation rate (% of citations reciprocated)")
    ax.set_title(
        "Mutual-citation rate by year, per diversity group\n"
        "(group 0 + cells <10K papers excluded; pooled rate)"
    )
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=MIN_YEAR, right=MAX_YEAR)
    ax.legend(title="diversity", fontsize=9, loc="upper right", frameon=False)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    print(f"wrote {OUT_PNG}")


def main():
    rows = compute()
    print(
        f"{'year':>6} {'grp':>4} {'n_papers':>12} {'sum_cited':>14} {'sum_mutual':>12} {'rate%':>8}"
    )
    for year, grp, n, sc, sm, rate in rows:
        if n >= MIN_PAPERS:
            print(f"{year:>6} {grp:>4} {n:>12,} {sc:>14,} {sm:>12,} {rate:>8.4f}")
    write_outputs(rows)


if __name__ == "__main__":
    main()
