# Paper outline — Mutual citation, field diversity, and the long decline of reciprocity

**Status:** rough draft to work from. Structure mirrors Li et al., *Reciprocity and impact
in academic careers* (EPJ Data Science, 2019) — IMRaD-plus-Discussion with **Methods placed
after Discussion**. Inline `» craft:` notes flag where each of the requested style/substance
devices should land, so they don't get lost as the draft fills in.

---

## Working titles (pick/iterate)

- *Reciprocity across fields: how interdisciplinary citing reshapes — and dilutes — mutual citation*
- *The more fields you cite, the less each citation comes back: mutual citation and field diversity, 1975–2023*
- *Fewer favors returned: a half-century decline in citation reciprocity and its relationship to field diversity*

`» craft (deliberate naming):` fix terminology in the title and defend it once in the text.
We use **mutual citation** (A→B *and* B→A) rather than "reciprocity," reserving "reciprocity"
for the behavioral interpretation we are careful *not* to assert. A short footnote should say
why (Li et al. call the same edge structure "reciprocated citation"; we avoid "excess
reciprocity" because we build no null-model benchmark — see Limitations).

---

## Abstract (~180–220 words)

Bibliometric pressure has renewed interest in how often scientists cite one another back. Two
recent shifts may be reshaping this: after the dot-com crash and the COVID-19 pandemic, more
people entered research and many now work remotely — attending fewer conferences and
collaborating within narrow circles of same-field peers rather than meeting researchers from
other fields — while the annual volume of published papers has risen sharply. We asked whether
the relationship between mutual citation (pairs of papers that cite each other) and a paper's
field diversity has changed over the past 50 years.

Using OpenAlex, we ingested every scientific paper from 1975 to 2023 (~413 million), connected
by 2.96 billion citations. For each paper we computed its number of mutual citations and its
field diversity — how many distinct fields the papers it cites belong to — then tracked average
mutual-citation rates and diversity counts per year. The more fields a paper cites, the less
likely each individual citation is returned; yet more diverse papers are more likely to collect
at least one mutual citation, and the ordering of the diversity groups flips exactly between
these per-citation and per-paper views. We attribute the flip to diverse papers citing more work
overall, raising the odds that some of it cites back. Across the half-century, as papers cite
ever more fields, average mutual citation declines. Because 58% of all mutual pairs share an
author, we re-ran every analysis excluding them; the trends hold. The decline is already decades
old and continues smoothly through the post-2020 window, so while our data reaches 2023 we cannot
attribute it to the remote-work shift that motivated the study — only establish the long-run
baseline against which such an effect would have to be measured.

**Keywords:** mutual citation; citation networks; interdisciplinarity; field diversity; bibliometrics; OpenAlex

---

## 1. Introduction

- **1.1 The incentive backdrop.** Citation-based metrics shape careers; this creates incentives
  around citation exchange. Brief prior-work sweep (self-citation literature, reciprocity in
  citation networks, interdisciplinarity/impact). Position ours as the large-scale, cross-field
  complement to APS-style single-corpus studies.
- **1.2 A changing research environment.** Two overlapping shifts plausibly reshape *who* a
  researcher encounters and cites. First, after the dot-com crash and especially the COVID-19
  pandemic, more people entered research and many now work remotely: fewer conferences, fewer
  chance encounters across fields, and tighter collaboration within a narrow circle of same-field
  peers. Second, the annual volume of published papers has risen sharply, enlarging every author's
  pool of citable work. Both point the same way — toward citation relationships that are denser
  *within* a field and sparser *across* fields.
- **1.3 The question.** Has the relationship between mutual citation (pairs of papers that cite
  each other) and a paper's field diversity changed over the last 50 years? State it open-ended
  here — the per-citation vs. per-paper split is a Results payoff, not a premise.
  - `» craft (hedge at the overreach point — first of several):` state up front what the design
    can and cannot support. COVID (early 2020) leaves a real but short post-onset window
    (2020–2023) — unlike a purely post-2022 event, we are *not* censored out of it — but the
    trend we study is **five decades old and already declining long before 2020**, so we can
    describe whether recent years continue, break, or bend the trend, but we **cannot attribute**
    any single-cause "COVID/remote-work" story to it. Say it here, in Results where the recent
    tail is discussed, and again in Discussion/Limitations. (Note also: 2024–2025 OpenAlex records
    are contaminated/censored, so the clean window ends at 2023 regardless.)
- **1.4 What we measure, and two things we are careful not to claim.** Mirror the reference's
  "let us stress two points from the outset":
  1. A→B→A structure is a *pattern*, not evidence of strategic or coordinated behavior; we make
     no intent claims.
  2. Field diversity is a property of a paper's reference list, not a virtue judgment about the
     work.
- **1.5 Definitions, with a worked example.**
  - *Mutual citation:* an unordered pair {A,B} with A→B and B→A; self-loops (A→A) excluded;
    each pair counted once.
  - *Field diversity* of a paper: the number of distinct fields among the papers it cites,
    excluding `Unknown`; a paper is **diverse** if it cites ≥3 distinct fields.
  - *Pooled mutual-citation rate* for a (year, group) cell:
    `rate = 100 · Σ mutual_citations / Σ outgoing_citations`.
  - `» craft (worked concrete example right after the formalism):` plug in numbers — e.g., a
    2005 paper making 40 citations spanning 5 fields, 3 of which are returned → contributes
    3 and 40 to its cell; a cell pooling 200k such papers with 12M citations and 300k mutual
    → rate = 2.5%. Then state *why pooled, not mean-of-per-paper-%*: the mean over-weights
    1-citation papers that read as clean 0% or 100% outliers. (This is the same "define the
    quantity carefully so a trivial artifact is ruled out before the real claim" move the
    reference makes with its null model.)

---

## 2. Results

Ordered as a narrative arc: **core claim → refine → mechanism → stress-test.** Each subsection
answers the next question a skeptical reader asks.

### 2.1 Core claim — diversity depresses the per-citation return rate
- Fig. 1: **mutual-citation rate by year, per diversity group** (`outputs/mutual_citation_rate/rate_by_diversity.png`).
- Finding: each individual citation a paper makes is *less* likely to be returned the more fields
  that paper cites. State the simplest version first.
- `» craft (effect size, not just direction):` report the magnitude — e.g., "diverse papers'
  per-citation return rate is X percentage points / a factor of Y below concentrated papers,
  consistently across every year." Fill from the CSV.
- `» craft (figure does argumentative work):` the two-line (diverse vs. non-diverse) time series
  *is* the claim; the reader should see the gap without reading prose.

### 2.2 Refine — does it hold across time and across the diversity gradient?
- Show the ordering is monotone across diversity groups (not just a 2-way split), and that the
  gap persists across the full 1975–2023 span, not one era.
- Note the shared downtrend: **every** diversity group's reciprocity is declining together over
  time (setup for §2.4 and Discussion).

### 2.3 Mechanism — reconcile the apparent paradox (rate vs. reach)
- Fig. 2: **share of papers with any mutual citation, by diversity group**
  (`outputs/mutual_paper_share/share_by_diversity.png`).
- The tension that makes the paper: diverse papers have a *lower per-citation* return rate (§2.1)
  yet are *more* likely to receive **at least one** mutual citation. Resolve it: diverse papers
  cite more, and across more fields — more "tickets," each individually longer-odds. Reach up,
  hit-rate down.
- Fig. 3: **mean mutual citations vs. mean field diversity over time, 1975–2023**
  (`outputs/mean_mutual_vs_diversity/mean_mutual_and_diversity_pre2024.png`).
  - `» craft (figure decomposes an aggregate into its drivers):` the dual line — rising mean
    diversity, falling mean mutual citation — visually carries the "as papers spread citations
    across more fields, average reciprocation thins" story.

### 2.4 Stress-test — alternative explanations
This is the dedicated skeptic's section; vary the analysis along **genuinely independent axes.**

- **(a) Author self-reciprocity.** 58% of all mutual pairs share ≥1 author. Re-run all three
  analyses excluding pairs with a shared author (`outputs/graphs_self_citations_removed/`,
  Figs. 4–6). Genuine cross-author reciprocity is lower in level but every trend holds.
  `» craft (baseline doing real work):` self-citation removal is the control that rules out
  "it's just people citing themselves" before the real claim stands.
- **(b) Data-contamination / censoring axis.** The 2024–2025 record flood is non-article junk
  (`field='Unknown'`, ~94% of it post-2023); we drop `Unknown` and cap at 2023. Report the
  censoring footprint: mutual ties form fast (50% same-year, 84% within 1yr, 91% within 2yr),
  so cohorts ≤2021 are essentially complete and the multi-decade decline is **real, not a
  censoring artifact** — state this as a measured result, with the tie-formation numbers.
- **(c) Composition axis (to add / confirm from scripts).** Does the diversity gap survive within
  broad field families and cohorts, so it isn't a field-mix or paper-volume-growth artifact?
- `» craft:` if any robustness cut *narrows* the effect, say so with the number — costs rhetoric,
  buys credibility.

---

## 3. Discussion

- **3.1 What the pattern is.** Restate the rate-vs-reach split and the half-century decline in
  plain terms; reconnect to §1's incentive backdrop.
- **3.2 A plausible story, flagged as such.** `» craft (turn numbers into a story, labeled
  speculation):` mirror the reference's "we speculate" / "it is tempting to relate." Candidate
  narrative: over 50 years the growing volume of literature has steadily widened each paper's
  pool of citable work, diluting the chance any single cited author reciprocates — even as
  interdisciplinary papers cast a wider net and catch at least one return more often. It is
  *tempting to relate* the most recent bend to the post-2020 shift toward remote work and fewer
  cross-field encounters (researchers citing tightly within their own field, less likely to be
  cited back from outside it). Explicitly mark this as interpretation, not demonstrated causation,
  and stress that any COVID-era effect would be a small perturbation on a decline already 45 years
  underway.
- **3.3 The question we set out to ask.** Return to §1.3 honestly. We *can* observe the 2020–2023
  window, so — unlike a purely post-ChatGPT study — the remote-work era is not censored out of our
  data. But what we see there is a **continuation** of a decades-old decline, not a break at 2020,
  so the design cannot isolate a COVID/remote-work cause from the long-run trend or from the
  concurrent surge in paper volume. Frame the half-century baseline and the diversity relationship
  as the reference point against which any future, cleaner post-2023 test (with a genuine control)
  would have to measure a specific remote-work or AI-discovery effect.
- **3.4 Limitations.**
  `» craft (limitations that undercut our own strongest reading):`
  - We have **no null model.** Li et al. measure *excess* reciprocity against a rewired-network
    benchmark; we report raw pooled rates. So we cannot say mutual citation is higher/lower than
    chance given field structure — only how it varies across groups and time. Name the fix: a
    degree- and field-preserving null would be needed to make an "excess" claim.
  - **The COVID/remote-work reading is the one to resist.** The decline predates 2020 by decades
    and continues smoothly through it; we see no structural break at the pandemic. So the motivating
    story cannot be causally supported here — it would need a design with a genuine counterfactual
    (e.g., a difference-in-differences against a control unaffected by remote-work shifts, or
    author-level mobility/collaboration data), which our aggregate year-by-diversity series lacks.
  - Correlation, not causation: diversity and reciprocity co-move; we do not identify a
    mechanism experimentally.
  - `Unknown`-field records dropped and 2023 cap → we describe the recorded, article-like,
    pre-2024 corpus, not "all of science."
  - Field labels are OpenAlex's; disambiguation and topic assignment carry their own error.
- **3.5 Implications.** For interpreting interdisciplinary citation counts, and as a pre-registered
  baseline for any future audit of how the remote-work era (and, later, AI-assisted discovery)
  reshapes cross-field reciprocity.

---

## 4. Materials and methods
*(placed after Discussion — full procedural detail deferred for readers who want to replicate;
Results §1.5 carried enough definition to be read on its own.)*

- **4.1 Data source and scope.** OpenAlex works snapshot, 1975–2025 (analysis capped at 2023).
  413,392,893 unique papers; ~2.96B directed citations; 117,055,340 citing papers (the study
  population — ~71.7% of papers cite nothing). Built via `build_tables_from_snapshot.py` into
  on-disk DuckDB. `attributes` = (id, year, field, author); `edges` = adjacency
  (`source,target1;target2;…`).
- **4.2 Cleaning.** Why `field='Unknown'` is dropped (17.68M rows, 94.4% in 2024–2025; local
  2024 subset exceeds OpenAlex's entire 2024 article corpus → contamination) and why the 2023
  cap follows. Confirm pre-2024 is materially unchanged by cleaning (junk is temporally in the
  future of pre-2024 papers).
- **4.3 Constructing mutual pairs.** Directed edge set, self-loop exclusion (~1.05M source==target),
  identifying A→B∧B→A, counting each pair once, and the shared-author test used for the
  self-citation control (`analysis/build_mutual_counts.py`, `find_mutual_pairs*.py`).
- **4.4 Field diversity.** Distinct-field count per paper excluding `Unknown`; ≥3 threshold for
  "diverse"; grouping (`analysis/add_diverse_column.py`, `add_diversity_count.py`,
  `classify_diversity.py`).
- **4.5 The pooled rate and why not the per-paper mean.** Formula, the outlier argument, and cell
  filters (exclude diversity group 0; drop (year, group) cells with <10K papers)
  (`analysis/compute_pooled_share.py`, `analyze_mutual_by_diversity.py`).
- **4.6 Censoring assessment.** Tie-formation gap distribution and the completeness-by-cohort
  argument behind analyzing confidently through ~2021 and reporting through 2023.
- **4.7 Reproducibility.** Scripts in `analysis/` and `research/`; each figure sits beside the
  CSV it was generated from in `outputs/`.

---

## Back matter
Availability of data (OpenAlex, public) · code availability (repo) · author contributions ·
competing interests · acknowledgements · endnote on the mutual-citation vs. reciprocity naming ·
references.

---

## Figure inventory (map to sections)

| Fig | Source | Section | Argumentative job |
|-----|--------|---------|-------------------|
| 1 | `mutual_citation_rate/rate_by_diversity.png` | 2.1 | Core claim: diversity ↓ per-citation return rate |
| 2 | `mutual_paper_share/share_by_diversity.png` | 2.3 | The paradox: diversity ↑ chance of ≥1 return |
| 3 | `mean_mutual_vs_diversity/mean_mutual_and_diversity_pre2024.png` | 2.3 | Aggregate decline decomposed vs. rising diversity |
| 4–6 | `graphs_self_citations_removed/*` | 2.4a | Same three, self-reciprocity removed — trends hold |

`» craft (open items before submission):` (1) add exact effect-size numbers from the CSVs;
(2) decide whether to attempt a null-model "excess" version or keep raw rates + own the
limitation; (3) confirm/perform the within-field-family robustness cut (§2.4c); (4) decide how
hard to lean on the 2020–2023 tail — worth a labeled look for a post-COVID bend, but the paper's
claim is the long-run baseline, and any remote-work reading must stay explicitly speculative
(§3.2–3.4).
