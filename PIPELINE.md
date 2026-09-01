# Pipeline

## Ingest

- `s3://openalex` works snapshot (gzipped JSONL) → `build_tables/build_tables_from_snapshot.py` → `data/attributes.csv` + `data/edges.csv`
- `data/attributes.csv` + `data/edges.csv` → `data_validation/validate_data.py` → `data/attributes.duckdb` + `data/validation_report.txt`

## Drop isolated papers

- `data/attributes.duckdb` + `data/edges.csv` → `corpus_distribution/scripts/find_connected.py` → `data/_connected.duckdb`
- `data/_connected.duckdb` + `data/attributes.duckdb` → *(unscripted removal step)* → `data/attributes.duckdb`

## Diversity count

- `data/attributes.duckdb` + `data/edges.csv` → `build_tables/add_diversity_count.py` → `data/_div_counts.csv` → `data/attributes_new.duckdb` → *(swapped in)* → `data/attributes.duckdb`

## Pre-1975 field backfill

- `s3://openalex` works snapshot (parquet) → `build_tables/extract_pre1975_fields.py` → `data/pre1975_fields/batch_*.parquet`
- `data/attributes.duckdb` + `data/edges.csv` + `data/pre1975_fields/batch_*.parquet` → `build_tables/recompute_diversity_backfilled.py` → `data/_div_backfilled_counts.csv` + `data/diversity_before_after_by_year.csv`
- `data/attributes.duckdb` + `data/_div_backfilled_counts.csv` → `build_tables/build_backfilled_attributes.py` → `data/attributes_backfilled.duckdb` → *(swapped in)* → `data/attributes.duckdb`

## Clean + mutual pairs

- `data/attributes.duckdb` + `data/edges.csv` → `compute_mutual_citations/compute_mutual_pairs.py` → `data/attributes_clean.duckdb` + `data/edges_clean.csv` + `data/mutual_pairs_batches/batch_000..019.csv` → `data/mutual_pairs_clean.csv`
- `data/attributes_clean.duckdb` + `data/edges_clean.csv` + `data/mutual_pairs_clean.csv` → *(renamed)* → `data/attributes.duckdb` + `data/edges.csv` + `data/mutual_pairs.csv`

## Per-paper metrics

- `data/edges.csv` → `STEPS=ncited compute_mutual_citations/build_n_cited_n_mutual.py` → `data/_n_cited.csv`
- `data/mutual_pairs.csv` → `STEPS=nmutual compute_mutual_citations/build_n_cited_n_mutual.py` → `data/_n_mutual.csv`

## Figures

- `data/_n_cited.csv` + `data/_n_mutual.csv` + `data/attributes.duckdb` → `figures/scripts/plot_mean_mutual_citations_per_year.py` → `figures/csvs/mean_mutual_citations_per_year.csv` + `figures/graphs/mean_mutual_citations_per_year.png`
- `data/_n_cited.csv` + `data/_n_mutual.csv` + `data/attributes.duckdb` → `figures/scripts/plot_mutual_citation_rate_per_year.py` → `figures/csvs/mutual_citation_rate_per_year.csv` + `figures/graphs/mutual_citation_rate_per_year.png`
- `data/_n_cited.csv` + `data/_n_mutual.csv` + `data/attributes.duckdb` → `figures/scripts/refcount_decile_value_binned.py` → `figures/csvs/refcount_decile_dvn_share.csv` + `figures/csvs/refcount_decile_dvn_rate.csv` + `figures/graphs/refcount_decile_dvn_share.png` + `figures/graphs/refcount_decile_dvn_rate.png`
- `data/attributes.duckdb` → `corpus_distribution/scripts/corpus_scale_by_year.py` → `figures/csvs/papers_per_year.csv`
- `data/mutual_pairs.csv` + `data/attributes.duckdb` → `compute_mutual_citations/compute_mutual_citation_lag.py` → `figures/csvs/citation_lag_distribution.csv`

## Validation

- `data/edges.csv` + `data/mutual_pairs.csv` + `data/_n_cited.csv` + `data/_n_mutual.csv` → `data_validation/validate_n_cited_n_mutual.py`
- `data/mutual_pairs.csv` + `data/attributes.duckdb` → `data_validation/check_mutual_pairs.py`
