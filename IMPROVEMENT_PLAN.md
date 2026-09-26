# Improvement plan

A review of the design process (`beqforge/pipeline.py` and the stages it calls) for weaknesses,
inconsistencies and redundancies, with a testable check for each and the shape of the
test material needed to run them. It absorbs the improvement-shaped items previously in
[TODO.md](TODO.md) so each is tracked once; `TODO.md` now points here for them.

**Status of the evidence.** Each item is marked *verified* (visible in the code as read) or
*hypothesis* (plausible from the code, needs its check to run before anyone acts on it). Nothing
here has been run against real material yet — the point of "Stress tracks" below is to make that
possible.

**Ground rules** (from [AGENTS.md](AGENTS.md), restated because this plan is where they are most
likely to be tested):

* Exact-preserving changes and accuracy-for-time trades never share a commit. Validate the first
  with `tools/experiments/compare_records.py`, the second with `compare_verdicts.py`.
* Never calibrate against the catalogue. Acceptance tolerances are calibrated against
  *constructed negatives and known injections* (E2, A1), not against authored filters.
* Every per-title decision comes from that title's own data. A fixed constant that decides a
  per-title outcome is a finding here (T4, T6).
* An item is done when its check has run on the track set below, the outcome is written down
  here, and either the change is merged or the decision not to is recorded.

## Findings and checks

Effort: S = a day or less, M = a few days. "TODO n" is the item's former number in `TODO.md`.

