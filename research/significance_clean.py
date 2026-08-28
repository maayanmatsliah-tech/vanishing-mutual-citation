"""
Significance tests on the clean dataset (data/clean_dataset.duckdb,
1950-2025, 10k papers per year), testing a structural break at June 2021.

Resolution note: the clean dataset has only publication_year, not
publication_date. "June 2021" cannot be tested at sub-year precision
here; the closest yearly approximation is splitting at the year
boundary. This script uses Pre = years <= 2020, Post = years >= 2021
(treats 2021 as fully post-event, since June 2021 is mid-year and most
2021 papers were written/published after that point).

Tests run:
  1. Per-year mutual citation rate table
  2. Log-rate trajectory fits on multiple windows
  3. Chow test for structural break at end of 2020 (i.e., 2021 = first
     post-event year) - the closest yearly approximation to June 2021
  4. Placebo Chow sweep across all candidate break dates
  5. Pre vs post (2018-2020 vs 2021-2025) chi-square on paper-level
     mutual participation

2025 caveat: OpenAlex 2025 coverage is incomplete (some papers still
being indexed), so 2025 may have a lower observed rate than will
eventually be visible.

Inputs:
  data/clean_dataset.duckdb (with papers and edges tables)

Outputs:
  prints results to stdout
  saves outputs/clean_trajectory_june2021.png
"""

import duckdb
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.stats import linregress, f as f_dist, chi2_contingency

PAPERS_PARQUET = "data/papers.parquet"
EDGES_PARQUET = "data/edges.parquet"
OUT_PNG = "outputs/clean_trajectory_june2021.png"

# break boundary: "after end-of-2020" means 2021 is the first post-event year
# (closest yearly approximation to "June 2021")
BREAK_AFTER_YEAR = 2020
BREAK_LABEL = "June 2021 (= after end of 2020 at yearly resolution)"

# Use an in-memory DuckDB and read the Parquet exports directly, so this
# script can run while data/backfill_cited_fields.py holds a lock on the
# .duckdb file. The Parquet files are not touched by the backfill.
con = duckdb.connect(":memory:")
con.execute(f"CREATE VIEW papers AS SELECT * FROM read_parquet('{PAPERS_PARQUET}')")
con.execute(f"CREATE VIEW edges  AS SELECT * FROM read_parquet('{EDGES_PARQUET}')")

# ---------- pull pairs per year + paper counts ----------
print("Querying mutual pairs by year...")
rows = con.execute("""
    WITH mutual_pairs AS (
        SELECT a.source AS p1, a.target AS p2
        FROM edges a
        JOIN edges b ON a.source = b.target AND a.target = b.source
        WHERE a.source < a.target
    )
    SELECT
        GREATEST(w1.year, w2.year) AS year,
        COUNT(*) AS mutual_pairs
    FROM mutual_pairs m
    JOIN papers w1 ON m.p1 = w1.id
    JOIN papers w2 ON m.p2 = w2.id
    GROUP BY GREATEST(w1.year, w2.year)
    ORDER BY year
""").fetchall()

paper_counts = dict(con.execute(
    "SELECT year, COUNT(*) FROM papers GROUP BY year ORDER BY year"
).fetchall())

per_year = {}
for y, n in rows:
    if y in paper_counts:
        per_year[y] = {
            "pairs": n,
            "papers": paper_counts[y],
            "rate": n / paper_counts[y] * 1000,
        }

# also compute paper-level participation
print("Querying paper-level mutual participation...")
participation = dict(con.execute("""
    WITH mutual_pairs AS (
        SELECT a.source AS p1, a.target AS p2
        FROM edges a
        JOIN edges b ON a.source = b.target AND a.target = b.source
        WHERE a.source < a.target
    ),
    paper_in_any AS (
        SELECT DISTINCT p1 AS pid FROM mutual_pairs
        UNION
        SELECT DISTINCT p2 FROM mutual_pairs
    )
    SELECT w.year, COUNT(*) AS in_mutual
    FROM paper_in_any pi
    JOIN papers w ON pi.pid = w.id
    GROUP BY w.year ORDER BY w.year
""").fetchall())

# ---------- summary table ----------
print(f"\n{'year':<6}{'pairs':>10}{'papers':>10}{'rate/1000':>12}{'papers_in_mutual':>20}")
print("-" * 58)
for y in sorted(per_year):
    d = per_year[y]
    in_m = participation.get(y, 0)
    flag = ""
    if y == 2025:
        flag = "  (2025 coverage incomplete)"
    print(f"{y:<6}{d['pairs']:>10,}{d['papers']:>10,}{d['rate']:>11.2f} {in_m:>15,}{flag}")


