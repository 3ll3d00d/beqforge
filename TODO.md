# Outstanding work

## Status and priority

The sole backlog and plan for outstanding work, reviewed against code and history on
2026-09-30. Order reflects value to the correctness and accuracy of the generated filter:
known inconsistencies first, then independent evidence and recovery, then conditional
improvements, reporting and speed. It is not an ordering by implementation cost. A blocked
item does not prevent starting the next independent open item. **Open** means actionable,
**blocked** names missing evidence or an external dependency, and **parked** means the
evidence does not yet justify a change; each has a reason and a reopening trigger. Historical IDs
are retained so records and code comments remain traceable. Completed items are in
[implemented changes](plans/done-design-and-pipeline.md),
[research decisions](plans/research-design-decisions.md), and
[baseline evidence](plans/done-baseline-evidence.md). The
[R2a implementation record](plans/R2a-server-stage-cache.md) is complete; R2b is complete too.

| Priority | ID | Status | Value, work and blocker or reason for parking |
| --- | --- | --- | --- |
| 1 | Playback contract | open | Reconcile the supplied bass-management model with the model actually used for targets, verification and clipping. Only `lpf_fs` is consumed today; check the ignored fields before claiming the listener's clipping cost. Caller propagation is an external subtask. |
| 2 | E10 | open | Predeclare fresh content-goal validation before further tuning or a default change. Existing seeds and corpus have repeatedly informed development; writing the protocol needs no new audio. |
| 3 | E1 | open | Add record-only scene-held-out verification: evidence independent of the material that generated the target. A gate needs a separate demonstrated benefit. |
| 4 | Steep-filter scoring | open | Implement coloured/codec-like floors and recipe-specific truth bands under E10; inspect shape failures and published-ceiling excess. Existing titles can supply programme texture. |
| 5 | Steep-filter default | blocked | Recovery improves substantially with `--content-edge`, but changing the default needs E10, the scoring above, listening judgements and more independent real steep titles. Safe House already works with the default; keep the option off meanwhile. |
| 6 | F2 / device behaviour | in progress; first hardware pilot measured | Coefficient quantisation does not establish hardware accuracy. Limit changes need measured internal arithmetic/noise/limit cycles on a named device and a capture setup; the [measurement plan](plans/F2-device-precision-validation.md) specifies Python sweep/capture, optional REW cross-checks, software controls, single-entry/full-catalogue analysis and a standalone cross-platform executable. The `beqforge-device-check` preview includes frozen manifests, capture/recovery, CLI-only miniDSP controls (minidsp-rs 0.1.12, batched through `-f`) with float32 transport attribution, staged qualification/convergence, uncertainty-aware filter checks, entry/unique-cascade frequency distributions and matched-device deltas. First verified pilot on a miniDSP 2x4 HD (USB loopback, 96 kHz): the device plays its float32 coefficients as predicted (worst 0.0074 dB, 2-200 Hz), while float32 coefficients themselves put 18.8 dB of error into a 5 Hz Q 6 peak; see the plan, section 12. First catalogue sample (50 cascades): 49 play as predicted on every bin (worst 0.0082 dB); the 50th was clipped by the device and is to be remeasured (F2a, plan section 13). Next: the `grid` and `boundary` suites on hardware to map where float32 coefficients stop representing low, high-Q filters. No Q-limit change yet. |
| 7 | Validation coverage (former TODO 10) | blocked | Broad real-programme generalisation needs the missing shapes and independently characterised paired releases listed below. Sparse titles exist; their absolute truth and wider sparse coverage remain missing. |
| 8 | Identification | blocked | Generalising `N(f)` and its fit band needs independent, varied source material, especially paired releases. Sensitivity experiments can proceed; programme-only uncertainty cannot identify the cause of a droop. |
| 9 | E4 | parked | No measured failure has been attributed to isolated ceiling holes. Reopen if unevenness or E9 excess is traced to such bins; smoothing may only reduce the raw licence. |
| 10 | F4 follow-up | parked | Both fitter-objective selection spikes lost passes/true positives. Judge several fits only with a demonstrated usable alternative discarded before `_judge`; a smaller residual is insufficient evidence. |
| 11 | F3 follow-up | parked | A fifth section moved no verdict when tried and costs more fitting. Reopen if an evidence-supported target has a demonstrated usable fit beyond four sections and no usable fit within four. |
| 12 | T2 | parked | The steep-variant audit found no swept cap binding a weak winner. Derive caps only when a binding cap demonstrably prevents a better supported result. |
| 13 | Residual (former TODO 5) | open | Correct the reported target error and its actual measurement band without changing fit selection. Primarily audit accuracy; any escalation/objective change is a separate, higher-impact decision. Non-parametric reporting is already allowed upstream. |
| 14 | Authored features | parked | Manual `--exclude` works; no validated automatic detector exists. Reopen with real labelled features and negatives showing that detection preserves legitimate bass. |
| 15 | Dynamic processing (former TODO 11) | parked | No suspected real case has scoped a useful tripwire. Reopen when compression/limiting demonstrably compromises this correction; non-LTI processing alone does not prove every BEQ is invalid. |
| 16 | Tilted passband reference (goal/corpus follow-up) | parked | No real in-sub-band case needs a sloping reference yet; Dossier's abstention was decided. Reopen with one. Goal-aware corpus labels belong to the open E10 protocol work. |
| 17 | Mixed-channel policy | parked | `channel_scope` is currently an unpopulated optional response field, not a computed `mixed` finding awaiting a gate. Reopen with a case where existing per-channel restoration and common pricing produce an unsuitable mix correction. |
| 18 | Fraction dial (former TODO 7) | parked | No user/title has needed partial licensed restoration as a preference; tilt and tolerance already ship. Reopen with a concrete requested outcome, then price and validate it like every target. |
| 19 | Protective corner (former TODO 9) | parked | The corner is already derived from boost cap and implied order, floored by `lowest_frequency_hz`. No case requires an independent override or different fallback alignment; reopen with one. |
| 20 | Device configuration on the wire | parked | The current contract deliberately omits device preference; server flags already configure realisation. Reopen if one server must serve different device formats/rates per request; then agree an upstream extension. Hardware validity remains F2. |
| 21 | Catalogue comparison (former TODO 8) | parked | A disagreement detector has no demonstrated accuracy benefit. Reopen with an independent discrepancy to investigate; authored filters remain comparisons, never calibration targets. |
| 22 | Performance | parked | Further reuse changes cost, not filter accuracy. Reopen after measuring repeated numerical identities or material remaining analysis cost; missed-fit search belongs to F3/F4 instead. |
| 23 | Chart peak bias | parked | Deliberate catalogue-compatible per-bin maximum; it affects presentation only. Reopen if a reader needs an alternative percentile view; keep it distinct from the 95th-percentile evidence envelope. |
| 24 | Documentation citations | open | Remove or repoint orphan references and stale descriptions of shipped behaviour. Low filter impact, but prevents future changes being based on obsolete assumptions. |

