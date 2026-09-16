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
| `beqanalyser/design/` | Automated filter design — a **separate capability**, not part of the clustering pipeline above. Derives a BEQ filter from a film's audio rather than summarising existing ones; the pipeline runs material → extraction → diagnose → target → fit → verify. See "Working on `design/`" below for what it does and why, and `TODO.md` for what's still open. |
| `beqanalyser/design/material.py` | Loads extracted signals (`.npz` from `tools/extract.py`) into the shapes `designer-interface.md` names, and models the bass-managed sub feed a BEQ actually operates on. |
| `beqanalyser/design/extraction.py` | Signal → mean spectrum, peak/quiet envelopes, per-bin partial coherence, and the per-bin block-bootstrap standard error the boost ceiling is priced from. |
| `beqanalyser/design/rolloff.py` | The soft-hinge attenuation model and its fit. An identity for Butterworth and Linkwitz-Riley, so it *identifies* rather than approximates. |
| `beqanalyser/design/identify.py` | Fits `E(f) = N(f) + A(f)` — separating the rolloff from the content it sits in. **The weakest link — diagnostic and confidence only, not on the path to a target; see "Working on `design/`" below.** |
| `beqanalyser/design/design.py` | Inversion: noise ceiling, dials, protective filter, publishable cascade. |
| `beqanalyser/design/filters.py` | High-pass synthesis, the closed-form shelf inversion of §5, and the numerical fallback with its publishability constraints. The fit escalates the section budget across every target at once and is ~75% of a run; `_sos_from_parameters` is a third copy of the RBJ formulae, kept honest by a test. |
| `beqanalyser/design/harness.py` | Synthetic ground truth — known-filter injection and constructed negatives. |
| `beqanalyser/design/verify.py` | Applies a design and measures the corrected low end, **including the error the device's own coefficient rounding adds** — so what is judged is what will play. **The only check that can say a filter is wrong rather than merely inaccurate.** |
| `beqanalyser/design/diagnose.py` | Per-channel decomposition: mix shares, the level-independence test (R2), band tracking, and each channel's own plateau reference. Where the evidence for a rolloff actually is. |
| `beqanalyser/design/accept.py` | The acceptance model. The cliff, flatness, turnover and overshoot tests are comparative and so need no calibrated threshold; the shape request (`target_tilt_db_per_octave` and its tolerances) is a stated preference; realisability is judged on the curve the device will play rather than against a drift constant. Tilt, level and extent judge against *intent* (`before_db` + the evidence-priced target), not flat, so a partial correction is judged on whether it achieved what it was licensed to. `recovered_fraction` and `shaping_fraction` report how much of the deficit was licensed and how much of the correction sits below the level-independence floor; `Candidate.confidence` is a separate, uncalibrated ordinal (`pipeline.correction_evidence_score`), not derived from either. Headroom (`required_offset_db`) is reported, never gated. |
| `beqanalyser/design/pipeline.py` | The repeatable process — diagnose, propose, fit, judge. Holds the `STRATEGIES` registry. |
| `beqanalyser/design/cache.py` | Stage cache — the analysis, and any strategy declaring `cache_modules`. On by default; keyed per stage so work on the fitter does not drop the analysis. |
| `beqanalyser/design/charts.py` | Peak-vs-average charts in the catalogue's axes (linear 1-160 Hz, -10 to -80 dB), plus the loudest second. Fixed colour per channel across every chart. |
| `beqanalyser/design/record.py` | The run record — a fingerprinted, gzipped JSON of everything a run produced, written every run. Ours, not beqdesigner's. |
| `beqanalyser/design/beqd.py` | Export to a `.beq` beqdesigner project. A separate job from the record: idiomatic in their UI, allowed to be lossy. |
| `tools/design_beq.py` | **The entry point.** One command, a filter and its reasoning. `--charts DIR` for the pictures; writes a `.run.json.gz` record beside the material unless `--no-record`. |
| `tools/replay.py` | Redraw charts and export to beqdesigner from a record — no rerun, no extraction. Refuses on a stale record unless `--force`. |
| `tools/extract.py` | ffmpeg → 1 kHz per-channel `.npz`. Requires an explicit supported channel layout; preserves layout provenance. Needs no beqdesigner. |
| `tools/summarise.py` | Sanity-check an extraction before using it. |
| `tools/experiments/` | Approaches that were measured and not adopted, kept with their numbers so they are not rebuilt: the P14 surrogate fitter, the P18 greedy placement, the analytic Jacobian, and the two record comparison tools. See "Performance" under "Working on `design/`" below. |
| `tests/` | Covers `beqanalyser/design/` only; the clustering pipeline has none. `uv run pytest`. |

