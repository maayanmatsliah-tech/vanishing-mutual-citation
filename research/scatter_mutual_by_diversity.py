"""
Clean visualization: yearly mean percent of citations that are mutual,
split by diversity (cites 3+ distinct fields = diverse).

For each paper with at least one outbound edge:
  pct_mutual = (# of outbound edges that are part of a mutual pair)
              / (total outbound edges) * 100

Aggregated per year per group (diverse vs not-diverse). Two lines with
shaded ±1 SE bands. The pattern of interest — non-diverse papers showing
systematically higher mutual share than diverse papers — is the
distance between the two lines.

Inputs:
  data/clean_dataset.duckdb (with papers.diverse populated)

Outputs:
  outputs/mutual_share_by_diversity.png
  prints summary stats
"""

import duckdb
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
from pathlib import Path

DB = "data/clean_dataset.duckdb"
OUT = "outputs/mutual_share_by_diversity.png"

con = duckdb.connect(DB, read_only=True)

cols = [r[0] for r in con.execute("DESCRIBE papers").fetchall()]
if "diverse" not in cols:
    raise SystemExit(
        "papers.diverse column not found. Run research/classify_diversity.py first."
    )

print("Computing per-paper mutual-edge counts...")
rows = con.execute("""
    WITH mutual_edges AS (
        SELECT a.source, a.target FROM edges a
        JOIN edges b ON a.source = b.target AND a.target = b.source
    ),
    out_counts AS (
        SELECT source AS pid, COUNT(*) AS n_out FROM edges GROUP BY source
    ),
    mut_counts AS (
        SELECT source AS pid, COUNT(*) AS n_mut FROM mutual_edges GROUP BY source
    )
    SELECT p.year, p.diverse, o.n_out, COALESCE(m.n_mut, 0) AS n_mut
    FROM papers p
    JOIN out_counts o ON o.pid = p.id
    LEFT JOIN mut_counts m ON m.pid = p.id
    WHERE p.year IS NOT NULL AND o.n_out > 0
""").fetchall()

# Group per-paper pct_mutual values by (year, diverse)
data = defaultdict(lambda: {"d": [], "n": []})
for year, diverse, n_out, n_mut in rows:
    pct = n_mut / n_out * 100
    bucket = "d" if diverse else "n"
    data[year][bucket].append(pct)

# Drop years with too few papers in either group (avoid noisy ends)
MIN_N = 50
years = sorted(y for y in data if len(data[y]["d"]) >= MIN_N and len(data[y]["n"]) >= MIN_N)
print(f"  years included (>= {MIN_N} papers in each group): "
      f"{years[0]}–{years[-1]}, n={len(years)}")


def mean_se(vals):
    arr = np.array(vals, dtype=float)
    return arr.mean(), arr.std(ddof=1) / np.sqrt(len(arr))


d_mean, d_se = [], []
n_mean, n_se = [], []
for y in years:
    m, s = mean_se(data[y]["d"])
    d_mean.append(m)
    d_se.append(s)
    m, s = mean_se(data[y]["n"])
    n_mean.append(m)
    n_se.append(s)

d_mean = np.array(d_mean)
d_se = np.array(d_se)
n_mean = np.array(n_mean)
n_se = np.array(n_se)

# Overall stats
all_d = np.concatenate([data[y]["d"] for y in years])
all_n = np.concatenate([data[y]["n"] for y in years])
print(f"\n  Diverse papers     (n={len(all_d):>7,}): "
      f"mean pct-mutual = {all_d.mean():.3f}%  median = {np.median(all_d):.3f}%")
print(f"  Not-diverse papers (n={len(all_n):>7,}): "
      f"mean pct-mutual = {all_n.mean():.3f}%  median = {np.median(all_n):.3f}%")
print(f"  Ratio: not-diverse / diverse mean = {all_n.mean()/all_d.mean():.2f}x")

# ---- Plot ----
fig, ax = plt.subplots(figsize=(13, 7))

# Not-diverse: blue line + band
ax.fill_between(years, n_mean - n_se, n_mean + n_se,
                color="steelblue", alpha=0.20, label="Not diverse: ±1 SE")
ax.plot(years, n_mean, "o-", color="steelblue", linewidth=2.5, markersize=7,
        label="Not diverse: yearly mean")

# Diverse: coral line + band
ax.fill_between(years, d_mean - d_se, d_mean + d_se,
                color="coral", alpha=0.20, label="Diverse: ±1 SE")
ax.plot(years, d_mean, "x-", color="coral", linewidth=2.5, markersize=8,
        label="Diverse: yearly mean")

ax.set_xlabel("Publication year")
ax.set_ylabel("Mean percent of citations that are mutual (%)")
ax.set_title(
    "Per-paper mutual citation share by year and citation-diversity\n"
    f"Across {years[0]}–{years[-1]}, NON-diverse papers (blue, cite ≤2 fields) "
    f"consistently sit above diverse papers (coral, cite 3+ fields).\n"
    f"Overall non-diverse mean is {all_n.mean()/all_d.mean():.1f}× higher than diverse mean."
)
ax.set_ylim(bottom=0)
ax.grid(True, alpha=0.3)
ax.legend(loc="upper right", fontsize=10)

plt.tight_layout()
Path("outputs").mkdir(exist_ok=True)
plt.savefig(OUT, dpi=150)
print(f"\nSaved {OUT}")