# ---------- trajectory fits on multiple windows ----------
def fit_window(start, end, label):
    ys = [y for y in sorted(per_year) if start <= y <= end and per_year[y]["rate"] > 0]
    if len(ys) < 4:
        print(f"  {label}: not enough data ({len(ys)} years)")
        return None
    rs = np.array([per_year[y]["rate"] for y in ys])
    log_r = np.log(rs)
    x = np.array(ys, dtype=float)
    fit = linregress(x, log_r)
    ann_pct = (np.exp(fit.slope) - 1) * 100
    print(f"  {label:30s}  n={len(ys):>2}  {ann_pct:>+7.1f}%/yr  "
          f"R²={fit.rvalue**2:.3f}  slope p={fit.pvalue:.4g}")
    return fit, ys, rs


print("\n" + "=" * 78)
print("TRAJECTORY FITS (log-rate vs year)")
print("=" * 78)
fits = {}
for start, end, label in [
    (1950, 2025, "Full window 1950-2025"),
    (2000, 2025, "Modern window 2000-2025"),
    (2015, 2025, "Decade 2015-2025"),
    (2018, 2025, "Tight pre+post 2018-2025"),
    (2015, 2022, "Pre-ChatGPT only 2015-2022"),
    (2023, 2025, "Post-ChatGPT only 2023-2025"),
]:
    res = fit_window(start, end, label)
    if res is not None:
        fits[label] = res


# ---------- Chow test for structural break at end of 2020 (proxy for June 2021) ----------
print("\n" + "=" * 78)
print(f"CHOW TEST: structural break at {BREAK_LABEL}")
print("=" * 78)


def chow_yearly(start, end, break_after_year):
    ys = [y for y in sorted(per_year) if start <= y <= end and per_year[y]["rate"] > 0]
    rs = np.array([per_year[y]["rate"] for y in ys])
    if (rs <= 0).any():
        return None
    log_r = np.log(rs)
    x = np.array(ys, dtype=float)
    bp = next((i for i, y in enumerate(ys) if y > break_after_year), None)
    if bp is None or bp < 3 or len(ys) - bp < 3:
        return None
    k = 2  # intercept + slope
    n = len(ys)
    f_all = linregress(x, log_r)
    f1 = linregress(x[:bp], log_r[:bp])
    f2 = linregress(x[bp:], log_r[bp:])
    ssr_c = float(np.sum((log_r - (f_all.slope * x + f_all.intercept)) ** 2))
    ssr1 = float(np.sum((log_r[:bp] - (f1.slope * x[:bp] + f1.intercept)) ** 2))
    ssr2 = float(np.sum((log_r[bp:] - (f2.slope * x[bp:] + f2.intercept)) ** 2))
    F = ((ssr_c - (ssr1 + ssr2)) / k) / ((ssr1 + ssr2) / (n - 2 * k))
    p = 1 - f_dist.cdf(F, k, n - 2 * k)
    pre_ann = (np.exp(f1.slope) - 1) * 100
    post_ann = (np.exp(f2.slope) - 1) * 100
    return F, p, pre_ann, post_ann, bp, len(ys) - bp


for start, end in [(2010, 2025), (2015, 2025), (2017, 2025)]:
    res = chow_yearly(start, end, BREAK_AFTER_YEAR)
    if res is None:
        print(f"  {start}-{end}: not enough data")
        continue
    F, p, pre, post, n_pre, n_post = res
    sig = "*** break ***" if p < 0.05 else "no break"
    print(f"  window {start}-{end}  pre n={n_pre} post n={n_post}  "
          f"pre {pre:+6.1f}%/yr  post {post:+6.1f}%/yr  F={F:.2f}  p={p:.4f}  {sig}")


# ---------- placebo Chow sweep ----------
print("\n" + "=" * 78)
print("PLACEBO CHOW SWEEP: does the test fire at many dates? (specificity check)")
print("=" * 78)

# use the 2010-2025 window (16 years)
window_start, window_end = 2010, 2025
ys = [y for y in sorted(per_year) if window_start <= y <= window_end and per_year[y]["rate"] > 0]
rs = np.array([per_year[y]["rate"] for y in ys])
log_r = np.log(rs)
x = np.array(ys, dtype=float)
n = len(ys)
k = 2
f_all = linregress(x, log_r)
ssr_c = float(np.sum((log_r - (f_all.slope * x + f_all.intercept)) ** 2))

