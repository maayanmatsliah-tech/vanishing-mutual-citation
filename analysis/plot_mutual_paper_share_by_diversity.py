"""
Share of papers with ANY mutual citation, by year, one line per diversity group.

Like plot_mutual_by_diversity.py, but the per-(year,group) point is a paper
share rather than a citation rate:

  point = 100 * count(papers that have >=1 mutual citation) / count(all papers)

(plot_mutual_by_diversity.py instead does sum(mutual citations) / sum(citations).)

Per citing paper we need: year, diversity_count, n_cited, n_mutual.
  - n_cited  = number of papers it cites, excluding self  (from edges.csv).
  - n_mutual = number of mutual pairs it belongs to        (from mutual_pairs.csv;
               each pair contributes +1 to BOTH of its papers). A paper "has a
               mutual citation" iff n_mutual >= 1.
  - year, diversity_count                                  (from attributes.duckdb)

Matches the "clean" chart: diversity group 0 excluded, and any (year,group)
cell with fewer than MIN_PAPERS papers dropped.

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
    "OUT_CSV", "outputs/mutual_paper_share/mutual_paper_share_by_diversity.csv"
)
OUT_PNG = os.environ.get(
    "OUT_PNG", "outputs/mutual_paper_share/mutual_paper_share_by_diversity.png"
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

    # n_cited per source (list length minus self-citation), no unnest
    con.execute(f"""
        CREATE TEMP TABLE ncited AS
        SELECT CAST(ltrim(source,'W') AS BIGINT) AS id,
               len(string_split(targets,';'))
                 - CASE WHEN list_contains(string_split(targets,';'), source) THEN 1 ELSE 0 END
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
                   CASE WHEN COALESCE(m.n_mutual, 0) >= 1 THEN 1 ELSE 0 END AS has_mutual
            FROM ncited c
            JOIN a.attributes att ON CAST(ltrim(att.id,'W') AS BIGINT) = c.id
            LEFT JOIN nmut m ON m.id = c.id
            WHERE c.n_cited >= 1
              AND att.year BETWEEN {MIN_YEAR} AND {MAX_YEAR}
        )
        SELECT year,
               CASE WHEN dc >= 6 THEN '6+' ELSE CAST(dc AS VARCHAR) END AS grp,
               count(*) AS n_papers,
               sum(has_mutual) AS n_with_mutual,
               100.0 * sum(has_mutual) / count(*) AS share
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
            ["year", "diversity_group", "n_papers", "n_with_mutual", "share_pct"]
        )
        for year, grp, n, nm, share in rows:
            w.writerow([year, grp, n, nm, f"{share:.4f}"])
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
        pts = sorted([(r[0], r[4]) for r in rows if r[1] == grp])
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
    ax.set_ylabel("Share of papers with any mutual citation (%)")
    ax.set_title(
        "Share of papers with any mutual citation by year, per diversity group\n"
        "(group 0 + cells <10K papers excluded)"
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
        f"{'year':>6} {'grp':>4} {'n_papers':>12} {'n_with_mutual':>14} {'share%':>8}"
    )
    for year, grp, n, nm, share in rows:
        if n >= MIN_PAPERS:
            print(f"{year:>6} {grp:>4} {n:>12,} {nm:>14,} {share:>8.4f}")
    write_outputs(rows)


if __name__ == "__main__":
    main()
