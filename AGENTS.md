# AGENTS.md

Working notes for coding agents. Human-facing detail lives in [README.md](README.md).

## What this is

A research/analysis tool, not a product. It takes the BEQ catalogue (thousands of hand-authored bass-EQ
filter sets, published as JSON by the `beqcatalogue` project), clusters their magnitude responses, and
emits a handful of **composite curves** plus fitted IIR/graphic-EQ approximations of them.

Single package, no CLI, no API, no service. Everything is driven by editing `__main__.py` or the notebook.

## Layout

| File | Contents |
| --- | --- |
| `beqanalyser/__init__.py` | All data classes + the RBJ `Biquad` hierarchy + `rms`/`cosine_similarity` helpers. Everything imports from here; it imports nothing from the package. |
| `beqanalyser/loader.py` | Catalogue fetch/cache, IIR→magnitude conversion, distance matrix construction (`compute_distance_components` is the shared scoring core). |
| `beqanalyser/analyser.py` | HDBSCAN clustering, assignment, composite refinement, fan envelopes. The pipeline proper. |
| `beqanalyser/filter.py` | Fits biquad cascades / 1/3-octave GEQ to composite curves via scipy `optimize`. |
| `beqanalyser/reporter.py` | matplotlib plots, log summaries, CSV export. Presentation only. |
| `beqanalyser/__main__.py` | The one hard-coded run configuration. |
| `beqanalyser/beq.ipynb` | Same pipeline, stage by stage. **Partially stale — see gotchas.** |
| `tests/` | Empty (stale `__pycache__` only). |

[AUTOMATED_DESIGN.md](AUTOMATED_DESIGN.md) is a plan for a separate, not-yet-built capability —
deriving a BEQ filter from an audio track rather than summarising existing ones. Nothing in the table
above implements it. Read it before starting that work; its principles section exists because several
of its rules were arrived at by getting them wrong first.

Dependency direction: `__init__` ← `loader` ← `analyser`; `filter` and `reporter` depend on `__init__`
(and `reporter` on `filter` for the `TableRowConvertible` protocol). Don't introduce a cycle by importing
`analyser` from `loader`.

## Core types

* `Points` — wraps one array in two views: `.full_range` and `.band_limited`. **Not** a numpy array; it
  has no arithmetic operators. Passing one where an ndarray is expected is the most common bug here.
* `Curves(min_freq, max_freq, magnitude, frequency)` — a `Points` for each of magnitude and frequency,
  plus `.entry_count`. All clustering/assignment work uses `.band_limited`.
* `BEQFilter` — one catalogue entry's `mag_freqs` / `mag_db` / `CatalogueEntry`.
* `BEQFilterMapping` — one (entry, composite) comparison. Carries all four metrics plus the combined
  `distance_score`, an optional `rejection_reason`, and `is_best`. One is recorded per pair, kept
  regardless of outcome, so the mapping list is the audit trail.
* `BEQComposite` — `mag_response` (full range) + `mag_response_band_limited`, its `mappings`, and
  `fan_envelopes`. `assigned_entry_ids` = mappings with `is_best` and no rejection reason.
* `ComputationCycle` → `BEQCompositeComputation` (one discovery pass, all its cycles) → `BEQResult`
  (composites flattened across all passes, with sequential ids).

## Invariants to preserve

* Every entry produces exactly one `is_best` mapping per discovery pass — `map_to_best_composite`
  asserts this.
* `assigned + rejected == input count` within a pass — `build_beq_composites` asserts this.
* Fan envelope bands are disjoint; no curve appears in two.
* Composite ids are the index into `BEQResult.composites`; `reporter` indexes axes arrays by `comp.id`,
  so ids must stay dense and zero-based.
* A distance ≥ `distance_penalty_scale` (100) means a hard-limit violation. Code tests against that
  constant rather than the individual limits.

## Running things

```bash
uv sync                              # first time / after dependency changes
uv run python -m beqanalyser         # full pipeline, from the repo root
uv run ruff check beqanalyser        # ruff is a dependency; there is no config section
uv run ruff format beqanalyser
```