print(f"\nWindow {window_start}-{window_end} (n={n})")
print(f"{'break_after':<12}{'pre_n':>6}{'post_n':>7}{'F':>8}{'p':>8}{'sig':>6}")
results = []
for break_after in range(window_start + 3, window_end - 2):
    bp = next((i for i, y in enumerate(ys) if y > break_after), None)
    if bp is None or bp < 3 or len(ys) - bp < 3:
        continue
    f1 = linregress(x[:bp], log_r[:bp])
    f2 = linregress(x[bp:], log_r[bp:])
    ssr1 = float(np.sum((log_r[:bp] - (f1.slope * x[:bp] + f1.intercept)) ** 2))
    ssr2 = float(np.sum((log_r[bp:] - (f2.slope * x[bp:] + f2.intercept)) ** 2))
    F = ((ssr_c - (ssr1 + ssr2)) / k) / ((ssr1 + ssr2) / (n - 2 * k))
    p = 1 - f_dist.cdf(F, k, n - 2 * k)
    sig = "***" if p < 0.05 else ""
    marker = "  <-- ChatGPT" if break_after == 2022 else ""
    print(f"  {break_after:<10}{bp:>6}{len(ys)-bp:>7}{F:>8.2f}{p:>8.4f}{sig:>6}{marker}")
    results.append((break_after, F, p))

sig_count = sum(1 for _, _, p in results if p < 0.05)
print(f"\n{sig_count} of {len(results)} candidate break-after years fire at p<0.05")

target_rank = next((i + 1 for i, t in enumerate(sorted(results, key=lambda r: -r[1]))
                    if t[0] == BREAK_AFTER_YEAR), None)
if target_rank:
    print(f"Target (break-after-{BREAK_AFTER_YEAR}) ranks {target_rank} of {len(results)} by F.")


# ---------- pre vs post chi-square on paper-level participation ----------
print("\n" + "=" * 78)
print(f"PRE vs POST chi-square on paper-level mutual participation")
print(f"  break = {BREAK_LABEL}")
print("=" * 78)

PRE_YEARS = [2018, 2019, 2020]
POST_YEARS = [2021, 2022, 2023, 2024, 2025]
pre_in = sum(participation.get(y, 0) for y in PRE_YEARS)
pre_n = sum(paper_counts.get(y, 0) for y in PRE_YEARS)
post_in = sum(participation.get(y, 0) for y in POST_YEARS)
post_n = sum(paper_counts.get(y, 0) for y in POST_YEARS)

print(f"  Pre  ({PRE_YEARS}):  {pre_in:,} in mutual / {pre_n:,} papers = "
      f"{pre_in/pre_n*1000:.2f} per 1000")
print(f"  Post ({POST_YEARS}):  {post_in:,} in mutual / {post_n:,} papers = "
      f"{post_in/post_n*1000:.2f} per 1000")

table = np.array([
    [pre_in, pre_n - pre_in],
    [post_in, post_n - post_in],
])
chi2, p_chi, dof, _ = chi2_contingency(table)
print(f"  Chi-square = {chi2:.2f},  p = {p_chi:.2e}")
if p_chi < 0.05:
    direction = "decrease" if post_in / post_n < pre_in / pre_n else "increase"
    print(f"  *** statistically significant {direction} post-{BREAK_AFTER_YEAR} ***")
else:
    print(f"  No significant difference")
print("\n  (Reminder: at n ~ 30k, chi-square detects sub-percentage-point differences;")
print("   p-value reflects sample size more than effect size. See trajectory tests above.)")


# ---------- chart ----------
fig, ax = plt.subplots(figsize=(13, 6))

all_years = sorted(per_year)
all_rates = [per_year[y]["rate"] for y in all_years]

ax.plot(all_years, all_rates, "o-", color="steelblue", markersize=4, linewidth=1.2,
        label="Mutual pair rate per 1000 papers")

# Highlight 2010-2025 fit and pre/post Chow if exists
if "Decade 2015-2025" in fits:
    fit, ys, rs = fits["Decade 2015-2025"]
    trend_x = np.linspace(min(ys), max(ys), 100)
    trend_y = np.exp(fit.slope * trend_x + fit.intercept)
    ann_pct = (np.exp(fit.slope) - 1) * 100
    ax.plot(trend_x, trend_y, "--", color="orange", linewidth=2,
            label=f"2015-2025 trend ({ann_pct:+.1f}%/yr)")

ax.axvline(x=2021.42, color="red", linestyle=":", linewidth=1.5,
           label="Candidate break: June 2021")

ax.set_xlabel("Year")
ax.set_ylabel("Mutual pairs per 1000 papers")
ax.set_title("Clean dataset (1950-2025): mutual citation rate trajectory\n"
             "Break candidate: June 2021 (yearly approximation)")
ax.set_yscale("log")
ax.grid(True, alpha=0.3, which="both")
ax.legend()

plt.tight_layout()
Path("outputs").mkdir(exist_ok=True)
plt.savefig(OUT_PNG, dpi=150)
print(f"\nSaved {OUT_PNG}")
