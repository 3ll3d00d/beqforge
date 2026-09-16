# AGENTS.md

Working notes for coding agents. Human-facing detail lives in [README.md](README.md).

## What this is

Derives a corrective BEQ filter directly from a film's own audio track, rather than summarising
a catalogue of existing hand-authored ones (that's the sibling `beqanalyser` project, which this
repo was extracted from — they share only the RBJ biquad arithmetic). The pipeline runs
material → extraction → diagnose → target → fit → verify, and prints the evidence beside the
answer, abstaining when nothing measures up. See "Working on `design/`" below for what it does
and why, and [TODO.md](TODO.md) for what's still open.

One entry point for file-based use: `tools/design_beq.py`, also installed as `beqforge design`
(`pip install beqforge` / `uv tool install beqforge`). The only other way in is
`beqforge serve-designer`, an HTTP server implementing beqdesigner's `designer-interface.md`
v1.0 §7.1 binding (`beqforge/designer.py` + `tools/designer_server.py`) — everything else here
still holds: no other API, no other service, and the server is a thin transport around the same
`beqforge.pipeline.run`, not a second implementation.

## Layout

| File | Contents |
| --- | --- |
| `beqforge/biquad.py` | The RBJ `Biquad` class hierarchy every filter this package builds is rendered through. Imports nothing else from the package. |
| `beqforge/__init__.py` | Shared design types — `Alignment`, `HighPass`, `BiquadSpec`, `PolePair`, `DESIGN_GRID`, `BIQUAD_BUDGET`. |
| `beqforge/material.py` | Loads extracted signals (`.npz` from `tools/extract.py`) into the shapes `designer-interface.md` names, and models the bass-managed sub feed a BEQ actually operates on. |
| `beqforge/extraction.py` | Signal → mean spectrum, peak/quiet envelopes, per-bin partial coherence, and the per-bin block-bootstrap standard error the boost ceiling is priced from. |
| `beqforge/rolloff.py` | The soft-hinge attenuation model and its fit. An identity for Butterworth and Linkwitz-Riley, so it *identifies* rather than approximates. |
| `beqforge/identify.py` | Fits `E(f) = N(f) + A(f)` — separating the rolloff from the content it sits in. **The weakest link — diagnostic and confidence only, not on the path to a target; see "Working on `design/`" below.** |
| `beqforge/design.py` | Inversion: noise ceiling, dials, protective filter, publishable cascade. |
| `beqforge/filters.py` | High-pass synthesis, the closed-form shelf inversion of §5, and the numerical fallback with its publishability constraints. The fit escalates the section budget across every target at once and is ~75% of a run; `_sos_from_parameters` is a second copy of the RBJ formulae, kept honest by a test. |
| `beqforge/harness.py` | Synthetic ground truth — known-filter injection and constructed negatives. |
| `beqforge/verify.py` | Applies a design and measures the corrected low end, **including the error the device's own coefficient rounding adds** — so what is judged is what will play. **The only check that can say a filter is wrong rather than merely inaccurate.** |
| `beqforge/diagnose.py` | Per-channel decomposition: mix shares, the level-independence test (R2), band tracking, and each channel's own plateau reference. Where the evidence for a rolloff actually is. |
| `beqforge/accept.py` | The acceptance model. The cliff, flatness, turnover and overshoot tests are comparative and so need no calibrated threshold; the shape request (`target_tilt_db_per_octave` and its tolerances) is a stated preference; realisability is judged on the curve the device will play rather than against a drift constant. Tilt, level and extent judge against *intent* (`before_db` + the evidence-priced target), not flat, so a partial correction is judged on whether it achieved what it was licensed to. `recovered_fraction` and `shaping_fraction` report how much of the deficit was licensed and how much of the correction sits below the level-independence floor; `Candidate.confidence` is a separate, uncalibrated ordinal (`pipeline.correction_evidence_score`), not derived from either. Headroom (`required_offset_db`) is reported, never gated. |
| `beqforge/pipeline.py` | The repeatable process — diagnose, propose, fit, judge. Holds the `STRATEGIES` registry. |
| `beqforge/cache.py` | Stage cache — the analysis, and any strategy declaring `cache_modules`. On by default; keyed per stage so work on the fitter does not drop the analysis. |
| `beqforge/charts.py` | Peak-vs-average charts in the catalogue's axes (linear 1-160 Hz, -10 to -80 dB), plus the loudest second. Fixed colour per channel across every chart. |
| `beqforge/record.py` | The run record — a fingerprinted, gzipped JSON of everything a run produced, written every run. Ours, not beqdesigner's. |
| `beqforge/beqd.py` | Export to a `.beq` beqdesigner project. A separate job from the record: idiomatic in their UI, allowed to be lossy. |
| `beqforge/cli.py` | `beqforge <subcommand> ...` — the installed entry point. Strips the subcommand off argv and hands the rest to the matching script in `tools/` unchanged. |
| `beqforge/designer.py` | The `design(request) -> response` adapter between beqdesigner's `designer-interface.md` v1.0 and `beqforge.pipeline.run` — request/response dataclasses, wire-format (de)serialisation and the field-by-field mapping onto `Report`/`Candidate`/`Verdict`. Also `validate_response`, an independent re-implementation of beqdesigner's own §3-§5 rules (that repo isn't importable — PyQt6), called by the server before a response ever goes on the wire. Pure and independently testable; no socket. |
| `tools/design_beq.py` | **The entry point.** One command, a filter and its reasoning. `--charts DIR` for the pictures; writes a `.run.json.gz` record beside the material unless `--no-record`. |
| `tools/designer_server.py` | `beqforge serve-designer` — the HTTP transport (`designer-interface.md` §7.1) around `beqforge/designer.py`. Server-wide flags for device realisation/strategies/exclusions; everything per-title comes from the request. Single-threaded (`http.server.HTTPServer`, not `ThreadingHTTPServer`) on purpose: the fitter forks worker processes (`beqforge.filters.PARALLEL_FITS`) when a fit escalates past one section count, and forking a multi-threaded process risks a deadlock. Costs nothing real — the contract is one synchronous POST per `design()` call. |
| `tools/replay.py` | Redraw charts and export to beqdesigner from a record — no rerun, no extraction. Refuses on a stale record unless `--force`. |
| `tools/extract.py` | ffmpeg → 1 kHz per-channel `.npz`. Requires an explicit supported channel layout; preserves layout provenance. Needs no beqdesigner. |
| `tools/summarise.py` | Sanity-check an extraction before using it. |
| `tools/render_ledger.py` | One HTML report across every `data/*.run.json.gz`. |
| `tools/validate_evidence.py` | Runs the predeclared final-selection protocol against the synthetic harness; see "Evidence and confidence" below and `evidence_validation.json`. |
| `tools/experiments/` | Approaches that were measured and not adopted, kept with their numbers so they are not rebuilt: the P14 surrogate fitter, the P18 greedy placement, the analytic Jacobian, and the two record comparison tools. See "Performance" under "Working on `design/`" below. |
| `tools/smoke_test_exe.py` | Drives a packaged `beqforge` executable's `serve-designer` over real HTTP — a health check, then one real accepted-candidate request (a known-injected rolloff, `strategies=("flatten",)`). Run by `.github/workflows/build-executable.yml` on every platform after packaging; the real request matters because it is the one thing that exercises the fitter's multiprocessing fork/spawn *inside a frozen executable*, PyInstaller's riskiest failure mode (worst on Windows, which re-execs the frozen binary itself under `spawn`) and invisible to `--help`/`/health` alone. |
| `beqforge.spec` | The PyInstaller build recipe for the single `beqforge` onefile executable (every subcommand). Reads its `hiddenimports` straight off `beqforge/cli.py`'s `_SUBCOMMANDS`, since PyInstaller's static scanner cannot follow `importlib.import_module(name)` with a runtime `name` — every dispatched-to `tools/*.py` module has to be named explicitly or the built executable fails at `beqforge <subcommand>` with a missing-module error. |
| `tests/` | `uv run pytest`. |

[TODO.md](TODO.md) is the live backlog — genuinely open questions, backlog items and known rough
edges. Everything in "Working on `design/`" below is what the shipped implementation actually
does today, not a plan for something still to be built.

## Running things

```bash
uv sync                                             # first time / after dependency changes
uv run python tools/design_beq.py data/NAME.npz     # automated design, all strategies
uv run python tools/design_beq.py data/NAME.npz --strategy flatten   # just one
uv run python tools/replay.py data/NAME.run.json.gz --charts charts   # redraw, no rerun
uv run python tools/replay.py data/NAME.run.json.gz --beq out/NAME.beq  # into beqdesigner
uv run ruff check beqforge tools tests   # ruff is a dependency; there is no config section
uv run ruff format beqforge tools tests
```

Once installed (`pip install beqforge` / `uv tool install beqforge`), the same pipeline runs as
`beqforge design data/NAME.npz`, `beqforge replay ...`, `beqforge extract ...`, `beqforge
summarise ...` and `beqforge ledger ...` — `beqforge/cli.py` dispatches each subcommand straight
to the script it names above, so `--help` on either form shows the same thing.

Notes:

* Python is pinned `>=3.13,<3.14` in `pyproject.toml`. If the venv's base interpreter has gone
  missing, `uv sync` will silently recreate `.venv` against a uv-managed 3.13.
* `tools/extract.py` needs `ffmpeg` on `PATH`; nothing else here shells out.
* `uv run pytest` is the whole feedback loop — `uv run python tools/design_beq.py` is not a
  substitute for it, but is the way to sanity-check a change against real material (see "Running
  a design run" below).

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

* RBJ biquad formulae exist twice — `biquad.py`'s class hierarchy and `filters.py`'s
  `_sos_from_parameters`. Fix both or neither; the test asserting they agree is what keeps that
  honest.
* `beqd.py`'s exported `.beq` metadata carries our verdict under a `"beqforge"` key inside
  beqdesigner's free-form `metadata` dict — that schema is pinned by `tests/test_design_record.py`.
  Don't rename it without updating that test.

## Conventions

* British spelling in prose and identifiers (`normalise`, `summarise`, `analyser`, `LICENCE.md`).
* Modern typing throughout: `X | None`, builtin generics, `@dataclass(frozen=True, slots=True)`
  for params objects, `@override` where applicable. Don't reintroduce `typing.Optional`/`List`.
* Logging via `logging.getLogger(__name__)`, f-strings, phase banners as `"=" * 80`. No print
  statements outside `tools/`'s own reporting output.
* Numeric code stays vectorised over numpy.

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
  params, the git revision, and a content hash over every module under `beqforge/` — including
  `biquad.py`'s RBJ arithmetic — plus the extraction/design/replay/ledger entry points and
  ledger template (`record.RECORD_SOURCE_FILES`) — so successive edits inside an already-dirty
  tree still invalidate it. `replay`/`render_ledger` refuse a stale record and say why;
  `--force` draws it anyway. Extend `RECORD_SOURCE_FILES` when a new dependency lives outside
  `beqforge/`; stage-cache dependency lists are separate and narrower. Legacy records are read
  verbatim and never silently acquire a claim (evidence, publication, playback) they did not
  actually record.
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
derived from outside that title. This is the recurring failure mode in this package; see
`TODO.md`'s "known contradictions" for the constants still standing in for a measurement.

`data/` holds extracted material and is gitignored. Nothing in it is committed.
