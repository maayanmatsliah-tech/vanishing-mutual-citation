"""
Mutual-citation pairs with shared-author pairs REMOVED.

Starts from the existing mutual_pairs.csv (pairs where A<->B cite each other) and
drops any pair whose two papers share at least one author -- leaving only mutual
citations between papers with disjoint author sets (no author self-reciprocity).

Author match is by display-name string (the snapshot stored no per-author id
here), normalized to trimmed-lowercase; blank names are ignored. It is therefore
a proxy: two identical display names are treated as the same person.

LEFT JOIN so a pair is never silently dropped for missing metadata -- a paper
with no known authors contributes an empty name set and so is kept.

Env: PAIRS_IN (default data/mutual_pairs.csv), ATTR (default data/attributes.duckdb),
     OUT (default data/mutual_pairs_no_shared_authors.csv), MEM (default 10GB).
"""

import os
import time

import duckdb

PAIRS_IN = os.environ.get("PAIRS_IN", "data/mutual_pairs.csv")
ATTR = os.environ.get("ATTR", "data/attributes.duckdb")
OUT = os.environ.get("OUT", "data/mutual_pairs_no_shared_authors.csv")
MEM = os.environ.get("MEM", "10GB")

# split "A; B; C" -> ['a','b','c'], trimmed/lowercased, blanks removed
NAMES = ("list_filter("
         "  list_transform(string_split(COALESCE({col}, ''), '; '), x -> trim(lower(x))),"
         "  x -> x <> '')")


def main():
    os.makedirs("data/_duckdb_tmp", exist_ok=True)
    t = time.perf_counter()
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET memory_limit='{MEM}'")
    con.execute("SET temp_directory='data/_duckdb_tmp'")
    con.execute(f"ATTACH '{ATTR}' AS a (READ_ONLY)")

    con.execute(f"""
        CREATE TEMP TABLE joined AS
        SELECT p.paper_a, p.paper_b,
               {NAMES.format(col='aa.author')} AS na,
               {NAMES.format(col='ab.author')} AS nb
        FROM read_csv('{PAIRS_IN}', header=true, all_varchar=true) p
        LEFT JOIN a.attributes aa ON aa.id = p.paper_a
        LEFT JOIN a.attributes ab ON ab.id = p.paper_b
    """)

    total = con.execute("SELECT count(*) FROM joined").fetchone()[0]
    shared = con.execute("SELECT count(*) FROM joined WHERE list_has_any(na, nb)").fetchone()[0]

    con.execute(f"""
        COPY (
            SELECT paper_a, paper_b FROM joined
            WHERE NOT list_has_any(na, nb)
        ) TO '{OUT}' (HEADER, DELIMITER ',')
    """)
    con.close()

    kept = total - shared
    print(f"input pairs:          {total:,}")
    print(f"shared-author pairs:  {shared:,}  ({100*shared/total:.1f}% excluded)")
    print(f"kept (disjoint auth): {kept:,}  -> {OUT}")
    print(f"done in {time.perf_counter()-t:.0f}s")


if __name__ == "__main__":
    main()
