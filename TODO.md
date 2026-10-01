# Outstanding work

## Status and priority

The sole backlog and plan for outstanding work, reviewed 2026-09-30. Rows are in priority
order; a blocked or parked item is not an instruction to start it. **Open** means actionable,
**blocked** needs external evidence, and **parked** needs the stated trigger. Historical IDs
are retained so records and code comments remain traceable. Completed items are in
[implemented changes](plans/done-design-and-pipeline.md),
[research decisions](plans/research-design-decisions.md), and
[baseline evidence](plans/done-baseline-evidence.md). The
[R2a implementation record](plans/R2a-server-stage-cache.md) is complete; R2b is complete too.

| Priority | ID | Status | Work and condition |
| --- | --- | --- | --- |
| 1 | Residual (former TODO 5) | open | Reconcile reported target error with the fitter's accuracy-plus-drift objective and the upstream contract. |
| 2 | E10 | parked | Predeclare a fresh content-goal validation protocol before changing a default or tuning tolerances. Prerequisite for priority 3. |
| 3 | Steep filters | blocked | Decide `--content-edge`'s default from listening, real steep titles and coloured-noise evidence; keep default off meanwhile. |
| 4 | F2 / device behaviour | in progress; measurements blocked | Device profiles and frozen manifests now ship in `beqforge_device_check`; see [F2 implementation outcomes](plans/F2-device-precision-validation.md). First targets: miniDSP 2x4 HD, 96 kHz/float32, and CamillaDSP reference. Bench qualification and measurements are still required before changing designer assumptions or Q limits. |
| 5 | E1 | open | Add record-only held-out verification by scene; any gate is a separate decision. |
| 6 | Validation coverage (former TODO 10) | blocked | Obtain missing real track shapes and paired releases; validate sparse material. |
| 7 | E4 | parked | Investigate ceiling holes only if an unevenness failure or excess traces to unsupported isolated bins. |
| 8 | F3 follow-up | parked | Try more sections only if a sound steep target demonstrably cannot be realised with four. |
| 9 | F4 follow-up | parked | Judge alternative fits only if a usable alternative is lost before acceptance; account for extra judging cost. |
| 10 | T2 | parked | Derive restoration caps only if a swept cap demonstrably binds a weak winner. |
| 11 | Goal/corpus follow-ups | parked | Reconcile negative labels with requested goals; tilted passband reference only when a title needs it. |
| 12 | Performance | parked | Measure repeated fit identities and analysis work before implementing further reuse. |
| 13 | Identification | blocked | Generalise content model, fit band and uncertainty with a broader corpus; decide mixed-channel policy when needed. |
| 14 | Authored features | parked | Automate manual exclusions when real examples support a detection rule. |
| 15 | Dynamic processing (former TODO 11) | blocked | Scope compression/limiting detection and abstention on a suspected real title. |
| 16 | Fraction dial (former TODO 7) | parked | Add a fraction of licensed restoration when a user/title needs it; goal tilt and tolerance already ship. |
| 17 | Catalogue comparison (former TODO 8) | parked | Test the disagreement-detector hypothesis; authored filters remain comparisons, never calibration targets. |
| 18 | Protective corner (former TODO 9) | parked | Expose `H_protect`'s corner when a non-default alignment is needed. |
| 19 | Documentation citations | open | Remove or repoint orphan bare section references to retired design documents in comments/docstrings. |
| 20 | Upstream integration | blocked | Confirm contract wording and batch bass-management propagation in beqdesigner. |

## Checks and scope

### Residual reporting

`Candidate.fit_error_db` reaches the response's `residual_db`. For fitted candidates it is
normally the larger of target error and exact-coefficient quantisation change; after pruning
it can be pure target error. The contract defines residual as target error. Check upstream
wording on non-parametric candidates before settling field availability. Separating reporting
from the escalation objective may be possible; changing what `residual_target_db` compares
against is a decision change and needs the full regression workflow.

