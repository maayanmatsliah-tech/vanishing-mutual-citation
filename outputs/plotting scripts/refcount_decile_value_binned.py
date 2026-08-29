#!/usr/bin/env python3
"""Regenerate reference-count decile share/rate charts with value-based bins.

The important rule is: papers with the same reference count cannot be split
across adjacent deciles. We therefore assign deciles at the level of distinct
n_cited values, not on individual rows via ntile(10).
"""

import os
import shutil
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
OUT_ROOT = ROOT / "updated_outputs"
OUT_CSV_DIR = OUT_ROOT / "csvs"
OUT_GRAPH_DIR = OUT_ROOT / "graphs"


def load_papers() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        sql = """
            WITH nc AS (
                SELECT CAST(id AS BIGINT) AS id, CAST(n_cited AS BIGINT) AS n_cited
                FROM read_csv(?, header=true, all_varchar=true)
            ),
            nm AS (
                SELECT CAST(id AS BIGINT) AS id, CAST(n_mutual AS BIGINT) AS n_mutual
                FROM read_csv(?, header=true, all_varchar=true)
            ),
            papers AS (
                SELECT
                    nc.id,
                    nc.n_cited,
                    COALESCE(nm.n_mutual, 0) AS n_mutual,
                    a.year,
                    a.diversity_count
                FROM nc
                JOIN attributes a
                  ON CAST(ltrim(nc.id::VARCHAR, 'W') AS BIGINT) = CAST(ltrim(a.id::VARCHAR, 'W') AS BIGINT)
                LEFT JOIN nm ON nm.id = nc.id
                WHERE nc.n_cited >= 3
            )
            SELECT *
            FROM papers
            ORDER BY id
        """
        df = con.execute(sql, [str(NC_PATH), str(NM_PATH)]).fetch_df()
    finally:
        con.close()
    return df


def assign_value_deciles(df: pd.DataFrame) -> pd.DataFrame:
    value_counts = (
        df.groupby("n_cited", as_index=False)
        .size()
        .rename(columns={"size": "n_papers"})
        .sort_values("n_cited")
        .reset_index(drop=True)
    )
    total = int(value_counts["n_papers"].sum())
    value_counts["cum_papers"] = value_counts["n_papers"].cumsum()
    value_counts["decile"] = (value_counts["cum_papers"] / total * 10).apply(
        lambda x: max(1, int(x))
    )
    value_counts["decile"] = value_counts["decile"].clip(1, 10)
    # Force the last distinct value to decile 10 when cumulative totals reach exactly total.
    value_counts.loc[value_counts.index[-1], "decile"] = 10
    df = df.merge(value_counts[["n_cited", "decile"]], on="n_cited", how="left")
    df["decile"] = df["decile"].astype(int)
    return df


def group_label(dc: int) -> str:
    return "non-diverse" if 1 <= dc <= 2 else "diverse"


def build_share(df: pd.DataFrame, out_csv: Path, out_png: Path):
    df = df.copy()
    df["group"] = df["diversity_count"].map(
        lambda x: "non-diverse" if 1 <= int(x) <= 2 else "diverse"
    )
    share = df.groupby(["decile", "group"], as_index=False).agg(
        n_papers=("id", "count"),
        n_with_mutual=("n_mutual", lambda s: int((s > 0).sum())),
    )
    share["share_pct"] = 100.0 * share["n_with_mutual"] / share["n_papers"]
    share = share.sort_values(["decile", "group"]).reset_index(drop=True)
    share.to_csv(out_csv, index=False)

    fig, ax = plt.subplots(figsize=(10, 6))
    for g in ["non-diverse", "diverse"]:
        sub = share[share["group"] == g].sort_values("decile")
        ax.plot(sub["decile"], sub["share_pct"], marker="o", linewidth=2, label=g)
    ax.set_xlim(0.5, 10.5)
    ax.set_xticks(range(1, 11))
    ax.set_xlabel("Reference-count decile")
    ax.set_ylabel("Share of papers with any mutual citation (%)")
    ax.set_title("Share of papers with any mutual citation by reference-count decile")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(title="Group")
    fig.tight_layout()
    fig.savefig(out_png, dpi=200)
    plt.close(fig)


def build_rate(df: pd.DataFrame, out_csv: Path, out_png: Path):
    df = df.copy()
    df["group"] = df["diversity_count"].map(
        lambda x: "non-diverse" if 1 <= int(x) <= 2 else "diverse"
    )
    rate = df.groupby(["decile", "group"], as_index=False).agg(
        n_papers=("id", "count"),
        sum_cited=("n_cited", "sum"),
        sum_mutual=("n_mutual", "sum"),
    )
    rate["rate_pct"] = 100.0 * rate["sum_mutual"] / rate["sum_cited"]
    rate = rate.sort_values(["decile", "group"]).reset_index(drop=True)
    rate.to_csv(out_csv, index=False)

    fig, ax = plt.subplots(figsize=(10, 6))
    for g in ["non-diverse", "diverse"]:
        sub = rate[rate["group"] == g].sort_values("decile")
        ax.plot(sub["decile"], sub["rate_pct"], marker="o", linewidth=2, label=g)
    ax.set_xlim(0.5, 10.5)
    ax.set_xticks(range(1, 11))
    ax.set_xlabel("Reference-count decile")
    ax.set_ylabel("Mutual-citation rate (% of references reciprocated)")
    ax.set_title("Mutual-citation rate by reference-count decile")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(title="Group")
    fig.tight_layout()
    fig.savefig(out_png, dpi=200)
    plt.close(fig)


def copy_outputs():
    for rel_dir in [
        "outputs/graphs_no_self_citations",
        "outputs/graphs_with_self_citations",
    ]:
        target_dir = ROOT / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in [
            "refcount_decile_dvn_share.png",
            "refcount_decile_dvn_rate.png",
        ]:
            src = OUT_GRAPH_DIR / fname
            if src.exists():
                shutil.copy2(src, target_dir / fname)


def main():
    OUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
    OUT_GRAPH_DIR.mkdir(parents=True, exist_ok=True)

    df = load_papers()
    df = assign_value_deciles(df)

    share_csv = OUT_CSV_DIR / "refcount_decile_dvn_share.csv"
    share_png = OUT_GRAPH_DIR / "refcount_decile_dvn_share.png"
    build_share(df, share_csv, share_png)

    rate_csv = OUT_CSV_DIR / "refcount_decile_dvn_rate.csv"
    rate_png = OUT_GRAPH_DIR / "refcount_decile_dvn_rate.png"
    build_rate(df, rate_csv, rate_png)

    copy_outputs()

    # Sanity check: no equal n_cited values should be split across adjacent deciles.
    bad = (
        df.groupby(["n_cited", "decile"], as_index=False)
        .size()
        .groupby("n_cited")
        .nunique("decile")
        .gt(1)
        .sum()
    )
    print(f"distinct n_cited values split across multiple deciles: {bad}")
    print(f"share csv: {share_csv}")
    print(f"rate csv: {rate_csv}")
    print(f"share png: {share_png}")
    print(f"rate png: {rate_png}")


if __name__ == "__main__":
    main()
