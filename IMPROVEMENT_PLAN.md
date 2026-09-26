# Improvement plan

A review of the design process (`beqforge/pipeline.py` and the stages it calls) for weaknesses,
inconsistencies and redundancies, with a testable check for each and the shape of the
test material needed to run them. It absorbs the improvement-shaped items previously in
[TODO.md](TODO.md) so each is tracked once; `TODO.md` now points here for them.

**Status of the evidence.** Each item is marked *verified* (visible in the code as read),
*observed* (seen on real material in the baseline below) or *hypothesis* (plausible from the
code, needs its check to run before anyone acts on it). A first real track set of nine titles
has been run — see "Baseline: 2026-09-26 track set" below. It produced two wrong declines, both
traced to a mechanism, and several new findings (E7, E8, T8, R1).

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
| **E3** | **Selection rewards ambition, and is unstable** *(verified; observed)*. `Report.accepted` ranks by departure from the requested (flat) shape, so the least-clipped, most-boosting candidate wins even when its support is weakest. Absorbs TODO 6, which asks for a written decision either way. **Observed:** on 28 Years Later, HEAD selects `parametric` (+19.5 dB shelf at 23.6 Hz with a −7 dB peak at 38 Hz, recovered fraction 0.99) over a passing `flatten` (+6.1 dB, recovered 0.86), on a spread difference of 0.6 dB (11.6 vs 12.2). The designer server's older build shipped the `flatten` answer for the same title. A 0.6 dB shape margin chose a filter three times as large. `parametric` also passes with a recovered fraction above 1 on Send Help (1.54): it boosts past the measured deficit. | Re-rank passing candidates by support (`correction_support_score` or `recovered_fraction`) before shape, and treat any recovered fraction above 1 as a failure, not a ranking input. Also a stability check: the accepted strategy and peak gain must not move when the ranking margin is under `ranking_tie_db` plus the fit residual. Pass: on the negative corpus, the selected candidate's recovered fraction does not exceed what the injected truth licenses; on real tracks compare with `compare_verdicts.py` and review every changed decision by eye (28 Years Later first). Either outcome is written down here. | S |
| **E4** | **The evidence ceiling is unsmoothed and punches holes** *(verified that it is per bin; effect is hypothesis)*. It is peak-minus-quiet contrast minus `z` standard errors per bin, applied with `np.clip`, so isolated unsupported bins become zero inside a supported region and reach the fitter as structure. | Smooth the ceiling with a running minimum over about a third of an octave. Pass: fit residual, wobble and section count improve or hold on every track; no accepted filter gains boost the raw ceiling did not license. | S |
| **E5** | **Two mechanisms for one job** *(verified that both exist; redundancy is hypothesis)*. `flatten` holds its boost flat below the tracking floor *and* prices by contrast. If the ceiling already zeroes those bins the hold is dead code; if it does not, the ceiling is not doing what it claims. | Ablate the hold. Pass: verdicts unchanged means delete it; verdicts changed means find which bins the ceiling let through and why. | S |
| **E6** | **The ceiling measures dynamic range, not missing content** *(verified, acknowledged in AGENTS.md; observed)*. A naturally drooping mix with strong scene-to-scene contrast is licensed up to its plateau. **Observed:** Send Help (+13.1 dB) and Obsession (+28.2 dB) are accepted with `shaping_fraction` 1.00 and 1.02: all of the correction sits below the level-invariance floor (22.7 and 24.2 Hz), with confidence 0.94 and 0.92. Neither is known to be wrong, but this is exactly the shape E6 describes, and nothing in the response tells a reviewer so. | Not fixable from programme audio alone (see AGENTS.md's "preference shaping"). The check is to *quantify* it: false-accept rate on natural-droop variants (E2) reported separately, and surfaced in the report so a reader can see when a title looks like that shape. A `shaping_fraction` near 1 should reach the designer response as a first-class warning, not a commentary number. | M |
| **E7** | **Extraction's scene and reference bands are fixed constants** *(verified; effect observed)*. `ExtractionParams.scene_band_hz = (10, 60)` picks loud frames, and `reference_band_hz = (60, 120)` picks quiet ones, for every title and every channel. That is the fixed-band mistake the principles forbid, sitting under the boost ceiling. **Observed:** on Dossier 137, whose mains are filtered at 28-42 Hz, the 10-60 Hz scene band is mostly stopband, and only 260 of 13,597 mix frames qualify as loud. | Derive both bands from the subject's own plateau (the scene band ends at, and the reference band is, the plateau). Pass: loud-frame counts rise on Dossier-shaped titles and no accepted boost grows beyond what the old ceiling licensed on the other eight. | S |
| **E8** | **Digital silence yields near-infinite contrast** *(observed)*. Where a channel's quiet frames are exact zeros, the median margin reads about 2,900 dB (the `1e-300` log floor). Seen on 4 of 9 real titles: LFE on Black Bag, Send Help and Bugonia; LFE, Ls and Rs on Dossier 137. Frame counts also go wrong: Dossier's Ls/Rs report 7,866 of 13,597 frames "loud". `boost_allowance` for such a channel is then bounded only by `restore_caps_db` and the mix-level pricing. No verdict is yet known to depend on it. | Treat exact-zero frames as absent, not quiet (exclude them from the quiet percentile, and mark a channel with too few non-silent frames unavailable). Pass: no channel margin above the extraction's dynamic range; verdicts unchanged, or each change explained. | S |

### Target construction and judging: consistency

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **T1** | **`counterfactual` ignores the playback model** *(verified)*. It re-sums with the module constants `MAIN_GAIN` and `LFE_GAIN`; verification and headroom use `params.playback`, which the CLI can change. | Unit test: changing `--lfe-gain-db` or `--main-gain-db` must change the counterfactual target. Identical at defaults, so exact-preserving. | S |
| **T2** | **`restore_caps_db` is a swept constant** (25/35/45/50 dB). Absorbs TODO 1: derive it from each filtered channel's own attenuation at its level-independence floor, which `diagnose` already computes and nothing consults. | Compare derived caps with the sweep on every track with a filtered channel. Pass: the derived cap reproduces the selected candidate's verdict, or the difference is explained. | S |
| **T3** | **`knee_slope_db_per_octave` (14.0) is a fixed threshold** for deciding a channel is filtered. Absorbs TODO 2: replace it with per-channel level-independence, which `stratified_response` already measures. | Must catch a real 15.9 dB/octave filter and spare a natural 13.5 dB/octave channel. Construct both in the harness, then check the real tracks with LFE lowpass variation. | S |
| **T4** | **Hidden constants in the plateau** *(verified; observed — causes a wrong decline)*. The plateau is the widest region within 3 dB of the 90th percentile over a fixed 4-200 Hz band, so the reference moves with the band edge, and "widest first" can favour a broad mid-bass shelf over a narrow true low-frequency plateau. **Observed:** Dossier 137's mix plateau is 143.3-200.0 Hz and runs into the band's upper edge. Everything downstream inherits it (T8): the tracking floor and level-invariance boundary land at 143 Hz, the judged band collapses to 143-156 Hz, and every candidate fails on "0.12 octaves left to judge". `flatten` fits sections at 284 and 303 Hz. Ballad of Wallis Island's plateau is also narrow (28.4-38.5 Hz, 0.44 octaves) and still accepted. | Sensitivity sweep: band upper edge 120/200/300 Hz, tolerance and minimum width. Pass: plateau level moves by under about 1 dB and its region by under a third of an octave. Otherwise a constant is deciding the outcome. Also: a region touching either edge of the analysis band is truncated, not a plateau. Its extent is unknown, so either extend the band until it closes or abstain with that reason. Dossier 137 is the regression case: it must stop failing on judged-band width. | S |
| **T8** | **Tracking is measured against the plateau's envelope, so it inherits any plateau error** *(verified; observed)*. `_temporal_evidence` walks octave bands down from the plateau and stops at the first whose scene envelope correlates below 0.5 with the plateau's. A plateau in the dialogue band makes every bass band look untracked. **Observed on Dossier 137** (mix, correlation per band): against the chosen 143-200 Hz reference, 0.28 at 100-140 Hz and 0.21-0.26 through 35-71 Hz, so the floor stops at 143 Hz. Against 50-100 Hz, 0.94 at 71-100 Hz, 0.70, and 0.54 at 35-50 Hz, failing at 25-35 Hz: a floor near 35 Hz, which is where the mains' 48-51 dB/octave knees are. | Fix T4 first and re-measure. Then decide whether tracking should correlate against the plateau or against the nearest band above (chained), which cannot be poisoned by the plateau's content. Pass: Dossier 137's floor lands within a third of an octave of its mains' knees, and no other title's floor moves by more than that without an explanation. | S |
| **T5** | **The deficit anchor may follow ripple** *(hypothesis)*. `_deficit_anchor` needs a third-of-an-octave run with no deficit of 0.5 dB or more; a mix that wobbles by several dB around its plateau may keep resetting the run and push the anchor upward. | Inject 3-6 dB of ripple on a flat plateau with no filter. Pass: the anchor stays at the plateau's lower edge. If not, add hysteresis or widen the run. | S |
| **T6** | **Fixed floor on the judged band** *(verified)*. `judged_band_hz` uses `max(45 Hz, deficit anchor)` as its upper edge, so a correction ending at 15 Hz is judged out to 45 Hz. | Remove or derive from the priced target's extent. Pass: no change to verdicts on tracks whose correction reaches 45 Hz or more; review each changed verdict where it ends well below. | S |
| **T7** | **Noise-floor resolution does not match its use** *(hypothesis)*. The floor is found in octave bands, but the extent clause compares against it with a 1.2x tolerance. Relates to TODO 12 (frame length 1024 vs 4096 samples), which is absorbed here. | Compare estimated against injected floor on harness signals at 1/3-octave and octave resolution; then check whether any real verdict depends on the frame length. Low priority until one does. | S |

### Fitting and publication

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **F1** | Fitter and judge disagree on drift (TODO 3): the optimiser minimises drift at exact coefficients, `assess` measures the 90th percentile across rounding. Jittered evaluations inside the cost were tried and were worse; a smooth pole-radius penalty has not been tried. | Add the penalty; pass: fewer accepted cascades with poles near z = 1 at 96 kHz and no loss of accepted candidates. | M |
| **F2** | `max_q = 6.0` contradicts the documented argument against constraining Q (TODO 4). It is near-binding on real material. | Either relax it or record why it is needed. Check the sections currently at Q 5.2 to 6.0 against their unconstrained fits. | S |
| **F3** | **The fitter and the judge measure over different bands** *(verified; observed — causes a wrong decline)*. The fit scores and `_prune` measure section contribution over `residual_band_hz` (5-200 Hz, widened to cover placements). `assess` credits a section only for what it does inside the judged band (tracking floor to `max(45 Hz, anchor)`). A section shaping the region below the tracking floor, where `flatten` holds its boost flat, is doing work the fitter asked for, and the judge rejects it for that. `_prune` then refuses to drop it, because dropping it costs more than 1 dB of residual *outside* the judged band. **Observed:** this is the only failure on Black Bag's `flatten` candidate: a −2.2 dB peak at 13.9 Hz and +1.05 dB at 131.8 Hz, judged over 25.1-50.2 Hz. Otherwise it passes (spread 16.0 → 11.8 dB, tilt +0.7 dB/oct, recovered 0.98). The same rule also rejects counterfactual candidates on 28 Years Later (shelf at 5.6 Hz) and Alto Knights (8.4 Hz). The fitter also spends sections above the sub band (131.8 Hz on Black Bag; 284 and 303 Hz on Dossier). | Put fit, prune and contribution on one band. Either contribution is judged over the band the target asks for (`correction_band_hz` of the priced target, which includes the held-flat region), or the fit stops scoring outside the judged band and refits after pruning. Pass: Black Bag's `flatten` is accepted, or fails on a substantive clause; no accepted filter elsewhere gains a section the judged band cannot see. Then test the original question: does one more section rescue candidates that fail only on wobble or tilt, run on targets known to be sound? | S |

### Calibration and clean-up

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **A1** | **Acceptance tolerances were tuned on titles with no negatives** *(verified)*: level 3 dB, tilt 2 dB/octave, spread margin 2 dB, cliff 2 dB/octave, overshoot 3 dB plus slack, extent 1.2x. That is the catalogue-calibration failure in miniature. | After E2 exists, sweep each tolerance and plot false-accept rate against true-positive rate. Move a tolerance only where the curve shows a clear knee; otherwise record it as a stated preference. | M |
| **C1** | **`parametric` costs about a quarter of a run and rests on the weakest component** *(verified from AGENTS.md and the cache)*. The claim that it never produces the selected filter no longer holds: at HEAD it wins 28 Years Later, the largest boost on offer (see E3). Its passing candidates reach recovered fractions of 1.54 (Send Help), and it is rejected for 1.90 and 2.01 on Bugonia and Caught Stealing. Settle E3 before making it opt-in, since the verdicts are no longer identical without it. `plateau_reference` and `mean_spectrum` are also recomputed in `run`, `diagnose`, `flatten_targets`, `counterfactual_targets` and per candidate in `judged_band_hz`. | Make `parametric` opt-in and compute the shared plateau once on `Diagnosis`. Pass: identical verdicts across records, wall time down. **Exact-preserving; own commit.** | S |
| **R1** | **The baseline must be reproducible from a record, and the review queue's output is not** *(observed)*. The designer server that produced the review queue is a PyInstaller build (`dist/beqforge serve-designer`) three days older than HEAD. On 28 Years Later it shipped a different filter from HEAD on input identical to 24-bit rounding (beqdesigner's `mono.wav` against the extracted mix: RMS difference 7e-6). HEAD itself is deterministic (a rerun reproduced every section). The designer response carries only the accepted candidate and no code revision, so a queue entry cannot say which build made it or why the losers lost. | Stamp the response (commentary or metadata) with the record fingerprint's revision and source hash. Have the server write the same `.run.json.gz` record `design_beq.py` does, beside the extraction. Pass: every queue entry can be replayed with `tools/replay.py`, and a stale build is visible without guessing. | S |
| **C2** | Duplicate limitation notes (attached to every proposal; `evidence_notes` computed twice) and legacy aliases (`mv_adjust_db`, `is_filtered`, `confidence`). | Deduplicate notes; keep aliases only where the external contract needs them. Exact-preserving apart from note text. | S |