### Fresh validation protocol and steep-filter policy

The legacy corpus is development evidence after repeated tuning, not a held-out estimate.
Version a new protocol without editing old results. Predeclare coloured, nonstationary and
correlated noise, finite stopbands, limited programme, sparse/continuous bass, channel
cancellation and partially filtered channels; partition seeds and source titles (variants of
one title are not independent), goal settings, failure classes and sample sizes. Preserve
legacy counts. Once holdouts inform tuning, reserve a new holdout.

`--content-edge` recovers 17/18 noise-floored steep injections against 2 with the default, but
can lift noise where loud events clear a floor that dominates the average. Listen to the
Hulk BW16 @ 30 Hz, −80 dB variant (+16.8 dB noise lift), and the −40 dB-floor case whose
corrected noise lies 28 dB below the plateau. Obtain real steep titles such as Master and
Commander, Kingdom of Heaven DC, Hunger Games: Songbirds & Snakes, Nobody, Wreck-It Ralph,
Battleship, Mad Max 2 and Midnight Run. Test codec-like/coloured floors and declare each
recipe's truth band instead of a fixed 60 Hz top. Review shape-clause failures that discard
the closest-to-truth candidate in both modes. A default change requires E10 first.

### Device behaviour and held-out verification

F2 requires real-device measurements of internal word length, recursive rounding noise and
limit cycles; coefficient quantisation alone does not model them. Compare sections at
Q 5.2–6.0 with unconstrained fits before deciding the limit.

E1: derive evidence, reference, target and cascade from separated scene blocks, evaluate the
fixed correction on the other fold, then swap. Guard filter/window edges so an event does not
cross folds; do not concatenate excerpts and call them complete programmes. Scene-specific
bass is content, so do not demand flatness in every scene. Report first: an overfit target
should fail out of sample, with fewer corpus false accepts and no lost true positives before
considering a gate.

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
is no policy for `channel_scope="mixed"`; automatic authored-feature exclusions remain
manual via `--exclude`. `parametric` stays on by default and does win titles.

Catalogue disagreement is an untested hypothesis: steep authored corrections may be
under-realised by single shelves. Look at disagreements rather than treating them as scores.
Dynamic processing needs a real suspected case before designing its tripwire.

Upstream: confirm the adopted clipping-cost field, request bass management and device
realisation, ordinal confidence, non-parametric residuals and decline/report rules in the
external contract. Thread batch bass management through beqdesigner's `_design` so
`gain_reduction_db` reflects the listener's crossover. This repo cannot close those checks
without upstream evidence; by-reference support on both sides is already complete.

## Validation material and completion rules

Every decision change follows [AGENTS.md](AGENTS.md)'s regression workflow. Write its outcome
in the appropriate completed/research record in `plans/`, and remove or update its status row
here in the same commit. Preserve baseline records; scratch check runs must not overwrite them.