[TODO.md](TODO.md) is the live backlog for `beqanalyser/design/` — genuinely open questions,
backlog items and known rough edges. Everything in "Working on `design/`" below is what the
shipped implementation actually does today, not a plan for something still to be built.

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
uv run python -m beqanalyser         # clustering pipeline, from the repo root
uv run python tools/design_beq.py data/NAME.npz   # automated design, all strategies
uv run python tools/design_beq.py data/NAME.npz --strategy flatten   # just one
uv run python tools/replay.py data/NAME.run.json.gz --charts charts   # redraw, no rerun
uv run python tools/replay.py data/NAME.run.json.gz --beq out/NAME.beq  # into beqdesigner
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
* The clustering pipeline has no tests, so there is no fast feedback loop there. To sanity-check a
  pipeline change, build a small synthetic catalogue (a few dozen shelf curves with jitter, in three
  groups), run `compute_distance_matrix` + `build_all_composites` with `min_cluster_size≈20`, and check
  the composite count and reject rate. That runs in seconds. `beqanalyser/design/` *is* tested —
  `uv run pytest`.

### Waiting on a long run without leaking shells

A design run is minutes and the test suite is ~2, so an agent working here will want to wait on
something. Waiting is where shells get leaked, and a leaked waiter is a `sleep` loop that outlives
the session and quietly competes for the cores the next run is being timed on.

**One waiter per condition, ever.** Arm it once, record its task id, and *check that id* on later
turns. Do not arm a second waiter on the same condition because the first has not fired yet — that
is how nine of them end up blocked on one `ALLDONE`. If it has not fired, it has not fired.

**Wait on a fact, not on a process.** `pgrep`/`/proc` conditions invert the moment the process
exits, and an empty `pgrep` substitutes into nonsense:

```bash
until [ ! -e /proc/$(pgrep -f thing.py | head -1) ]; do sleep 5; done   # never exits once it dies:
                                                                       # $(...) is empty, so this
                                                                       # tests /proc, which exists
until grep -q ALLDONE run.log; do sleep 30; done                        # exits, and says why
```

Have the job print a sentinel when it is done and wait for that. A run's own output is a fact; a
process table entry is a race.

**Every waiter needs a ceiling.** `sleep` in a loop with no bound is a leak waiting for a crash
upstream. Either bound the loop (`for _ in $(seq 60)`) or make the *job* write the sentinel on
failure as well as success, so the wait ends either way.

**Clean up before you finish.** `ps -eo pid,etime,args | grep shell-snapshots` shows what is still
parked; anything measured in hours is yours and is not coming back. Kill it. This matters more than
tidiness: leftover waiters and queued runs from an earlier session will silently corrupt any timing
measurement taken afterwards, and the numbers look plausible.

**This box suspends, so hold the sleep lock when timing anything.** A run that spans a suspend
reports hours of wall time for minutes of work — measured here at 34,313 s and 15,790 s for runs
that did 210 s and ~250 s of work, with correct output both times. Wrap the command:

```bash
systemd-inhibit --what=sleep:idle --why="beq run" --mode=block uv run python tools/design_beq.py ...
```