## Suggested order

0. **Baseline.** Done for nine titles (below). Records are in `data/*.run.json.gz` at 4858a45;
   `tools/render_ledger.py` renders them together. R1 comes first so the next batch through the
   designer server is replayable too. Build the variants (E2) alongside.
1. **Exact-preserving** changes, each its own commit: T1, C2, and R1's stamping. C1 is no
   longer exact-preserving (28 Years Later's selection changes without `parametric`) and moves
   after E3.
2. **The two known wrong declines**, each its own commit, each checked on all nine titles with
   `compare_verdicts.py`:
   * T4 + T8 (plateau at the band edge, tracking inheriting it): Dossier 137.
   * F3 (fit and judge on different bands): Black Bag.

   These are the only items with a real title that is currently wrong, so they come ahead of the
   analysis. The E2 caveat still applies: a fix that makes a decline accept has to be shown not
   to open a false accept, so run the harness negatives (`evidence_validation.json`) before and
   after.
3. **Analysis only, no behaviour change:** E5, E7, E8, T5, T7 and E6's report. Each ends in a
   written decision here.
4. **Behaviour changes with a decision to record:** E3 (28 Years Later is the test case), then
   C1, E4, T6, T2, T3, E1.
5. **Calibration:** A1, then F1 and F2.

E2 gates the rest in practice: without a false-accept baseline no decision-changing item can be
shown to help. The nine titles below contain no known negative, so on their own they can show a
wrong decline but never a wrong acceptance.

## Progress

Each entry: what changed, how it was checked, what moved. "Probe" is
`tools/experiments/probe.py compare` against the previous commit's snapshot on all nine
baseline titles; a full `design_beq.py` run is made only for titles the probe says need one.

* **Tooling.** `pipeline.run` split into `analyse`/`propose`; `probe.py` added; the
  `counterfactual` restoration transform padded to a fast FFT length (Caught Stealing's run
  167 s → 66 s; targets move by under 5e-5 dB; verdicts identical).
* **T1 — done.** `counterfactual` re-sums the restored channels under the playback model's
  gains, rebuilding the mix from the channels when its LFE-to-mains ratio differs from §2's
  (a common gain cancels). Unit test: same ratio gives an identical target; LFE +6 dB moves it.
  Probe at `--tol 0`: nothing moved on any title. `flatten`, `diagnose` and the judged band
  still read §2's stored mix, deliberately — it is the contract's analysis signal, and
  cached analysis does not depend on playback flags.
* **R1 — done.** Every designer response names its build: `beqforge_revision` in the
  accepted candidate's commentary, or a trailing `[beqforge_revision: …]` on a decline
  message. `serve-designer --record-dir DIR` writes each request's run record there, named by
  a digest of the request audio (`designer-<digest>.run.json.gz`), and the response names the
  file. `record.revision()` never raises; a frozen build reads a revision `beqforge.spec` bakes
  in at build time. This fixed a real crash: the deployed PyInstaller build dies with
  `FileNotFoundError: …/tools/design_beq.py` on `beqforge replay` (and on any record write),
  because `_source_digest` read sources a onefile build does not carry. Checked by a scratch
  PyInstaller build through `smoke_test_exe.py`, which now asserts both the baked revision and
  the record. Probe: nothing moved (no decision logic touched).
* **C2 — done.** A run's limitations now live once, on `Report.evidence_notes`: proposals no
  longer copy them, `_judge` no longer appends a candidate's target notes to its verdict notes,
  and `priced_by_evidence` no longer repeats the "correction evidence" note. The designer
  response, which has no run-level field, joins candidate and run notes in the commentary;
  the `.beq` export does the same and de-duplicates legacy records. **Aliases kept**, by
  decision: `mv_adjust_db` and `confidence` feed the designer contract's own fields, the
  record schema and the ledger, and `is_filtered` is not an alias but T3's knee test.
  Probe: nothing moved (note text is outside every decision).
* **T4 — checked; no code change.** Sensitivity sweep of the mix plateau against the band's
  upper edge (120/200/300/450 Hz): stable on five titles, fragile on four. Dossier's plateau
  always runs into the edge (143-200, 129-300, 127-450 Hz; none at 120); Ballad of Wallis
  Island jumps from 28-38 Hz to 141-224 Hz at 300; Black Bag has none past 200; Send Help none
  at 120. At the default 200 Hz, widest-first and lowest-first ordering pick the same plateau on
  all nine, so reordering changes nothing today. The proposed rule — a region touching the top
  edge is truncated, not a plateau — was tried and **rejected**: it changes only Dossier (to "no
  usable plateau") and breaks verification of a correct result, since an exactly flattened curve
  is flat to the top of the band (`test_the_exact_inverse_leaves_the_low_end_flat`).
  **Why Dossier has no good plateau:** its mix never flattens above the rolloff. It rises at
  about 3-4 dB/octave from 80 to 200 Hz (third-octave levels: −74.9 at 80 Hz, −73.2 at 125,
  −69.5 at 160), against a 3 dB/octave flatness limit, so the only region that qualifies is
  the 143-200 Hz tip. Rescuing it is a design decision, not a bug fix: how should a sloping
  passband be referenced? Options: allow a tilted reference (fit the passband's slope and
  measure the deficit against the extrapolated line), reference the mix to its main
  contributors' own plateaus (L 80-198 Hz, R 102-198 Hz here), or keep abstaining but say
  why. **Decided: keep abstaining, and say why** — see "Dossier 137" below.
* **T8 — checked; chained tracking rejected.** Comparing each band's envelope with the band
  directly above it, instead of with the plateau, removes the tracking floor on eight of nine
  titles. Adjacent bands always correlate above 0.5, which is the stopband-leakage failure
  the evidence rules warn about. On Dossier it still fails at 143 Hz, because the band below the
  plateau does not track the dialogue-dominated plateau at all (0.28). Tracking against the
  plateau stays. Dossier's floor is a consequence of its plateau (T4) and moves only if that
  is decided.
* **F3 — done (the band mismatch; the "one more section" question is still open).** A section
  is now credited for what it does across the band the fitter was allowed to place it in
  (`correction_band_hz` of the priced target, the same band `_fit_all` uses), not only across
  the judged band, which starts at the tracking floor. Midrange parking is still caught: that
  band is the placement band, and the existing 341 Hz test still fails. Probe: Black Bag goes
  from abstain to accepting `flatten` (same four sections; low end from −7 to −10 dB to within
  about ±2 dB of flat), and three counterfactual candidates that failed only on this rule now
  pass without changing any winner (28 Years Later, Alto Knights, Black Bag). A full Black Bag
  run agrees. Synthetic evidence protocol, both seeds, before and after: identical selections
  and false acceptances (1 of 4 development negatives, 0 of 4 held-out — as recorded in
  `evidence_validation.json`). `_prune` still measures contribution over the score band, a
  superset of the placement band. It keeps nothing the judge would now refuse, because a
  section placed inside its band does its work there.
* **E8 — done.** All-zero frames are excluded from the scene floor and from both frame
  classes. Digital silence is absent programme, not a quiet scene. Share of exact-silence
  frames on the baseline: LFE 98% (Dossier), 67% (Black Bag), 42% (Send Help), 26% (Bugonia),
  Dossier's surrounds 42%; the mix never above 0.4%, so no title's boost ceiling was ever
  affected. The ~2,900 dB channel margins become 42-71 dB. Probe: no verdict or selection
  moves; targets move on three titles (Black Bag counterfactual 0.06 dB, Dossier flatten 0.36,
  Obsession counterfactual 0.41). Full runs on those three: same accept/decline on every
  title. Black Bag's accepted `flatten` takes a different four-section route to the same curve
  (within 0.6 dB everywhere; peak boost 9.0 against 9.2 dB). Obsession's losing
  counterfactual/35 fails for a different set of reasons. Synthetic protocol, both seeds:
  identical decisions and recovery. A new test reproduces the real 2,937 dB median margin on the
  old code.
* **E6 (report) — done.** The judge's own notes now reach the designer response as
  `verdict_notes`. They were in the run record but never in the response, so the review queue
  showed `shaping_fraction` as a bare number. On the baseline, Send Help's accepted filter now
  says "16.1 dB of the correction is claimed below 22.7 Hz, where the attenuation stops being
  level-invariant" and warns its 7.9 Hz shelf has 1.5 quantisation steps of DC headroom ("one
  rounding moves its low-frequency gain by 4.4 dB"); Obsession's says 28.9 dB below 24.2 Hz.
  No threshold was added: the note is the one `assess` already writes. The quantitative part
  of E6 (false-accept rate on natural-droop variants) waits for E2.
* **E5 — checked; the hold stays.** Ablated `flatten`'s hold below the tracking floor on the
  six titles that have a floor. The evidence ceiling alone would license up to 14.1 dB more
  boost below the floor on 28 Years Later (at 4.9 Hz), 13.1 dB on Ballad of Wallis Island,
  6.2 dB on Alto Knights, 2.1 dB on Bugonia and 0.6 dB on Black Bag; the hold binds on 117 of
  157 sub-floor bins on 28 Years Later. Temporal contrast licenses bins that do not track the
  programme, so the hold is the only thing carrying the tracking evidence into the target.
  Not redundant, and the ceiling is doing what it claims — it was never a tracking test.
* **E7 — checked; fixed bands kept for now.** Deriving extraction's scene band (ending at the
  mix plateau) and reference band (the plateau itself) per title moves loud-frame counts a lot
  (Ballad 104 → 517, Caught Stealing 927 → 1534, Obsession 928 → 1724) but the priced `flatten`
  target barely at all: at most 0.87 dB (Black Bag), zero on six titles. On Dossier it is
  worse (loud frames 260 → 4), because the derived bands inherit the wrong plateau. The fixed
  constants are not deciding an outcome today; revisit once T4's open question is settled.
* **T5 — checked; folded into T4.** Injected ripple on a flat, unfiltered spectrum. At 3 dB
  peak-to-peak the anchor stays at the plateau's lower edge (4-8.5 Hz). At 6 dB and more the
  plateau either vanishes (abstain) or, with octave-period ripple, latches onto one crest
  (127-185 Hz) and the anchor follows it to 68 Hz, so `flatten` would lift ripple valleys by
  up to 4.9 dB on unfiltered material. The anchor logic is sound; what moves is the plateau
  choice, which is T4's crest-picking. No hysteresis added.
* **T7 — checked; stays low priority.** The only extent failure among 28 baseline candidates
  (Obsession `counterfactual/35dB`, "corrected only down to 24.9 Hz") is on a title with no
  tracking floor, so no verdict depends on the floor's resolution or the frame length.
* **Designer diagnosis — done.** Every accepted response now leads with `found`,
  `correction` and `alternatives` (`beqforge/explain.py`). A decline carries `found` after its
  reason, and a blocked run's decline message is its blockers rather than every caveat. Probe
  at `--tol 0`: nothing moved.
* **Dossier 137 — decided: abstain, for the real reason.** Its low end is a dialogue-led mix
  with no authored bass. The centre carries 74% of the plateau, and the LFE contributes
  nothing and is digital silence 98% of the time. Its only flat region, 143-200 Hz, lies
  entirely above the 80 Hz sub-feed low-pass. New blocker: a mix plateau that starts at or
  above the sub band's upper edge (the lower of the crossover and the bus low-pass, taken from
  the declared playback model rather than a calibrated constant) leaves nothing in the band
  a BEQ acts on to restore towards. Dossier now declines `no_usable_plateau` with that
  sentence and the channel composition, instead of "only 0.12 octaves left to judge". Probe:
  only Dossier moves (the other eight plateaus start at 18-50 Hz). This settles T4's open
  question for Dossier. A sloping passband *inside* the sub band remains unhandled until a
  title needs it.

