# Citation Graph Analysis

Analysis of OpenAlex citation data to test whether mutual citations — pairs of
papers that cite each other — grew faster than paper volume after ChatGPT's
release (November 2022), and whether that growth varies with a paper's field
diversity.

## Question & hypothesis

Did mutual citations rise after ChatGPT faster than overall paper growth? The
hypothesis: AI tools let researchers locate and extract specifics from papers
without reading them in full, compressing discovery enough to create citation
loops that wouldn't otherwise exist.

## Data

Source: [OpenAlex](https://openalex.org/) — public, no account needed
(S3 snapshot for older papers, API for recent years). Tables are built locally
into an on-disk DuckDB; raw `data/` is not committed.

```bash
pip install boto3 duckdb matplotlib requests
python3 build_tables_from_snapshot.py
```