Discarding the outlier afterwards is not good enough. A suspend landing inside the fit also skews
the per-run CPU figures `FIT_STATS` reports — one contaminated run measured 21.8 s per optimiser
run against 13.9 s for the same code on the same machine — so a stalled run is unusable for
timing even though its record is sound. Two cross-checks worth keeping: compare the record's own
`total_s` against wall clock, and compare `FIT_STATS`' seconds-per-run across titles. If either
disagrees with its neighbours, the run met a suspend and needs repeating rather than explaining.

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

## Working on `design/`

Deriving a BEQ filter from a film's audio rather than summarising existing ones. `TODO.md` is
the live backlog of what's still open; everything below is what the shipped code actually does
and why — read it before making a change here, since several of these rules were arrived at by
getting them wrong first.

### Principles

* Every per-title decision must come from that title's own data. A fixed frequency band, a
  slope threshold borrowed from one title, or a constant calibrated against the catalogue are
  the same mistake wearing different clothes — several constants here have already been wrong
  this way (see "Never calibrate against the catalogue", below).
* Abstention is the default. A correction is only as good as the evidence for it; when the
  evidence is missing, ambiguous, or the material is an excerpt, the pipeline must decline
  rather than guess.
* Past catalogue-authored filters are a test of a design, never its target. The catalogue
  contains no negatives (nothing known to be unfiltered), so calibrating against it teaches
  nothing about false positives.

### Strategies and evidence pricing

* **Target strategies are first-class and interchangeable.** `flatten` (invert the measured mix
  response), `counterfactual` (restore filtered channels, re-sum, read the deficit) and
  `parametric` (fit and invert a rolloff) all produce a target, all go through the same fitter
  and the same acceptance model, and all run by default. Adding one is a function plus an entry
  in `STRATEGIES`. Select with `--strategy NAME` (repeatable, or `all`). All eight titles on
  hand now accept — `flatten` and `counterfactual` between them win every one; `parametric` has
  never produced the selected filter. No strategy has an opinion of its own: each will invert a
  noise floor as happily as a rolloff, which is what `priced_by_evidence` and `diagnose`'s guard
  are for. **Every strategy that builds a target must price it through `priced_by_evidence`**;
  `counterfactual` did not for a long time, and handed the fitter +35 to +46 dB of boost that no
  measurement supported.
* **The target is the outcome, not a model of the cause.** A BEQ recovers a filtered mix, but
  the outcome is a flat-to-rising response, and inverting the measured response reaches it
  directly. Do not reach for `identify_rolloff` to build a target — it returned "no
  representable alignment" on every real title tried. Identification's remaining role is
  diagnostic and confidence, not target derivation.
* **Missing evidence licenses zero boost, never unrestricted correction.**
  `Envelopes.boost_ceiling` is zero wherever a bin lacks a measurable peak/quiet separation or
  finite bootstrap uncertainty, including deliberately omitted profiling bins. The pipeline
  abstains outright for an excerpt (`Material.coverage != "complete_programme"`), missing
  channel decomposition, no qualifying loud events, or no positively-supported bins. These are
  missing-evidence policies, not confidence thresholds, and do not claim that temporal contrast
  proves a mastering filter — see "Evidence and confidence" below.
* **No fixed frequency band may decide anything per title.** A constant band asserts where the
  interesting frequencies are — it has already failed once: a fixed 22-35 Hz channel reference
  sat on one title's knee and understated its mains by 13-17 dB. Channels and the mix are now
  referenced to their own contiguous plateau (`diagnose.plateau_reference` — widest-then-
  flattest-then-lowest region within 3 dB of the log-frequency 90th percentile, at least a
  third of an octave wide, at most 3 dB/octave of trend), shared by target construction and
  verification. No usable plateau abstains.
* **Authored-feature exclusions (`--exclude LOW HIGH`) omit evidence and request zero
  correction, everywhere** — reference discovery, channel slopes/shares/floors, scene
  selection, coherence, identification, every target strategy and judging, not just the target
  curve. References and smoothing never bridge across an excluded gap, including gaps narrower
  than one sampling interval. If the remaining evidence is still fragmented inside the judged
  band, the pipeline abstains with an explicit reason rather than concatenating the pieces.