## Baseline: 2026-09-26 track set

Nine complete programmes from UHD/BD discs, extracted at 1 kHz by beqdesigner's worklist
(`ffmpeg -drc_scale 0 … aresample=1000:resampler=soxr`, 24-bit) and designed through the designer
server. They were then re-extracted from the same `multichannel.wav` with `tools/extract.py` and
re-run at HEAD (4858a45) with default parameters and all three strategies. Filtered/unfiltered
status is **unknown for every title**: nothing here has an independent source, so none of these
is ground truth for E2 or A1.

| Title | Layout, runtime | Server | HEAD | Winner (sections, peak gain) | Recovered / shaping | Mix plateau | Tracking floor → judged band |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 28 Years Later | 7.1 (Atmos), 115 min | accept | accept | `parametric` 2, +18.7 dB (server: `flatten` 4, +7.7) | 0.99 / 0.77 | 28.7-81.2 | 20.5 → 20.5-45 |
| Alto Knights | 7.1 (Atmos), 122 min | accept | accept | `flatten` 3, +20.2 dB | 0.90 / 0.84 | 25.5-53.8 | 12.8 → 12.8-45 |
| Ballad of Wallis Island | 5.1, 100 min | accept | accept | `flatten` 3, +8.6 dB | 0.93 / 0.43 | 28.4-38.5 (0.44 oct) | 20.1 → 20.1-59.1 |
| **Black Bag** | 5.1, 94 min | **decline** | **decline** | — (`flatten` fails on F3 only) | 0.98 / 0.63 | 50.2-82.8 | 25.1 → 25.1-50.2 |
| Bugonia | 7.1 (Atmos), 119 min | accept | accept | `flatten` 1, +5.4 dB | 0.59 / 0.61 | 18.1-39.7 | 6.4 → 6.4-45 |
| Caught Stealing | 7.1 (Atmos), 107 min | accept | accept | `flatten` 2, +12.2 dB | 1.00 / 0.61 | 24.5-49.7 | none → 5-45 |
| **Dossier 137** | 5.1, 116 min | **decline** | **decline** | — (all fail on judged-band width) | — | **143.3-200.0** | **143.3 → 143.3-155.6** |
| Obsession | 7.1 (Atmos), 109 min | accept | accept | `flatten` 3, +28.2 dB | 0.92 / 1.02 | 24.3-40.1 | none → 5-45 |
| Send Help | 7.1 (Atmos), 113 min | accept | accept | `flatten` 2, +13.1 dB | 0.93 / 1.00 | 24.1-41.7 | none → 5-45 |