Notes:

* Python is pinned `>=3.13,<3.14` in `pyproject.toml`. If the venv's base interpreter has gone missing,
  `uv sync` will silently recreate `.venv` against a uv-managed 3.13.
* `python -m beqanalyser` needs `database.bin` in the CWD. Without it, it downloads the catalogue JSON
  from GitHub and re-derives every magnitude response through `sosfilt`/`freqz` in a process pool,
  rebuilding a ~250 MB cache. `database.bin`, `*.npy` and `beq_composites.csv` are all gitignored —
  never commit them.
* First run on a fresh catalogue selection computes an `N × N` float64 distance matrix. The 2023+
  selection in `__main__` is N≈3000 (a 67 MB matrix); the unfiltered catalogue is several times that
  and the matrix grows quadratically. It is cached to `<data_hash>.npy`, keyed on the hash of the
  *filtered* catalogue, so changing the `load()` predicate invalidates it.
* Every `reporter.plot_*` function calls `plt.show()` and blocks. Don't call them from a headless script
  without setting a non-interactive matplotlib backend.
* There are no tests, so there is no fast feedback loop. To sanity-check a pipeline change, build a small
  synthetic catalogue (a few dozen shelf curves with jitter, in three groups), run
  `compute_distance_matrix` + `build_all_composites` with `min_cluster_size≈20`, and check the composite
  count and reject rate. That runs in seconds.

## Gotchas

* **`Points` lives only at API boundaries.** `fit_all_composites_to_peq` / `_to_geq` / `_to_mag` and
  `plot_assigned_fan_curves` take `Points`; everything beneath them takes plain ndarrays. When adding a
  function, pick one and don't straddle — `Points` has no arithmetic operators, so the failure mode is a
  bare `TypeError` deep in a scipy call.
* **Band-limited vs full-range is a real distinction, not two views of the same thing.** Clustering,
  distance and assignment use `.band_limited` / `mag_response_band_limited`. Filter fitting and its plots
  use `.full_range` / `mag_response`. `plot_composite_evolution` plots the band-limited shape and so takes
  a band-limited ndarray. Mixing them gives silent length mismatches in `np.interp`, not a clean error.
* `BEQFilterMapping.assess()` and the per-metric `RejectionReason` values (`RMS_EXCEEDED` etc.) are dead
  code — superseded by the combined distance score. Only `SUBOPTIMAL`, `NOISE` and `HARD_LIMIT` are
  produced. Don't wire `assess()` back in without checking whether that is intended.
* `distance_soft_penalty_scale` is plumbed through and logged but never applied.
* The phase-1 `while assigned_rate >= 0.01` guard tests a cumulative rate that only rises, so it never
  fires; the pass count is simply `len(iteration_params)`.
* `rms(a, weights)` supports frequency weighting, but every caller passes `None`.
* `BEQComposite.rejected_mappings_for_reason` compares `m.is_best == best_only`, so the default
  (`False`) returns non-best mappings. No callers.
* RBJ biquad formulae exist twice — `filter.py` module functions and the `__init__.py` class hierarchy.
  Fix both or neither.
* `map_to_best_composite` mutates the composites passed in (appends to `comp.mappings`); it also builds a
  `best_composites` list purely to assert. It is O(entries × composites) with per-pair scipy-free numpy
  work — the hot loop.

## Conventions

* British spelling in prose and identifiers (`normalise`, `summarise`, `analyser`, `LICENCE.md`).
* Modern typing throughout: `X | None`, builtin generics, `@dataclass(slots=True)` for params objects,
  `@override` where applicable. Don't reintroduce `typing.Optional`/`List`.
* Config objects are frozen-ish dataclasses extending `DefaultAwareRepr`, which prints only non-default
  fields. Add new knobs there with a docstring under the field, following the existing pattern.
* Logging via `logging.getLogger(__name__)`, f-strings, phase banners as `"=" * 80`. No print statements
  outside the notebook.
* Numeric code stays vectorised over numpy; the distance matrix path is chunked and multiprocessed on
  purpose — preserve the chunking when editing it.
