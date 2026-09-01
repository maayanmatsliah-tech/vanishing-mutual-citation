# The Vanishing Mutual Citation

Source code and data pipeline for *The Vanishing Mutual Citation*, an empirical study of mutual citation trends from 1975 to 2023 using the OpenAlex citation graph.

Detailed findings, interpretations, and results are presented in *The Vanishing Mutual Citation* paper.

## Reproduction Pipeline

Step-by-step instructions for data ingest, table construction, metrics computation, and figure reproduction are documented in [PIPELINE.md](PIPELINE.md).

## Installation

```bash
pip install boto3 duckdb matplotlib requests numpy
```

## Repository Structure

- `build_tables/` — Ingest works metadata from OpenAlex, backfill pre-1975 field classifications, and compute field diversity counts.
- `compute_mutual_citations/` — Clean non-paper records, extract reciprocal mutual pairs, and compute per-paper citation and reciprocation metrics.
- `corpus_distribution/` — Scripts and summary distributions tracking corpus scale and citation lag.
- `data_validation/` — Validation checks for snapshot completeness, schema invariants, and data integrity.
- `figures/` — Plotting scripts, source CSV tables, and generated figures.