**Dossier 137 should not have been declined.** Every main channel is steeply rolled off (L 48.5
dB/oct at 41.7 Hz, R 51.2 at 28.1 Hz, C 33.2 at 39.3 Hz); the mean spectrum falls about 40 dB
between 100 and 30 Hz; LFE is almost silent (219 loud frames of 13,597, 0% of the mix plateau).
The decline is not an evidence decision. It is T4 feeding T8: a plateau at the band edge sets
a tracking reference in the dialogue band, and the judged band collapses. Expected after the fix:
a judged band reaching down to about 35 Hz, and a correction the evidence may or may not license
there. Either outcome is legitimate; the current one is not.

**Black Bag is a probable wrong decline.** Its `flatten` candidate passes every substantive
clause and fails only F3's band mismatch. Whether a pruned or refitted cascade is acceptable is
F3's check; the mix's level-invariance boundary sits at 50 Hz with 5.6 dB of the correction
below it, so the answer may still be a small or partial correction.

**Shape coverage.** Positive-control candidates (bass-rich, full LFE): 28 Years Later, Send
Help, Obsession, Caught Stealing, Bugonia. Sparse, dialogue-led: Black Bag, Dossier 137, Alto
Knights. Nearest to a music film: Ballad of Wallis Island (not continuous bass). Layout: 5.1 and
7.1 beds only. **Still missing:** paired releases, an old or upmixed mix, a concert film,
a heavily compressed mix, a noise-dominated documentary, 2.0, and long/short pairs — so the
"Definition of enough" below cannot yet be met (no natural-droop variant, no paired release).

**Reproducing it.** `tools/extract.py "<title> - audio 1/multichannel.wav" --out data --name
<Title>` accepts the worklist's WAV directly (layout survives in the WAV header), then
`tools/design_beq.py data/<Title>.npz`. About 100-175 s a title at HEAD.

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
