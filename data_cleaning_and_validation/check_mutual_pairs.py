import duckdb

con = duckdb.connect('data/attributes.duckdb', read_only=True)

result = con.execute("""
    WITH pairs AS (
        SELECT paper_a, paper_b
        FROM read_csv('data/mutual_pairs_clean.csv', header=true, all_varchar=true)
    )
    SELECT
        count(*) AS total_pairs,
        count(*) FILTER (WHERE a.id IS NULL) AS paper_a_missing,
        count(*) FILTER (WHERE b.id IS NULL) AS paper_b_missing
    FROM pairs p
    LEFT JOIN attributes a ON a.id = p.paper_a
    LEFT JOIN attributes b ON b.id = p.paper_b
""").fetchone()
print(f"total_pairs={result[0]:,}  paper_a_missing={result[1]:,}  paper_b_missing={result[2]:,}")

result2 = con.execute("""
    WITH pairs AS (
        SELECT paper_a, paper_b
        FROM read_csv('data/mutual_pairs_clean.csv', header=true, all_varchar=true)
    )
    SELECT count(*) AS pairs_touching_unknown
    FROM pairs p
    JOIN attributes a ON a.id = p.paper_a OR a.id = p.paper_b
    WHERE a.field = 'Unknown'
""").fetchone()
print(f"pairs_touching_unknown={result2[0]:,}")

con.close()
