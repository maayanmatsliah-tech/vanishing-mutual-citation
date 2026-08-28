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

## Structure

```
├── build_tables_from_snapshot.py   # ingest OpenAlex snapshot -> local tables
├── analyze_mutual_by_diversity.py  # top-level mutual-by-diversity analysis
├── analysis/                       # pipeline: find mutual pairs, diversity, plots
├── research/                       # current-hypothesis scripts (per-year, significance)
├── docs/                           # findings and write-up
├── data/                           # local DuckDB + CSVs (not committed)
└── outputs/                        # saved charts + their source CSVs
```

## Outputs

- `outputs/mutual_citation_rate/rate_by_diversity.png` — mutual-citation rate
  (% of citations reciprocated) by year, per diversity group.
- `outputs/mutual_paper_share/share_by_diversity.png` — share of papers with
  any mutual citation by year, per diversity group.

Both exclude diversity group 0 and (year, group) cells with fewer than 10K
papers. Each PNG sits next to the CSV it was generated from.
