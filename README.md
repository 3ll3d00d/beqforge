# BEQ Analyser

Reduces the [BEQ catalogue](https://beqcatalogue.readthedocs.io) — thousands of individually authored
bass-EQ filter sets — to a small number of **composite curves** that represent the catalogue as a whole,
then fits realisable IIR filters to those composites.

> NB: Code and requirements are LLM generated with human guidance/review.

**A second, separate capability lives in `beqanalyser/design/`**: deriving a BEQ filter from a film's
audio rather than summarising existing ones. It shares nothing with the clustering pipeline below except
the biquad classes. It derives a target three ways, fits each, and judges them against an acceptance
model — printing the evidence beside the answer, and abstaining when nothing measures up. See
[AUTOMATED_DESIGN.md](AUTOMATED_DESIGN.md), whose §0 records how far it has actually got and what is
still unevidenced. [PERFORMANCE.md](PERFORMANCE.md) covers where its runtime goes and what has been done
about it — a run is ~40-80 s a title, down 7.18x, with every accepted filter unchanged.

### Running the design pipeline manually

Five scripts under `tools/`, each runnable on its own — a full pass is the first three in order;
the last two redraw pictures from what `design_beq.py` already wrote, so they cost no rerun.
Every one takes `--help` for its full flag list; this covers what you'd reach for day to day.

| step | command | produces |
| --- | --- | --- |
| 1. extract | `uv run python tools/extract.py FILM.mkv --out data/` | `data/FILM.npz` — a 1 kHz mono mix plus per-channel decomposition, from one ffmpeg pass |
| 2. sanity-check *(optional)* | `uv run python tools/summarise.py data/FILM.npz` | structural facts and an average spectrum — enough to tell a good extraction from a broken one before spending a run on it |
| 3. design | `uv run python tools/design_beq.py data/FILM.npz` | a filter and its reasoning, printed; `data/FILM.run.json.gz` written alongside the material unless `--no-record` |
| 4. redraw charts *(optional, no rerun)* | `uv run python tools/replay.py data/FILM.run.json.gz --charts charts/` | peak/average PNGs per candidate, drawn from the record — no extraction, no rerun |
| 5. build the ledger *(optional, no rerun)* | `uv run python tools/render_ledger.py` | one HTML report across every `data/*.run.json.gz`; open `out/ledger/index.html` directly in a browser |

**`tools/extract.py FILM.mkv --out data/`** — `--stream N` picks a non-default audio stream
(default 0); `--name` overrides the output basename (default: the source filename's stem);
`--excerpt` records the material as less than the complete programme (folded into the stage
cache's key so an excerpt and the full programme never share a cached analysis, but nothing in
`design_beq.py` branches on it yet — that's `designer-interface.md`'s contract, not yet built
here); `--mono-only` drops the per-channel arrays and roughly halves the file, which is fine for
the `flatten` strategy alone but starves `counterfactual` and the per-channel diagnosis of the
channels they need. Without those channels, sub-feed headroom is reported as unavailable.

**`tools/design_beq.py data/FILM.npz`** — the entry point. Exit status is 0 when a candidate was
accepted, 1 when abstaining was the correct output — neither is an error. Key flags:

| flag | effect |
| --- | --- |
| `--strategy NAME` (repeatable) | run only the named strategies (`flatten`, `counterfactual`, `parametric`); default `all` |
| `--exclude LOW HIGH` (repeatable) | drop an authored feature (Hz) from the target and the judgement — still manual (AUTOMATED_DESIGN.md §3.1) |
| `--charts DIR` | write peak/average charts per candidate into `DIR/<name>/` |
| `--record PATH` / `--no-record` | where to write the run record (default: `<material>.run.json.gz` alongside it), or skip writing one |
| `--cache PATH` / `--fresh` / `--no-cache` | the stage cache: where to keep it (default: `<material>.cache.json.gz`), force a recompute and overwrite it, or use neither |
| `--quiet` | report only, no progress log |

**`tools/replay.py data/FILM.run.json.gz`** — redraws from the record alone, without touching
the extraction. `--charts DIR` for the pictures, `--beq PATH` to export a beqdesigner project.
Uses the configuration recorded with the run, including exclusions and strategy selection.
Refuses if the schema, code or available source material has changed, and says why; `--force`
draws it anyway.

**`tools/render_ledger.py [RECORDS...]`** — every `data/*.run.json.gz` by default, or specific
ones named on the command line. `--charts-dir DIR` (default `out/ledger`) is where charts are
redrawn and, unless `--out` says otherwise, where the page (`index.html`) is written alongside
them; `--files-manifest PATH` (default `<charts-dir>/files.json`) writes `{published filename:
path under --charts-dir}`, needed only when publishing the page somewhere other than opening it
straight off disk. A stale record is skipped with a warning rather than failing the whole page;
`--force` draws it anyway.

---

## 1. Quick start

```bash
uv sync
uv run python -m beqanalyser
```

`python -m beqanalyser` runs the whole pipeline with the settings hard-coded in
[`beqanalyser/__main__.py`](beqanalyser/__main__.py) — there is no CLI. To change the band, the catalogue
filter, or the clustering schedule, edit that file (or work in the notebook, below).

[`beqanalyser/beq.ipynb`](beqanalyser/beq.ipynb) runs the same pipeline stage by stage and is the better
place to explore results interactively.

### Working directory matters

Several paths are resolved relative to the current working directory:

| Path | Role |
| --- | --- |
| `database.bin` + `database.bin.sha256` | Cached catalogue (JSON, despite the extension) |
| `<data_hash>.npy` | Cached pairwise distance matrix |
| `beq_composites.csv` | Assignment audit trail written by `print_assignments` |
| `<digest>/composite_delta.png` | Per-entry delta plots written by `dump_filter_delta` |

All are gitignored. Both the repo root and `beqanalyser/` contain a `database.bin`, because the module is
run from the root and the notebook from `beqanalyser/`.

---

## 2. What the pipeline does

```
beqcatalogue JSON
   → IIR filter definitions per entry
   → magnitude response per entry            (loader.convert)
   → normalise + band-limit                  (Curves)
   → pairwise distance matrix                (loader.compute_distance_matrix, cached)
   → HDBSCAN clustering, repeated over noise (analyser.build_all_composites, phase 1)
   → final assignment sweep of stragglers    (analyser.build_all_composites, phase 2)
   → composite curves + fan envelopes
   → biquad / graphic-EQ fits                (filter.py)
   → plots, CSV, summaries                   (reporter.py)
```

### 2.1 Loading and response generation

`loader.load(predicate)` reads `database.bin` and verifies its SHA-256 against `database.bin.sha256`.
On any failure it fetches
`https://raw.githubusercontent.com/3ll3d00d/beqcatalogue/master/docs/database.json`, converts every entry
that has filters, and writes both cache files.

Conversion (`loader.convert`) turns each entry's `PeakingEQ` / `LowShelf` / `HighShelf` definitions into
RBJ biquads, cascades them, filters a scaled unit impulse (`sosfilt`) and takes `freqz` of the result at
`fs=1000`. DC is discarded, leaving **511 linearly spaced points from ~1 Hz to ~500 Hz**.

`predicate` filters the catalogue (e.g. `entry.year >= 2023`). When a predicate is supplied, the returned
hash is computed over the *filtered* data, so the distance-matrix cache key tracks the selection.

### 2.2 Normalisation and band limiting

`__main__` normalises each curve to 0 dB at its top frequency (`mag_db - mag_db[-1]`), then wraps
everything in `Curves(min_freq, max_freq, magnitude, frequency)`.

`Curves` holds a `Points` for magnitude and frequency, each exposing `.full_range` and `.band_limited`.
Distances, clustering and assignment all operate on `.band_limited` (default 5–50 Hz); the full range is
carried alongside for plotting and filter fitting.

All curves are assumed to share a common frequency axis. This is a hard precondition and is **not
validated at runtime**.

### 2.3 Distance matrix

`loader.compute_beq_distance_matrix` builds a dense `N × N` `float64` matrix, chunked and computed across
a process pool. Per pair it derives RMS deviation, max absolute deviation, cosine similarity and
first-derivative RMS, then combines them in `compute_distance_components`:

```
base     = rms_weight · rms_adjusted + cosine_weight_adj · (1 − cos_sim) · cosine_scale
distance = base + Σ penalties
```

with three behaviours layered on top:

* **Asymmetric RMS.** When the candidate sits *below* the reference (mean difference < 0), its RMS is
  divided by `distance_rms_undershoot_tolerance` and its RMS penalty scale reduced by the same factor —
  undershooting a BEQ curve is treated as less harmful than overshooting it.
* **Cosine boost when close.** When RMS is below `distance_rms_close_threshold`, the cosine weight is
  multiplied by `distance_cosine_boost_in_close_range`, so shape dominates the ranking once magnitude
  already agrees.
* **Smooth tiered penalties.** Each of RMS / cosine / max / derivative has a hard limit and a soft limit
  at `distance_soft_limit_factor` of it. Below the soft limit the penalty is zero; between the two it
  grows exponentially; at or above the hard limit it saturates at `distance_penalty_scale` (100).
  A distance ≥ 100 therefore signals at least one hard-limit violation.

The same function serves both the matrix build and single curve-vs-composite comparisons
(`analyser.compute_composite_distance`), so scores are directly comparable.

The matrix is computed once for the whole catalogue and cached to `<data_hash>.npy`. Each clustering pass
takes a submatrix of it via `np.ix_` rather than recomputing.

### 2.4 Clustering — phase 1 (discovery)

`build_all_composites` walks the list of `HDBSCANParams` it is given. Pass 1 clusters the whole
catalogue; **each subsequent pass reclusters only the entries the previous pass rejected**, typically with
a smaller `min_cluster_size` / `min_samples`, so successively looser structure is picked out of the noise.

Within one pass (`build_beq_composites`):

1. HDBSCAN runs with `metric="precomputed"`, `cluster_selection_method="eom"`, `allow_single_cluster=False`.
   Points labelled `-1` are noise.
2. Each cluster's initial composite is its **medoid** (the member closest to the per-frequency median),
   unless that medoid scores a hard-limit distance from the median, in which case the median is used.
3. Every entry is scored against every composite. The lowest-distance composite is marked `is_best`; the
   rest are marked `SUBOPTIMAL`. Entries HDBSCAN labelled as noise are marked `NOISE`.
4. Composites are recomputed as the **per-frequency median** of their assigned members.
5. Steps 3–4 repeat until the reject rate stops improving by more than `min_reject_rate_delta`, gets
   worse, or `max_iterations` is hit. If it got worse, the previous cycle's state is the one kept.

Median aggregation is used rather than mean to blunt the effect of outliers.

### 2.5 Final assignment — phase 2

`create_final_result` flattens the composites from every pass into one list with sequential ids, remapping
mapping references as it goes. `assign_remaining_entries` then gives every still-unassigned entry one more
chance against **all** discovered composites, using limits scaled by
`final_assignment_threshold_multiplier` (`1.0` = unchanged; > 1.0 relaxes them). An entry is rejected as
`HARD_LIMIT` only if its best distance still reaches `distance_penalty_scale`. Composites and fan
envelopes are recomputed afterwards if anything new was assigned.

### 2.6 Fan envelopes

`compute_fan_curves` sorts a composite's assigned curves by RMS distance from it, then slices them into
**disjoint bands using the absolute counts in `fan_counts`** (e.g. `(5, 10, 20, 50, 100)` → the closest 5,
then the next 5, then the next 10, …). No curve appears in more than one band. Bands beyond the available
membership are empty arrays.

---

## 3. Distance and similarity metrics

Four complementary metrics are recorded for every attempted assignment. No single one captures perceptual
similarity in infra-bass BEQ filters; together they guard against distinct failure modes seen in real
catalogue data.

| Metric | Definition |
| --- | --- |
| RMS | Root mean square of the per-frequency difference |
| Max | Maximum absolute per-frequency difference |
| Cosine similarity | Cosine of the angle between the two curves as vectors in frequency space |
| Derivative RMS | RMS of the difference of first differences (slope mismatch) |

All four are stored on **every** `BEQFilterMapping`, accepted or not, alongside the combined
`distance_score` that actually decides the assignment.

### RMS deviation

Measures overall energy deviation across the band, correlates with perceived loudness difference, and
penalises distributed mismatches more than localised ones. Catches filters that are broadly too strong or
too weak, and gradual shape drift. Misses narrow sharp deviations and directional shape inversions.

### Maximum absolute deviation

A hard safety constraint against visually or perceptually egregious mismatches that RMS averaging would
hide — sharp peaking filters, unexpected notches, rolloffs that diverge at one end. Misses broad but
moderate deviations.

### Cosine similarity

Directional similarity of shape, independent of magnitude: do the two curves move together? Catches shape
inversions (shelf vs inverted shelf), boost vs cut, and structurally different intent. Misses absolute
strength differences.

### First-derivative deviation

Rate-of-change difference — sensitive to filter *topology* rather than level. Catches additional
poles/zeros, sharp knees, peaking filters stacked on shelves. Misses parallel but offset curves.

### Why all four

| Failure mode | RMS | Max | Cosine | Derivative |
| --- | --- | --- | --- | --- |
| Too strong / weak | ✓ | ✗ | ✗ | ✗ |
| Sharp spike | ✗ | ✓ | ✗ | ✓ |
| Shape inversion | ✗ | ✗ | ✓ | ✓ |
| Extra filter stage | ✗ | ✓ | ✗ | ✓ |
| Broad drift | ✓ | ✗ | ✗ | ✗ |

> **RMS measures "how much", cosine measures "which way", derivative measures "how".**

Treating these as orthogonal constraints rather than interchangeable thresholds is what allows looser
RMS/max limits without admitting structurally different filters.

### Rejection reasons

`RejectionReason` (in `beqanalyser/__init__.py`) is authoritative:

| Reason | Meaning | Set where |
| --- | --- | --- |
| `SUBOPTIMAL` | A closer composite exists for this entry | Discovery, non-best mappings |
| `NOISE` | HDBSCAN classified the entry as noise | Discovery |
| `HARD_LIMIT` | Best distance still hit the penalty ceiling | Final assignment sweep |
| `RMS_EXCEEDED` | RMS deviation exceeds threshold | `BEQFilterMapping.assess` (unused) |
| `MAX_EXCEEDED` | Maximum deviation exceeds threshold | `BEQFilterMapping.assess` (unused) |
| `RMS_MAX_EXCEEDED` | Both RMS and max exceed thresholds | `BEQFilterMapping.assess` (unused) |
| `COSINE_TOO_LOW` | Shape similarity below threshold | `BEQFilterMapping.assess` (unused) |
| `DERIVATIVE_TOO_HIGH` | Slope mismatch above threshold | `BEQFilterMapping.assess` (unused) |

Only the first three are produced by the current pipeline. The per-metric reasons predate the combined
distance score: the individual limits now feed the smooth penalty system inside the distance instead of
acting as standalone gates, and `assess()` is dead code.

---

## 4. Filter fitting

`filter.py` fits realisable filters to each composite curve.

All three entry points take the catalogue's `Points` and fit over its **full range**, against
`BEQComposite.mag_response`. Band limiting applies to clustering and assignment, not to fitting: a filter
you would actually deploy has to be sane across the whole response, not just 5–50 Hz. Everything below the
`fit_all_composites_*` boundary works on plain ndarrays.

* **`fit_all_composites_to_peq`** — iterative residual fitting. Fits a low shelf to the curve, subtracts
  its response, then fits either another shelf (if the residual still has > 1 dB of overall tilt) or a
  peaking filter to the most prominent residual peak, up to `max_filters` or until the residual RMS falls
  below `residual_threshold`. Multi-filter results then get a global Nelder–Mead pass over all
  `(fc, gain, Q)` at once, with near-zero-gain filters dropped.
* **`fit_all_composites_to_geq`** — solves for the gains of fixed 1/3-octave bands with L-BFGS-B, using a
  vectorised biquad cascade evaluated on a 500-point log grid, plus a smoothing penalty on adjacent-band
  gain differences.
* **`fit_all_composites_to_mag`** — no fitting at all; just samples the composite at 1/3-octave centres.

All three return `{composite_id: {"freqs", "filters", "rms_error", "max_error", "target_response",
"fitted_response"}}` (the mag variant returns only `freqs` and `filters`).

RBJ coefficient generation lives in both `filter.py` (`lowshelf_rbj` / `peaking_rbj` / `highshelf_rbj`,
returning `BiquadCoefficients`) and `__init__.py` (the `Biquad` class hierarchy used to render the
catalogue). They are separate implementations of the same cookbook formulae.

---

## 5. Reporting

| Function | Output |
| --- | --- |
| `summarise_result` | Assigned/rejected counts and per-composite membership, to the log |
| `summarise_assignments` | Per-pass breakdown including rejection reasons and reject rate per cycle |
| `plot_assigned_fan_curves` | Grid of composites (max 3 per row), fan curves in light blue with alpha ramping by RMS rank, composite overlaid in black, inset distance-score histogram |
| `plot_composite_evolution` | How each composite's shape moved across refinement cycles, coloured by iteration |
| `plot_distance_histograms` | Catalogue-wide histograms of RMS, max, cosine, derivative and distance score with 50/90/95th percentile markers |
| `plot_filter_comparison` | Target composite vs fitted filter response per composite |
| `show_filters` | Fitted filter parameters rendered as tables |
| `print_assignments` | `beq_composites.csv` — one row per best mapping with metrics and catalogue metadata |
| `dump_filter_delta` | Per-composite PNG of composite-minus-source delta, under `<digest>/` |

Plotting is deliberately non-interactive: no widgets, no animation, no implicit downsampling, no
re-normalisation at plot time.

---

## 6. Configuration reference

### `DistanceParams`

| Field | Default | Meaning |
| --- | --- | --- |
| `rms_limit` | 10.0 | Hard RMS limit (dB) |
| `max_limit` | 10.0 | Hard max-deviation limit (dB) |
| `cosine_limit` | 0.90 | Hard minimum cosine similarity |
| `derivative_limit` | 1.0 | Hard maximum derivative RMS |
| `use_constraints` | True | Apply the penalty system at all |
| `distance_rms_weight` | 0.8 | Weight of the RMS term |
| `distance_cosine_weight` | 0.2 | Weight of the cosine term |
| `distance_cosine_scale` | 10.0 | Scales cosine distance into RMS units |
| `distance_penalty_scale` | 100.0 | Penalty at/above a hard limit; also the rejection ceiling |
| `distance_soft_limit_factor` | 0.7 | Soft limit as a fraction of the hard limit |
| `distance_rms_undershoot_tolerance` | 2.0 | Divisor applied to RMS and RMS penalty when undershooting |
| `distance_rms_close_threshold` | 2.0 | RMS below which cosine weight is boosted |
| `distance_cosine_boost_in_close_range` | 2.0 | Cosine weight multiplier in the close range |
| `distance_chunk_size` | 1000 | Rows per chunk in the matrix build |
| `distance_n_jobs` | -1 | Worker processes (-1 = all cores) |
| `distance_soft_penalty_scale` | 10.0 | Logged but not applied — see known issues |

### `HDBSCANParams`

| Field | Default | Meaning |
| --- | --- | --- |
| `min_cluster_size` | 500 | Smallest admissible cluster |
| `min_samples` | 50 | Core-point density requirement |
| `cluster_selection_epsilon` | 0.0 | Merge clusters closer than this (0 = no merging) |

One instance per discovery pass; the list length sets the number of passes.

---

## 7. Current state and known issues

* **`distance_soft_penalty_scale` is inert.** It is threaded through and logged, but
  `compute_distance_components` always penalises with `distance_penalty_scale`.
* **The phase-1 loop guard is ineffective.** `while assigned_rate >= 0.01` tests the *cumulative*
  assignment rate, which only rises, so passes are never cut short — the loop always runs once per entry
  in `iteration_params`.
* **`HARD_LIMIT` rejection during discovery is commented out** in `map_to_best_composite`, so `NOISE` is
  the only non-`SUBOPTIMAL` reason a discovery pass produces.
* **`BEQComposite.rejected_mappings_for_reason(reason, best_only=False)`** filters on
  `m.is_best == best_only`, so the default returns *non*-best mappings. It has no callers.
* **`plot_distance_by_composite` is a stub** (`pass`), and there is no rejected-curve plotting.
* **The clustering pipeline has no tests.** `tests/` covers `beqanalyser/design/` only (194 tests,
  `uv run pytest`); nothing exercises the clustering path, so there is no fast feedback loop there.

---

## 8. Licence

MIT — see [LICENCE.md](LICENCE.md).
