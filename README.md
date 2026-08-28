# The Vanishing Mutual Citation

Source code for *The Vanishing Mutual Citation*, a study of mutual citation
(paper pairs that cite each other) trends from 1975 to 2023, using the
OpenAlex citation graph.

## Question & hypothesis

Two questions: how has reciprocation moved over fifty years, and does citing
across more fields change the odds a citation is returned?

We hypothesized that (1) reciprocation would rise, since more accessible
search should make it easier for authors to find and cite each other's work,
and (2) diverse papers would reciprocate less, since a paper touching many
fields may not sit squarely in any one field to be cited back. Results
contradict both hypotheses: reciprocation fell rather than rose — an 87.4%
decline since 1975, dropping most sharply after 2010 — and diverse papers
reciprocate up to 83% more than non-diverse papers, not less.

## Data

Source: [OpenAlex](https://openalex.org/) — public, no account needed
(S3 snapshot for older papers, API for recent years). Tables are built
locally into an on-disk DuckDB; raw `data/` is not committed.

```bash
pip install boto3 duckdb matplotlib requests
```

## Repo structure

- `data_cleaning_and_validation/` — corpus construction from the OpenAlex
  snapshot, field-label filtering, and data validation checks.
- `build_attributes_and_edges_tables/` — field-diversity classification and
  citation-edge construction, including pre-1975 field backfilling.
- `compute_mutual_citations/` — mutual-pair identification, reference-count
  decile stratification, and robustness checks (shared-authorship exclusion).
- `outputs/` — aggregated result tables (CSV) and figures (PNG) corresponding
  to the paper's Results section and Figure 1.

## Reproducing the results

Run the scripts in the order above (cleaning → attributes/edges → mutual
citations) to regenerate the tables and figures in `outputs/`.

## Citation

If you use this code, please cite the paper (details in the paper PDF /
[link]).