* **Start with `uv run python tools/design_beq.py data/NAME.npz`.** It runs the whole process
  and prints the evidence beside the answer; exit status is 0 when a candidate was accepted, 1
  when the correct output was to abstain — neither is an error. The stage cache is on by
  default and skips `diagnose`/`extract`/`identify` and the parametric fit when the material,
  their parameters, their modules and any effective exclusions are all unchanged; `--fresh`
  recomputes and overwrites them, `--no-cache` neither reads nor writes, `--cache PATH` moves
  the file.
* Acceptance rules must be **comparative wherever possible** — corrected curve against input or
  house curve. Every absolute threshold tried so far has been wrong on some title: a fixed 6 dB
  flatness limit sat on the floor of what any smooth cascade can achieve, and a fixed ±3 dB
  envelope rejected a correct filter on one 0.24 Hz bin. Aggregates over the whole band are the
  recurring failure — a step, a turnover and a cliff are all invisible to a mean. Measure over
  the segment that matters.
* **Tilt, level and extent are judged against intent, not flat.** `Correction.intent_db` is
  `before_db` + the evidence-priced target (+ any house curve), so a target `priced_by_evidence`
  clipped is judged on whether the fit achieved what the evidence licensed, not on whether it
  happened to be flat — without this, a filter that did exactly what it was asked failed
  anyway. Overshoot, cliff, wobble-against-material, turnover, section contribution and
  drift/realisability stay judged against the house curve or the material, deliberately: they
  ask *is this filter wrong*, a different question from *did it achieve its intent*, and
  judging them against a target that could itself be wrong collapses into trusting the residual
  (see "Never trust a residual", below).
* **The tilt dial reads in the audio sense; the internal measurement does not.**
  `AcceptParams.target_tilt_db_per_octave` is positive for a low end *rising* toward the
  bottom, the opposite sign convention to `Correction.tilt_db_per_octave`. `assess` negates
  once, at the comparison. Do not add a second negation somewhere else.
* Refine the process by editing `PipelineParams`, `DiagnoseParams` or `AcceptParams`, not by
  writing another one-off script. The point of the driver is that two titles become comparable;
  twenty scratchpad scripts are how the design was first worked out and none of them survived.
* Parametric design and its cache key share `parametric_params`: shared evidence/fitting knobs
  must reach both. `parametric_max_boost_db` is a total-correction preference; `max_gain_db` is
  a per-section realisability bound — not the same knob. Preserve the actual priced target and
  method through every stage, including the parametric route, so partial correction is judged
  against its intent.
* **Never trust a residual.** It says a cascade matches the target it was handed, not that the
  target was right. Five separate outputs have measured well and been wrong on sight — a +15 dB
  peak at 378 Hz, a no-op section at 105 Hz, a +45 dB gain, a shelf placed at 3.22 Hz, and a
  +17.5 dB boost at 21 Hz. Run `verify` and look at the corrected curve; every one of these was
  caught by a person looking, not by a metric.

### Evidence and confidence

* Three separate outputs are required and must not be collapsed into one number:
  **mastering-rolloff support** (unavailable from programme audio alone — a fitted knee, level
  invariance or temporal tracking is a feature, not proof; source coloration and mastering can
  look identical), **correction support** (conditional temporal contrast and its uncertainty,
  `max(1 - z·SE/contrast, 0)`, boost-weighted and scale-free — halving a request without
  changing its shape leaves it unchanged, and it is not a probability), and **preference
  shaping** (choosing a plateau-relative target assumes a desired source spectrum; every
  strategy, including `parametric`, makes this assumption).
* Quiet frames estimate additive noise only if they contain negligible programme content,
  represent the same noise process as loud frames, and the programme is covered adequately (an
  excerpt fails this). Contrast is not SNR: a common spectral gain cancels in the peak-minus-
  quiet difference. Temporal tracking supports recovery only if the measured low-band energy is
  resolved programme energy rather than stopband leakage, correlated noise, or filter
  transients — a steep filter's own stopband output can correlate with level almost perfectly
  and is not content.
