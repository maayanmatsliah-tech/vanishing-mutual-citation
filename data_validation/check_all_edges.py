import duckdb
con = duckdb.connect('data/_mutual_clean.duckdb', read_only=True)

count = con.execute("SELECT count(*) FROM all_edges").fetchone()[0]
print(f"all_edges row count: {count:,}")

result = con.execute("""
    SELECT count(*) FROM (
        SELECT least(s,t) AS a, greatest(s,t) AS b
        FROM all_edges
        GROUP BY least(s,t), greatest(s,t)
        HAVING bool_or(s < t) AND bool_or(s > t)
    )
""").fetchone()
print(f"total mutual pairs (single-pass, from all_edges): {result[0]:,}")
con.close()
