"""
Script 2 of 2 — the (light) pooled-ratio calculation.

Reads the compact per-paper counts from build_mutual_counts.py and computes, for
each (year, diverse-group), the POOLED mutual-citation share:

    pct_mutual = 100 * sum(n_mutual) / sum(n_cited)

i.e. of all the citations made by that group in that year, what fraction are
reciprocated. Pooling (summing counts before dividing) weights each citation
equally instead of each paper, so single-citation papers can no longer swing the
value to 0%/100% -- the small-denominator skew is gone.

This is a streaming aggregation: only (years x 2 groups) accumulators are kept,
so memory is negligible regardless of input size.

Output (OUT_YEAR): one row per (year, diverse) with
  year, diverse, n_papers, sum_cited, sum_mutual, pct_mutual
This is the table the two-line graph plots (x=year, one line per diverse group).

Env
  COUNTS    per-paper counts CSV from script 1 (default data/mutual_counts_per_paper.csv)
  OUT_YEAR  per-year output (default outputs/mutual_share_by_diversity_per_year.csv)
"""

import csv
import os
from collections import defaultdict

COUNTS = os.environ.get("COUNTS", "data/mutual_counts_per_paper.csv")
OUT_YEAR = os.environ.get("OUT_YEAR", "outputs/mutual_share_by_diversity_per_year.csv")


def truthy(s):
    return s.strip().lower() in ("true", "t", "1")


def main():
    os.makedirs(os.path.dirname(OUT_YEAR) or ".", exist_ok=True)

    # key (year, diverse) -> [n_papers, sum_cited, sum_mutual]
    agg = defaultdict(lambda: [0, 0, 0])
    with open(COUNTS, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            year = int(row["year"])
            diverse = truthy(row["diverse"])
            a = agg[(year, diverse)]
            a[0] += 1
            a[1] += int(row["n_cited"])
            a[2] += int(row["n_mutual"])

    rows = []
    for (year, diverse), (n_papers, sum_cited, sum_mutual) in agg.items():
        pct = (100.0 * sum_mutual / sum_cited) if sum_cited else None
        rows.append((year, diverse, n_papers, sum_cited, sum_mutual, pct))
    rows.sort(key=lambda x: (x[0], x[1]))

    with open(OUT_YEAR, "w", newline="", encoding="utf-8") as g:
        w = csv.writer(g)
        w.writerow(["year", "diverse", "n_papers", "sum_cited", "sum_mutual", "pct_mutual"])
        for year, diverse, n_papers, sum_cited, sum_mutual, pct in rows:
            w.writerow([year, diverse, n_papers, sum_cited, sum_mutual,
                        "" if pct is None else f"{pct:.6f}"])

    # console preview
    print(f"wrote {OUT_YEAR}\n")
    print(f"{'year':>6} {'group':>12} {'n_papers':>12} {'sum_cited':>14} "
          f"{'sum_mutual':>12} {'pct_mutual':>10}")
    for year, diverse, n_papers, sum_cited, sum_mutual, pct in rows:
        label = "diverse" if diverse else "non-diverse"
        pct_s = "n/a" if pct is None else f"{pct:.4f}%"
        print(f"{year:>6} {label:>12} {n_papers:>12,} {sum_cited:>14,} "
              f"{sum_mutual:>12,} {pct_s:>10}")


if __name__ == "__main__":
    main()