* `Candidate.confidence` (`pipeline.correction_evidence_score`) is an **uncalibrated ordinal**,
  fit quality and recovered fraction both excluded by design — there is no labelled corpus to
  calibrate a probability against. It does not reorder `Report.accepted`, deliberately (see
  `TODO.md` item 6). Use `recovered_fraction` (priced target ÷ measured deficit) and
  `shaping_fraction` (share of the realised correction below the level-independence floor) as
  the separate diagnostics they are; the legacy `accept.confidence_from_evidence` is kept only
  for callers of the old arithmetic and must not be revived as the live confidence measure.
* Every channel and the mix carry their own plateau, temporal contrast/error and tracking —
  there is no single dominant channel whose floor becomes the mix's floor. Reported per-channel
  contributions are signed coherent terms (`Re(X_channel·conj(X_sum))/|X_sum|²`), not
  normalised power shares — they can be negative or exceed one under cancellation, and a
  restored channel needs its own contrast and tracking support, priced against its own
  block-bootstrap uncertainty, before it counts.
* The predeclared synthetic validation protocol and its results live in
  `evidence_validation.json` (development seed 101, held-out seed 947): one false acceptance in
  four development negatives, zero in four held-out; both excerpts and both steep-stopband
  positives correctly abstained; both complete positives recovered a partial correction, 17.77
  and 13.11 dB RMS from the full injected inverse. This falsifies the old "temporal contrast
  proves restoration" reading; it does not establish safe automatic restoration of arbitrary
  source material, and **generalisation to sparse real programmes remains unvalidated** — see
  `TODO.md`.

### Publication, playback and verification

* **Headroom is a clipping question on the sub feed, not a master-volume figure.** A BEQ runs
  post bass management on the sub channel only, so a large boost usually costs the listener
  nothing. `PlaybackParams` declares the assumed model (default: historical LR4 mains crossover
  + LR4 sub-bus low-pass, both at `crossover_hz`, mains −20.2 dB / LFE −10.2 dB — CLI
  `--crossover`, `--sub-lowpass`, `--main-gain-db`, `--lfe-gain-db`, `--sub-gain-db`); judge
  headroom with `required_offset_db` on `material.bass_managed_sum` under that model, never by
  the cascade's peak magnitude — measured against the real quantity, peak magnitude is close to
  *inverted* (a +45.7 dB filter needing 0.00 dB of reduction; an +18.2 dB one needing 4.4).
  `required_offset_db` is reported, never gated — there is no `max_gain_reduction_db` in
  `AcceptParams`. What this does not see is excursion (a property of a driver and listening
  level, not of the filter), reported as a diagnostic only.
* **Publication uses canonical rounding, not the optimiser's raw floats.**
  `publication_filters` rounds frequency to 2 decimals, gain to 3, Q to 4, before device
  coefficient quantisation — the same parameters for judging, export and the record. Every
  accepted section must pass strict Jury stability at those exact quantised coefficients
  (`unstable_sections`); the fitter screens the same condition before its sensitivity screen,
  and export refuses to write an unstable accepted filter.
* **Verification applies the actual published, quantised device response, not an
  approximation.** Zero-padded Fourier convolution (`scipy.fft.rfft`/`irfft`) applies the full
  complex transfer — magnitude and phase — of the exact declared device (rate,
  coefficient/integer bits) to the band-limited extraction; this is not "assume the filter
  parameters behave the same at every rate" — measured maximum differences between 1 kHz and
  96 kHz exact responses ran to 2.4 dB on a 200 Hz shelf. Padding covers at least eight seconds
  or twelve decades of pole decay per section, whichever is longer. Unstable publications get a
  response diagnostic for rejection, never a finite waveform/headroom claim.
* Extraction never infers LFE from channel count. Layout identity comes from an explicit
  supported ffmpeg layout, checked for count consistency before decoding; unknown/unsupported
  layouts are refused. Legacy `.npz` files load with an unverified-provenance warning and need
  re-extraction or source-layout verification — relabelling channels cannot fix a wrongly
  weighted stored `mono_mix`.