### Evidence and decision quality

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **E1** | **Acceptance mostly re-checks the fit against the target it was handed** *(verified)*. `flatten`'s target is the mix's deficit against its own plateau and `verify` measures that same mix, so the tilt, level, extent and wobble clauses (judged against intent) largely test fit quality. Only overshoot, cliff, turnover, section contribution and stability ask whether the filter is *wrong*. | Held-out verification: derive the target from one half of the programme (split by scene, not by time) and judge on the other. Pass: false accepts on the negative corpus (E2) fall without losing any true positive, and a target that overfits one half fails on the other. | M |
| **E2** | **The false-accept rate is measured on four development negatives** *(verified)*. One of four is falsely accepted; four held-out show none; there is no interval on either. Absorbs TODO 10 and the parametric-path note on calibrating scene segmentation against a false-positive rate. | Build a negative corpus of 50 or more constructed cases across the track shapes below; report the false-accept rate with a Clopper-Pearson interval, per shape. Gate a scheduled test on the interval's *upper* bound. Real tracks supply content, the harness supplies ground truth (see "Variants"). | M |
| **E3** | **Selection rewards ambition** *(verified)*. `Report.accepted` ranks by departure from the requested (flat) shape, so the least-clipped, most-boosting candidate wins even when its support is weakest. Absorbs TODO 6, which asks for a written decision either way. | Re-rank passing candidates by support (`correction_support_score` or `recovered_fraction`) before shape. Pass: on the negative corpus, the selected candidate's recovered fraction does not exceed what the injected truth licenses; on real tracks compare with `compare_verdicts.py` and review every changed decision by eye. Either outcome is written down here. | S |
| **E4** | **The evidence ceiling is unsmoothed and punches holes** *(verified that it is per bin; effect is hypothesis)*. It is peak-minus-quiet contrast minus `z` standard errors per bin, applied with `np.clip`, so isolated unsupported bins become zero inside a supported region and reach the fitter as structure. | Smooth the ceiling with a running minimum over about a third of an octave. Pass: fit residual, wobble and section count improve or hold on every track; no accepted filter gains boost the raw ceiling did not license. | S |
| **E5** | **Two mechanisms for one job** *(verified that both exist; redundancy is hypothesis)*. `flatten` holds its boost flat below the tracking floor *and* prices by contrast. If the ceiling already zeroes those bins the hold is dead code; if it does not, the ceiling is not doing what it claims. | Ablate the hold. Pass: verdicts unchanged means delete it; verdicts changed means find which bins the ceiling let through and why. | S |
| **E6** | **The ceiling measures dynamic range, not missing content** *(verified, acknowledged in AGENTS.md)*. A naturally drooping mix with strong scene-to-scene contrast is licensed up to its plateau. | Not fixable from programme audio alone (see AGENTS.md's "preference shaping"). The check is to *quantify* it: false-accept rate on natural-droop variants (E2) reported separately, and surfaced in the report so a reader can see when a title looks like that shape. | M |

### Target construction and judging: consistency

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **T1** | **`counterfactual` ignores the playback model** *(verified)*. It re-sums with the module constants `MAIN_GAIN` and `LFE_GAIN`; verification and headroom use `params.playback`, which the CLI can change. | Unit test: changing `--lfe-gain-db` or `--main-gain-db` must change the counterfactual target. Identical at defaults, so exact-preserving. | S |
| **T2** | **`restore_caps_db` is a swept constant** (25/35/45/50 dB). Absorbs TODO 1: derive it from each filtered channel's own attenuation at its level-independence floor, which `diagnose` already computes and nothing consults. | Compare derived caps with the sweep on every track with a filtered channel. Pass: the derived cap reproduces the selected candidate's verdict, or the difference is explained. | S |
| **T3** | **`knee_slope_db_per_octave` (14.0) is a fixed threshold** for deciding a channel is filtered. Absorbs TODO 2: replace it with per-channel level-independence, which `stratified_response` already measures. | Must catch a real 15.9 dB/octave filter and spare a natural 13.5 dB/octave channel. Construct both in the harness, then check the real tracks with LFE lowpass variation. | S |
| **T4** | **Hidden constants in the plateau** *(hypothesis)*. The plateau is the widest region within 3 dB of the 90th percentile over a fixed 4-200 Hz band, so the reference moves with the band edge, and "widest first" can favour a broad mid-bass shelf over a narrow true low-frequency plateau. | Sensitivity sweep: band upper edge 120/200/300 Hz, tolerance and minimum width. Pass: plateau level moves by under about 1 dB and its region by under a third of an octave. Otherwise a constant is deciding the outcome. | S |
| **T5** | **The deficit anchor may follow ripple** *(hypothesis)*. `_deficit_anchor` needs a third-of-an-octave run with no deficit of 0.5 dB or more; a mix that wobbles by several dB around its plateau may keep resetting the run and push the anchor upward. | Inject 3-6 dB of ripple on a flat plateau with no filter. Pass: the anchor stays at the plateau's lower edge. If not, add hysteresis or widen the run. | S |
| **T6** | **Fixed floor on the judged band** *(verified)*. `judged_band_hz` uses `max(45 Hz, deficit anchor)` as its upper edge, so a correction ending at 15 Hz is judged out to 45 Hz. | Remove or derive from the priced target's extent. Pass: no change to verdicts on tracks whose correction reaches 45 Hz or more; review each changed verdict where it ends well below. | S |
| **T7** | **Noise-floor resolution does not match its use** *(hypothesis)*. The floor is found in octave bands, but the extent clause compares against it with a 1.2x tolerance. Relates to TODO 12 (frame length 1024 vs 4096 samples), which is absorbed here. | Compare estimated against injected floor on harness signals at 1/3-octave and octave resolution; then check whether any real verdict depends on the frame length. Low priority until one does. | S |

### Fitting and publication

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **F1** | Fitter and judge disagree on drift (TODO 3): the optimiser minimises drift at exact coefficients, `assess` measures the 90th percentile across rounding. Jittered evaluations inside the cost were tried and were worse; a smooth pole-radius penalty has not been tried. | Add the penalty; pass: fewer accepted cascades with poles near z = 1 at 96 kHz and no loss of accepted candidates. | M |
| **F2** | `max_q = 6.0` contradicts the documented argument against constraining Q (TODO 4). It is near-binding on real material. | Either relax it or record why it is needed. Check the sections currently at Q 5.2 to 6.0 against their unconstrained fits. | S |
| **F3** | **Nothing feeds an acceptance failure back into the fit** *(hypothesis; the fitter was not read for this)*. The fit escalates sections against a residual target; acceptance is judged afterwards on different metrics. | Read `fit_minimal_biquads_all`'s stop rule. If it stops on residual alone, test whether one more section rescues candidates that fail only on wobble or tilt. Related to the already-rejected larger budget: that test failed because the target was wrong, so run this on targets known to be sound. | S |

### Calibration and clean-up

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **A1** | **Acceptance tolerances were tuned on titles with no negatives** *(verified)*: level 3 dB, tilt 2 dB/octave, spread margin 2 dB, cliff 2 dB/octave, overshoot 3 dB plus slack, extent 1.2x. That is the catalogue-calibration failure in miniature. | After E2 exists, sweep each tolerance and plot false-accept rate against true-positive rate. Move a tolerance only where the curve shows a clear knee; otherwise record it as a stated preference. | M |
| **C1** | **`parametric` costs about a quarter of a run, has never produced the selected filter, and rests on the weakest component** *(verified from AGENTS.md and the cache)*. `plateau_reference` and `mean_spectrum` are also recomputed in `run`, `diagnose`, `flatten_targets`, `counterfactual_targets` and per candidate in `judged_band_hz`. | Make `parametric` opt-in and compute the shared plateau once on `Diagnosis`. Pass: identical verdicts across records, wall time down. **Exact-preserving; own commit.** | S |
| **C2** | Duplicate limitation notes (attached to every proposal; `evidence_notes` computed twice) and legacy aliases (`mv_adjust_db`, `is_filtered`, `confidence`). | Deduplicate notes; keep aliases only where the external contract needs them. Exact-preserving apart from note text. | S |

## Suggested order

0. **Baseline.** Assemble the track set below, run every track through the current code, keep
   the records. Everything else is measured against these. Build the variants (E2) alongside.
1. **Exact-preserving** changes, each its own commit: T1, C1, C2.
2. **Analysis only, no behaviour change:** E5, T4, T5, T7, F3 and E6's report. Each ends in a
   written decision here.
3. **Behaviour changes with a decision to record:** E4, E3, T6, T2, T3, E1.
4. **Calibration:** A1, then F1 and F2.

E2 gates the rest in practice: without a false-accept baseline no decision-changing item can be
shown to help.

## Stress tracks

The tracks need to be real audio because the risk being tested is the tool meeting material it
has not seen (TODO 10: "watch for the right material rather than manufacturing another synthetic
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
| **Bass-light, dialogue-driven drama** | The sparse case the guard exists for; few independent loud events, so wide standard errors. Best if its tracking floor sits *inside* the content band. | E2, E4, T7, TODO 10 |
| **Old or upmixed mix** (mono or stereo origin, no real LFE) | Natural droop that looks like a mastered rolloff; no LFE channel, so `counterfactual` has nothing to do. | E2, E6, T3 |
| **Concert or music film** | Continuous bass with no quiet frames, so the quiet-frame assumption fails and contrast is near zero everywhere. | E4, E5, T5 |
| **Heavily compressed or limited mix** (loudness-war, trailer-style) | A non-LTI process no linear filter inverts (TODO 11). Not a target, a tripwire: the tool should abstain or say so. | E2, E6 |
| **Noise-dominated location recording** (documentary, stationary rumble) | Stationary noise at low frequency; the ceiling must license nothing there. | E2, E4, E5 |
| **Strongly rippled or humped bass** (a 40-80 Hz hump, or a mid-bass shelf above the sub) | Plateau choice and the anchor: a wide hump can win "widest first" and a wobbly plateau can drag the anchor. | T4, T5 |
| **Authored LFE feature** (a narrow hump in the LFE) and **LFE lowpass variation** (different lowpass corners across releases) | The `--exclude` path, and whether a channel is judged filtered. | T3, T2 |
| **Layout variety** (2.0, 5.1, 7.1, and a bed from an object mix) | Downmix weights, the LFE gain assumption, and the `"mixed"` channel-scope case with no policy. | T1, TODO parametric-path note |
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
recorded in this file. A change that only speeds a run up needs `compare_records.py` to show the
records are identical apart from the fingerprint and timings.

## Not in this plan

Kept in `TODO.md` because nothing here would move them: reconciling `fit_error_db` with the
external contract (TODO 5), a fraction dial and house-curve targets (TODO 7), the catalogue
disagreement detector (TODO 8), exposing `H_protect`'s corner (TODO 9), dynamic-processing
detection (TODO 11, beyond the tripwire above), and the parametric/identification open questions.