## Review evidence

F2 also tracks the [catalogue filter optimisation design and initial implementation](plans/F2-catalogue-filter-optimisation.md):
reproduce a published filter's ideal response more accurately on a named device, using only
that filter. Deliver as the `beqoptimiser` package in the single `beqforge[optimiser]` distribution profile,
used by beqcatalogue to publish device-specific
variants consumed by ezbeq, supporting 48/96 kHz with extensible precision models.
Search only above a configurable maximum error margin (default 0.5 dB); publish a replacement
only when it meets that same margin.
The library/CLI now implements direct-coefficient search and numerical validation;
development examples show some qualifying replacements and correctly withheld partial improvements.
The [static whole-catalogue report](docs/optimiser-report/README.md) now evaluates all 15,323 entries
at both rates: 11,871 entries gain qualifying replacements at one or both rates; failures
retain the originals in the aggregate curves. The library now automatically reuses numerical
results, with a bundled seed covering all filter-bearing entry/rate cases and configurable
disk caching; entry metadata is rebuilt on every call. Catalogue/ezbeq publication integration
remains open.
The [package consolidation](plans/F2-package-consolidation.md) puts all three independent
workflow packages in one versioned distribution with optional dependency profiles and
separate commands; shared arithmetic lives beneath them in `beq_common`.
Next: agree beqcatalogue/ezbeq variant and loading contracts, freeze catalogue evaluation and
verify selected pairs on hardware. Parameter search and cascade refits remain follow-ups;
no catalogue-wide or hardware-validated benefit is claimed. This work does not
change the audio-derived pipeline or establish whether an authored BEQ suits its film.

The consolidation at `4b11827` retained most work, but put a reporting issue above evidence
quality, called actionable protocol work parked, and treated confirmation of already-adopted
contract wording as blocked. This review restores the chart-bias follow-up and separates
actionable steep-scoring work from the externally dependent default decision. No pipeline
behaviour, tolerance or baseline record changes here.