* **Every run writes a record; use it rather than rerunning.** `tools/design_beq.py` writes
  `data/<name>.run.json.gz` — diagnosis, candidates, verdicts and the chart curves — and
  `tools/replay.py`/`tools/render_ledger.py` redraw charts or export a `.beq` from it in
  seconds, **using the run's own recorded configuration** (strategy selection, exclusions,
  etc.), not a fresh default. The record is fingerprinted on the material hash, the recorded
  params, the git revision, and a content hash over every `design/` module plus the root RBJ
  implementation and the extraction/design/replay/ledger entry points and ledger template
  (`record.RECORD_SOURCE_FILES`) — so successive edits inside an already-dirty tree still
  invalidate it. `replay`/`render_ledger` refuse a stale record and say why; `--force` draws it
  anyway. Extend `RECORD_SOURCE_FILES` when a new dependency lives outside `design/`;
  stage-cache dependency lists are separate and narrower. Legacy records are read verbatim and
  never silently acquire a claim (evidence, publication, playback) they did not actually
  record.
* **The record and the `.beq` export are two different things.** The record is ours and has to
  be exact and complete for re-analysis; the export is beqdesigner's and only needs the
  filters plus the underlying signal. Do not merge them — it would make the cache hostage to a
  schema this repo does not own. beqdesigner is not importable (PyQt6, qtawesome), so its
  schema is reproduced in `beqd.py` and pinned by `tests/test_design_record.py`.

### Performance

* A run is ~40-80 s a title (down from ~100-490 s, 7.18x, every accepted filter's verdict
  preserved); the test suite is ~2 minutes. Run both in the background regardless — see
  "Waiting on a long run" above. The biquad fitter is ~75% of a run; `FIT_STATS` reports its
  own cost breakdown per run.
* **Exact-preserving changes and accuracy-for-time trades must never be mixed in one commit.**
  A run that got faster and also moved is a run that says nothing about either. Validate an
  exact change by reproducing the *whole record* byte-for-byte except the fingerprint and
  timings (`tools/experiments/compare_records.py`); validate a trade by checking the
  *decisions*, not the numbers — which candidates passed, which was accepted, what it
  published (`tools/experiments/compare_verdicts.py`).
* The fit pool leaves a core free (`FIT_WORKERS`); `PARALLEL_FITS = False` forces serial for
  profiling. **Already measured and rejected — don't redo:** replacing the optimiser with a
  smooth surrogate (fragile, or too slow), greedy section placement (this objective is
  minimax, greedy is a least-squares idea), a coarser fit grid (1.24x, not the claimed 2x, and
  it changes every filter), sharing one fit pool across every tier (no effect), scoring
  publication-rounding drift inside the fit's own cost function via jittered evaluations
  (non-smooth, costs more than it buys), and raising `max_sections` past 4 to rescue an
  abstaining title (tested on two titles with real headroom to gain; verdicts did not move and
  one title's wobble got worse, not better — the gap is in what the target asks for, not in the
  section budget). `tol` is not a lever for the optimiser; `maxiter` is. `verify` itself costs
  ~0.3 s and is not worth trading accuracy for.
* A real bug that bit twice: `_fit_structure`'s Nelder-Mead polish must be given the same
  `bounds` as the search that seeded it, or the simplex can walk outside them into parameters
  `BiquadSpec` refuses (a negative Q), crashing a worker mid-run.

### Never calibrate against the catalogue

The catalogue's 3,505 authored `mvAdjust` values look like ground truth for a headroom gate and
are not: a gate built and calibrated against them measured close to *inverted* against the real
quantity (gain reduction actually required on the modelled sub feed) and had to be withdrawn.
More generally, the catalogue has no negatives — nothing in it is known to be unfiltered — so it
cannot validate a false-positive rate, and a per-title decision must never rest on a value
derived from outside that title. This is the recurring failure mode in this subpackage; see
`TODO.md`'s "known contradictions" for the constants still standing in for a measurement.

`data/` holds extracted material and is gitignored. Nothing in it is committed.