The tracks need to be real audio because the risk being tested is the tool meeting material it
has not seen (Validation coverage: "watch for the right material rather than manufacturing another synthetic
case"). What they need to give is *known structure*, so the tracks below are described by the
failure they provoke, not by title. Each must be a complete programme (the tool abstains on an
excerpt), with an explicit channel layout so `extract` accepts it.

### Per-track metadata to record

Layout and LFE presence; source codec and bit depth; whether it is a complete programme;
runtime; whether it is believed filtered, unfiltered or unknown, and how that was established.
The last matters most: a belief with no independent source is not ground truth.

### The shapes

| Shape | What it provokes | Items exercised |
| --- | --- | --- |
| **Paired releases of one mix** (an original and a remaster, or a lossless and a lossy release of the same soundtrack) | The only real ground truth for a mastering change: the difference between the two is the filter. Also codec-only variants for noise-floor and ceiling robustness. | E1, E2, E6, A1 |
| **Bass-rich, high-dynamic-range modern mix with full LFE** | The positive control: large events, quiet passages, a clean floor. Every change must keep it working. | all (regression) |
| **Bass-light, dialogue-driven drama** | The sparse case the guard exists for; few independent loud events, so wide standard errors. Best if its tracking floor sits *inside* the content band. | E2, E4, T7, Validation coverage |
| **Old or upmixed mix** (mono or stereo origin, no real LFE) | Natural droop that looks like a mastered rolloff; no LFE channel, so `counterfactual` has nothing to do. | E2, E6, T3 |
| **Concert or music film** | Continuous bass with no quiet frames, so the quiet-frame assumption fails and contrast is near zero everywhere. | E4, E5, T5 |
| **Heavily compressed or limited mix** (loudness-war, trailer-style) | A non-LTI process no linear filter inverts (Dynamic processing). Not a target, a tripwire: the tool should abstain or say so. | E2, E6 |
| **Noise-dominated location recording** (documentary, stationary rumble) | Stationary noise at low frequency; the ceiling must license nothing there. | E2, E4, E5 |
| **Strongly rippled or humped bass** (a 40-80 Hz hump, or a mid-bass shelf above the sub) | Plateau choice and the anchor: a wide hump can win "widest first" and a wobbly plateau can drag the anchor. | T4, T5 |
| **Authored LFE feature** (a narrow hump in the LFE) and **LFE lowpass variation** (different lowpass corners across releases) | The `--exclude` path, and whether a channel is judged filtered. | T3, T2 |
| **Layout variety** (2.0, 5.1, 7.1, and a bed from an object mix) | Downmix weights, the LFE gain assumption, and the `"mixed"` channel-scope case with no policy. | T1, Identification |
| **Infrasound-rich mix** (content below 10 Hz) | The 5 Hz placement floor and the flat hold below the noise floor. | E5, T7 |
| **Long and short programmes of similar character** | How the standard errors and the ceiling scale with the number of independent events. | E4, E2 |

Aim for at least two real examples of each shape; a single example cannot separate a track's
quirk from the shape's.

### Variants generated from each real track

The real tracks supply content; the harness (`beqforge/harness.py`) supplies ground truth by
transforming them. For each track that is believed unfiltered (or as close as can be
established):

1. **As-is** — the baseline record.
2. **Injected known rolloff:** vary corner (roughly 15-40 Hz), order (2-4) and family
   (Butterworth and Linkwitz-Riley). Ground truth for recovery, and the source of the positive
   side of every false-accept/true-positive curve (A1).
3. **Injected natural droop:** the same transform applied identically to *every* channel, which
   is observationally the same as a mix that was recorded that way. It is the hard negative:
   the tool should be seen to accept or abstain here, and the rate written down (E6).
4. **Added noise at a stated SNR:** steady rumble and broadband, to test the ceiling and floor.
5. **Excerpted:** 20% and 50% of the programme, which must abstain.
6. **Re-encoded:** through the codecs a release would use, for noise-floor stability.
7. **Non-default playback model:** different `--main-gain-db`, `--lfe-gain-db` and
   `--crossover` on the same track (T1).

Each variant is a separate `.npz` under `data/`, which stays gitignored, and each gets its own
run record. The variant recipe (seed, transform, parameters) is what should be committed, so
they are reproducible without committing audio.

### What to measure on every track

* Accepted or abstained, which strategy won, and the section count and filter.
* `recovered_fraction`, `shaping_fraction`, `correction_support_score`, and the note that the
  ceiling bound.
* Plateau region and level, deficit anchor, noise floor and judged band, so T4-T7 can be read
  straight from the records.
* The held-out verdict (once E1 exists) and the false-accept and true-positive tallies by shape.

### Definition of enough

A change to decision logic is not trusted until it has run on at least the positive control, one
sparse track, one natural-droop variant and one paired-release track, and its effect on each is
recorded in the relevant completed/research document under `plans/`. A change that only speeds a run up needs `compare_records.py` to show the
records are identical apart from the fingerprint and timings.