Evidence behind the order and the parked decisions:

* [F1 implementation](plans/done-design-and-pipeline.md#implementation-outcomes), commits
  `5054ae4` and `e62be2a`: noise-floored steep acceptances improved **17/18 → 18/18** with
  the option on. The 17/18 figure belongs to the earlier prototype; default-mode 2/18 is
  the earlier comparison, not a fresh measurement in this review.
* [Research outcomes](plans/research-design-decisions.md#measured-outcomes), `352206f`,
  `c34465c` and `4d04e97`: F4 lost true positives; weak steep winners mostly lost better
  candidates at acceptance, not ranking/cap selection; T8's confidence-bound floor cost
  correction without consistently improving stability. These do not justify another
  speculative ranking, cap or floor change.
* [E9 audit](plans/done-design-and-pipeline.md#implementation-outcomes), `6d0989f`:
  accepted steep variants exceeded the ceiling by up to 4.0 dB over 0.58 octave; the corpus's
  filtered/1 reached 5.6 dB over 0.28 octave. Real-title candidates stayed below 0.5 dB.
  Audit this with steep policy; it is not evidence specifically of single-bin holes or
  permission to add a blanket gate.
* [`designer._to_design_candidate`](beqforge/designer.py) forwards `fit_error_db` and the
  run's residual band, while [`filters._fit_structure`](beqforge/filters.py) returns a
  target-error/device-drift objective and [`design._result`](beqforge/design.py) recomputes
  pure target error. The actual fit score band can widen beyond the reported one.
* The sibling [`designer-interface.md`](../beqdesigner/design/designer-interface.md)
  §§2–4 already adopts clipping cost, bass management, ordinal confidence, non-parametric
  residuals and decline/report rules. It deliberately excludes device preference.
  [`designer.design`](beqforge/designer.py) uses only the supplied crossover;
  [`DesignJob.run`](../beqdesigner/src/main/python/model/batch.py) and the library's
  [`_design`](../beqdesigner/src/main/python/pipeline/library/run.py) omit bass management
  when calling helpers that support it. These are code/contract issues, not missing
  contract evidence.

## Checks and scope

### Playback contract

The contract's bass-management input includes crossover, low-pass position, headroom type
and clipping flags. `designer.design` changes only the crossover, leaving fixed mains/LFE
gains and an always-on mains-plus-bus LR4 model. The supplied headroom model can therefore
differ from the one behind `gain_reduction_db`. Playback also feeds counterfactual summation,
the sub-band blocker and verification, so determine which differences change the filter or
its verdict and which only change clipping reports.

Compare the same channels and cascade against beqdesigner's actual bass-management path,
including WCS versus numeric headroom, LFE presence/channel count and low-pass Off. Resolve
which fields describe linear playback and which describe simulation of clipping before
deciding how to support them. Any unsupported configuration must be described honestly;
supplying a dict is not enough to claim it was modelled. No hardware capture is needed for
these software comparisons. Caller propagation requires a change in beqdesigner, outside
this repo; both its batch job and library call omit the available argument today.

### Residual reporting

`Candidate.fit_error_db` reaches the response's `residual_db`. For fitted candidates it is
normally the larger of target error and exact-coefficient quantisation change; after pruning
it can be pure target error. The contract already permits residuals for every method with an
explicit target and defines them as maximum absolute target error. Recompute the reported
error from the canonical published cascade against its priced target on a stated band; make
the evaluation rate and coefficient treatment explicit. Carry or recompute the actual band:
`_fit_all` can widen it above `params.residual_band_hz`, and parametric proposals carry their
own effective design settings. Keep the optimisation objective, drift screen and escalation
unchanged in a reporting fix. Changing what `residual_target_db` compares against is a
separate decision change and needs the full regression workflow. A small residual says the
fit matched the constructed target, not that the target is correct.

### Fresh validation protocol and steep-filter policy

The legacy corpus is development evidence after repeated tuning, not a held-out estimate.
Version a new protocol without editing old results. This is actionable now; acquiring new
real holdouts is the separate coverage dependency. Predeclare coloured, nonstationary and
correlated noise, finite stopbands, limited programme, sparse/continuous bass, channel
cancellation and partially filtered channels; partition seeds and source titles (variants of
one title are not independent), goal settings, failure classes and sample sizes. Preserve
legacy counts. Resolve the goal/corpus follow-up here: specify which goals license shaping,
which cases must abstain and why; assess restoration accuracy, unsupported/noise gain and
selection quality as well as counts.
Choose sample sizes from the desired interval bound: 0/45 development negatives is not
evidence of a zero population rate, and nine cases per shape provide weak bounds.
Once holdouts inform tuning, reserve a new holdout.

The first `--content-edge` experiment accepted 17/18 noise-floored steep injections against
2/18 with the default; F1 subsequently brought the opt-in to 18/18 (review evidence above).
These are development results, not independent safety estimates. The option
can lift noise where loud events clear a floor that dominates the average. Listen to the
Hulk BW16 @ 30 Hz, −80 dB variant (+16.8 dB noise lift), and the −40 dB-floor case whose
corrected noise lies 28 dB below the plateau. Obtain real steep titles such as Master and
Commander, Kingdom of Heaven DC, Hunger Games: Songbirds & Snakes, Nobody, Wreck-It Ralph,
Battleship, Mad Max 2 and Midnight Run. Safe House is already on hand and accepts a steep
finite-stopband correction with the default, so steepness alone is not the missing ability.
The open scoring work can proceed on existing real texture: test codec-like/coloured floors,
finite stopbands and partial-channel filtering; declare each recipe's truth band instead of
the scorer's fixed 60 Hz top and compute corrected noise from its actual spectrum rather
than the white-floor formula. Review shape-clause failures that discard the closest-to-truth
candidate in both modes, along with E9's excess in the published response. Do not assume a
ceiling gate or a shape exemption is the answer; both can discard usable partial recovery.
A default change waits on E10 and the missing listening/independent-title evidence.

### Device behaviour and held-out verification

F2 requires a named device, known rate/coefficient format, a signal/capture path with enough
low-frequency dynamic range, and real measurements of internal word length, recursive
rounding noise and limit cycles. Those measurements are the blocker, not writing the
harness. The [F2 measurement plan](plans/F2-device-precision-validation.md) defines the
miniDSP loopback with sounddevice/pyfar, optional REW cross-checks, identity-normalised
exact/stored-coefficient comparisons, arithmetic checks, CamillaDSP/JRiver controls and a
standalone cross-platform executable with single-entry/full-catalogue modes; qualify the bench before executing its frozen matrix. Compare sections at Q 5.2–6.0 with unconstrained fits and the device's measured
output before deciding the limit; coefficient quantisation alone does not model its arithmetic.

**F2a — remeasure the catalogue sample after the clipping fix.** The one cascade in
`results/20261005T192911Z` that failed against prediction (*Mojin: The Worm Valley*) was
clipped by the device: the level screen used the sent float64 gain (+32.5 dB) rather than the
stored float32 gain (+48.8 dB), and the 2x4 HD saturates at −0.012 dBFS, under the old 0.999
clipping test. Both are fixed (plan section 13). Next: regenerate the catalogue manifest and run
verify again; expect all 50 to be judged on (nearly) every bin, and Mojin's result to say
something about the device rather than about clipping.

E1: derive evidence, reference, target and cascade from separated scene blocks, evaluate the
fixed correction on the other fold, then swap. Guard filter/window edges so an event does not
cross folds; do not concatenate excerpts and call them complete programmes. Scene-specific
bass is content, so do not demand flatness in every scene. Report first: demonstrate that a
deliberately overfit target is exposed out of sample and quantify variability on valid
injections and real titles. Reporting alone changes no acceptance counts. Only consider a
gate after demonstrating fewer false accepts without losing true positives on fresh E10
evaluation; the existing development corpus is a regression check too.

### Parked decision changes and watch cases

E4's proposed running-minimum ceiling must never license gain unsupported by the raw ceiling.
F3's fifth section moved no verdict when tried; fit cost grows with section budget. F4's two
fitter-selection spikes were rejected: acceptance judges something different from residual.
A follow-up would carry several publishable fits through `_judge`, then select by verdict.
T2's cap sweep did not explain weak winners. Revisit only with a binding example.

Watch near-texture-blocker cases: Black Bag (1.08×), Bugonia (1.09×), Incredible Hulk (1.01×).
Obsession has a narrow level-dependent band ending its level-independence run; decide whether
its omission from the response matters if a reviewer needs it. T8's point floor agrees with
the modal resampled floor on tested titles; revisit only if they disagree. T7's floor and
1024/4096-sample resolution review found no verdict depending on it; revisit with injected
floor evidence. Reopen E7 only if the plateau rule changes.

### Performance and remaining product questions

Measure identical numerical fit requests before gathering parametric targets into `_fit_all`
and deduplicating. Identity includes target, grid, score/placement bands, bounds, seeds and
realisation; preserving each strategy's scoring matters. Only then consider a bounded atomic
cross-run fit cache keyed on that identity, implementation and library versions, honouring
`--fresh`/`--no-cache`; never cache verdicts or headroom. Check repeated `mean_spectrum`,
`plateau_reference`, `_flat_deficit`, `supported_mix_change` and counterfactual-cap blocks
without merging different estimators. More seeds, warm starts or reparameterisation need a
measured missed usable fit. Precision/budget trades measured around 1.4× carry a quality cost
and were not adopted. Headroom acceleration and stage timing already ship (C4/C5).

Identification still needs a generalisable `N(f)` model/fit band and a specified uncertainty
method. Scene segmentation must be evaluated against false positives, not one title. There
is no computed response-level channel scope or mixed-channel policy; the adapter leaves the
optional field unset despite the available per-channel diagnosis. Automatic authored-feature
exclusions remain manual via `--exclude`. `parametric` stays on by default and does win titles:
model work must show an improvement in the final priced and judged correction, not just a
better fit to `N + A`. A sampling interval would not resolve the observational equivalence
between natural colour and a mastering filter.

Catalogue disagreement is an untested hypothesis: steep authored corrections may be
under-realised by single shelves. Look at disagreements rather than treating them as scores.
Dynamic processing needs a real suspected case before designing its tripwire.

Upstream wording is already confirmed in the local contract, including non-parametric
residuals. Passing device realisation per request would be a new contract decision, not
confirmation of an adopted field; server flags already supply it. Bass-management propagation
and semantic fidelity are the playback item above. By-reference support on both sides is
already complete. Chart maxima deliberately retain duration-dependent bias for catalogue
comparison; extraction's evidence envelope uses a percentile instead, so changing charts
would not improve the generated filter.

## Validation material and completion rules

Every decision change follows [AGENTS.md](AGENTS.md)'s regression workflow. Write its outcome
in the appropriate completed/research record in `plans/`, and remove or update its status row
here in the same commit. Preserve baseline records; scratch check runs must not overwrite them.


Real audio tests generalisation to programme the tool has not seen; constructed cases test
known failure mechanisms and differential injection supplies known changes on real texture.
All three are needed. Describe tracks by the structure they test, not by title. Each real
track must be a complete programme (the tool abstains on an excerpt), with an explicit
channel layout so `extract` accepts it. Black Bag already supplies sparse material with an
in-band tracking floor; Dossier supplies a dialogue-led abstention. The missing coverage is
additional independent sparse examples and characterised truth, not the absence of any
sparse title. The [baseline coverage](plans/done-baseline-evidence.md#baseline-2026-09-26-track-set)
still lacks paired releases, old/upmixed material, continuous-bass concert films, heavily
compressed and noise-dominated material, 2.0 and long/short pairs.

### Per-track metadata to record

Layout and LFE presence; source codec and bit depth; whether it is a complete programme;
runtime; whether it is believed filtered, unfiltered or unknown, and how that was established.
The last matters most: a belief with no independent source is not ground truth.

### The shapes

| Shape | What it provokes | Items exercised |
| --- | --- | --- |
| **Paired releases of one mix** (an original and a remaster, or a lossless and a lossy release of the same soundtrack) | Independent reference for a mastering change after alignment and gain matching. Establish that the difference is a filter: remixing, dynamics, edits and codecs can also differ. Codec-only variants test noise-floor and ceiling robustness. | E1, E2, E6, A1 |
| **Bass-rich, high-dynamic-range modern mix with full LFE** | The positive control: large events, quiet passages, a clean floor. Every change must keep it working. | all (regression) |
| **Bass-light, dialogue-driven drama** | The sparse case the guard exists for; few independent loud events, so wide standard errors. Best if its tracking floor sits *inside* the content band. | E2, E4, T7, Validation coverage |
| **Old or upmixed mix** (mono or stereo origin, no real LFE) | Natural droop that looks like a mastered rolloff. `counterfactual` can restore mains without LFE; assess the correction against its declared goal without treating absent LFE as proof that nothing can be restored. | E2, E6, T3 |
| **Concert or music film** | Continuous bass with few genuine quiet frames: the quiet estimate may contain programme and suppress the contrast licence. | E4, E5, T5 |
| **Heavily compressed or limited mix** (loudness-war, trailer-style) | Dynamic processing may undermine contrast or level-independence evidence. Establish which corrections become wrong before designing an abstention tripwire; compression by itself need not invalidate a spectral correction. | E2, E6, Dynamic processing |
| **Noise-dominated location recording** (documentary, stationary rumble) | Stationary noise at low frequency; the ceiling must license nothing there. | E2, E4, E5 |
| **Strongly rippled or humped bass** (a 40-80 Hz hump, or a mid-bass shelf above the sub) | Plateau choice and the anchor: a wide hump can win "widest first" and a wobbly plateau can drag the anchor. | T4, T5 |
| **Authored LFE feature** (a narrow hump in the LFE) and **LFE lowpass variation** (different lowpass corners across releases) | The `--exclude` path, and whether a channel is judged filtered. | T3, T2 |
| **Layout variety** (2.0, 5.1, 7.1, and a bed from an object mix) | Downmix weights, the LFE gain assumption, and the `"mixed"` channel-scope case with no policy. | T1, Identification |
| **Infrasound-rich mix** (content below 10 Hz) | The 5 Hz placement floor and the flat hold below the noise floor. | E5, T7 |
| **Long and short programmes of similar character** | How the standard errors and the ceiling scale with the number of independent events. | E4, E2 |

Aim for at least two real examples of each shape; a single example cannot separate a track's
quirk from the shape's.

### Variants generated from each real track

The real tracks supply content; known transforms supply **differential** truth. An injection
does not require a known-unfiltered original: score the additional change against the
original, whose unknown mastering then cancels. Neither that nor comparison with the
original's own correction proves absolute restoration accuracy. Absolute positive/negative
labels need independently established truth; an unknown as-is track is not a negative.
Commit recipes for:

1. **As-is** — the baseline record.
2. **Injected known rolloff:** vary corner (roughly 15-40 Hz), order (2-4 and steep 8/12/16),
   family (Butterworth and Linkwitz-Riley), finite stopband and channel subset. Declare the
   recoverable band and score recovery, noise lift and which candidate was selected.
3. **Natural-droop controls:** intrinsically coloured known sources, with acceptance/shaping
   rates reported separately (E6), not gated as distinguishable mastering negatives. Applying
   the same high-pass to every channel is also the positive injection above: it cannot
   become an independently distinguishable negative merely by renaming its provenance.
4. **Added noise at a stated spectrum/SNR:** steady rumble, white, coloured, nonstationary
   and cross-channel-correlated floors, including noise added after the filter. Measure the
   corrected floor as well as cascade gain; keep the true programme/noise arrays or spectra.
5. **Excerpted:** 20% and 50% of the programme, explicitly marked `coverage="excerpt"`,
   which must abstain. This tests coverage policy; undisclosed excerpts cannot be assumed
   detectable from their audio alone.
6. **Re-encoded:** through the codecs a release would use, for noise-floor stability.
7. **Non-default playback model:** different `--main-gain-db`, `--lfe-gain-db` and
   `--crossover` on the same track (T1).

Each variant is a separate `.npz` under `data/`, which stays gitignored, and each gets its own
run record. The variant recipe (seed, transform, parameters) is what should be committed, so
they are reproducible without committing audio.

### What to measure on every track

* Accepted or abstained, which strategy won, and the section count and filter.
* `recovered_fraction`, `shaping_fraction`, `correction_support_score`, and the note that the
  ceiling bound; published `evidence_excess`, including unsupported bins and exclusions.
* Plateau region and level, deficit anchor, noise floor and judged band, so T4-T7 can be read
  straight from the records.
* The held-out verdict (once E1 exists) and the false-accept and true-positive tallies by shape.
* For known transforms, recovery/overshoot in the declared truth band, noise after correction
  and whether selection discarded a better valid candidate. Compare the published device
  response rather than raw optimiser parameters.

### Definition of enough

Every decision change must complete AGENTS.md's regression workflow on available material
and record its limits. A claim of broad real-programme correctness additionally needs at
least a positive control, sparse material, a natural-droop control and a characterised
paired release, with outcomes recorded under `plans/`; that claim is currently blocked by
the missing paired releases and independent truth. Do not imply that development-corpus
success closes it. A change that only speeds a run up needs `compare_records.py` to show
the records are identical apart from the fingerprint and timings.
