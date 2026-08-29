"""
Citation-lag distribution for mutual pairs -- the censoring check cited in Methods.

For each mutual pair {A, B}, computes the gap between the two papers'
publication years: abs(year_A - year_B). Reports the cumulative share of pairs
whose gap is 0 (same year), <=1, <=2, and <=3 years, which bounds how much of
the corpus's tail years are affected by right-censoring at the 2023 cutoff --
a pair can only be observed as mutual once BOTH papers exist, so a pair formed
late in the corpus has less time to complete than one formed decades earlier.

Env: PAIRS (default data/mutual_pairs.csv), ATTR (default data/attributes.duckdb),
     OUT (default outputs/citation_lag/citation_lag_distribution.csv),
     MEM (default 10GB).
"""

import os

import duckdb

PAIRS = os.environ.get("PAIRS", "data/mutual_pairs.csv")
ATTR = os.environ.get("ATTR", "data/attributes.duckdb")
OUT = os.environ.get("OUT", "outputs/citation_lag/citation_lag_distribution.csv")
MEM = os.environ.get("MEM", "10GB")


def compute():
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute(f"ATTACH '{ATTR}' AS a (READ_ONLY)")

    # Join each pair to both papers' years and compute the gap.
    con.execute(f"""
        CREATE TEMP TABLE pair_years AS
        SELECT ya.year AS year_a, yb.year AS year_b,
               abs(ya.year - yb.year) AS gap
        FROM read_csv('{PAIRS}', header=true, all_varchar=true) p
        JOIN a.attributes ya ON ya.id = p.paper_a
        JOIN a.attributes yb ON yb.id = p.paper_b
    """)

    n_total = con.execute("SELECT count(*) FROM pair_years").fetchone()[0]

    # Cumulative share of pairs completing within 0/1/2/3 years of each other.
    rows = con.execute("""
        SELECT
            sum(CASE WHEN gap = 0 THEN 1 ELSE 0 END)                         AS n_within_0,
            sum(CASE WHEN gap <= 1 THEN 1 ELSE 0 END)                        AS n_within_1,
            sum(CASE WHEN gap <= 2 THEN 1 ELSE 0 END)                        AS n_within_2,
            sum(CASE WHEN gap <= 3 THEN 1 ELSE 0 END)                        AS n_within_3,
            count(*)                                                        AS n_total
        FROM pair_years
    """).fetchone()
    con.close()
    return rows


def write_outputs(rows):
    import csv

    n0, n1, n2, n3, n_total = rows
    labels = ["same_year", "within_1_year", "within_2_years", "within_3_years"]
    counts = [n0, n1, n2, n3]

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["threshold", "n_pairs", "n_total", "cumulative_pct"])
        for label, n in zip(labels, counts):
            pct = 100.0 * n / n_total if n_total else 0.0
            w.writerow([label, n, n_total, f"{pct:.4f}"])
    print(f"wrote {OUT}")


def main():
    rows = compute()
    n0, n1, n2, n3, n_total = rows
    print(f"total mutual pairs: {n_total:,}\n")
    print(f"{'threshold':>16} {'n_pairs':>12} {'cumulative_pct':>16}")
    for label, n in zip(
        ["same year", "within 1 year", "within 2 years", "within 3 years"],
        [n0, n1, n2, n3],
    ):
        pct = 100.0 * n / n_total if n_total else 0.0
        print(f"{label:>16} {n:>12,} {pct:>15.1f}%")
    write_outputs(rows)


if __name__ == "__main__":
    main()