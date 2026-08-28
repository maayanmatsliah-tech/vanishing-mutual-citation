"""
Re-draw mean_mutual_and_diversity but excluding the 2024-2025 junk years.

Reads the already-computed CSV (no DuckDB / edges re-scan) and re-plots with
year <= MAX_YEAR. Output is a separate PNG so the original is untouched.

Env: IN_CSV, OUT_PNG, MAX_YEAR (default 2023).
"""
import csv
import os

IN_CSV = os.environ.get("IN_CSV", "outputs/mean_mutual_vs_diversity/mean_mutual_and_diversity.csv")
OUT_PNG = os.environ.get("OUT_PNG", "outputs/mean_mutual_vs_diversity/mean_mutual_and_diversity_pre2024.png")
MAX_YEAR = int(os.environ.get("MAX_YEAR", "2023"))

xs, mutual, diversity = [], [], []
with open(IN_CSV, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        y = int(row["year"])
        if y > MAX_YEAR:
            continue
        xs.append(y)
        mutual.append(float(row["mean_mutual"]))
        diversity.append(float(row["mean_diversity"]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax1 = plt.subplots(figsize=(12, 7))
c1, c2 = "C0", "C3"
l1, = ax1.plot(xs, mutual, marker="o", markersize=3, linewidth=1.6, color=c1,
               label="mean mutual citations per paper")
ax1.set_xlabel("Publication year")
ax1.set_ylabel("Mean mutual citations per paper", color=c1)
ax1.tick_params(axis="y", labelcolor=c1)
ax1.grid(True, alpha=0.3)

ax2 = ax1.twinx()
l2, = ax2.plot(xs, diversity, marker="s", markersize=3, linewidth=1.6, color=c2,
               label="mean diversity count per paper")
ax2.set_ylabel("Mean diversity count per paper (raw, no 6+ bucketing)", color=c2)
ax2.tick_params(axis="y", labelcolor=c2)

ax1.set_title(f"Mean mutual citations vs mean diversity count, by year (1975-{MAX_YEAR})\n"
              "(2024-2025 junk years excluded; papers citing >=1 work)")
# tick every 5 years instead of 10
ax1.set_xticks(range(1975, MAX_YEAR + 1, 5))
# legend in the clear lower-centre band (below the blue line, well off the red line)
ax1.legend(handles=[l1, l2], loc="lower center", fontsize=9)
fig.tight_layout()
fig.savefig(OUT_PNG, dpi=150)
print(f"wrote {OUT_PNG} ({len(xs)} years, {xs[0]}-{xs[-1]})")
