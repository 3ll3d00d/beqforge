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

## Status

The one place to see what is done and what is open. **Update it in the same commit as the
Progress entry** it summarises; the detail stays in "Progress" below. *Done*: changed and
merged. *Checked*: the check ran and the decision was no change. *Open*: not started.
*Parked*: not started, and waiting on the condition given.

| ID | Status | Outcome, in one line (detail under "Progress") |
| --- | --- | --- |
| E1 | **open** | Not started. Priority 11 (insurance). |
| E2 | done | Corpus built (`negative_corpus.json`). Gated false acceptances 7/45 → 4/45 (low-end cap) → 0/45 (texture blocker); the gate passes. |
| E3 | done | Hold and deficit cap applied to every strategy; the ranking is unchanged. |
| E4 | parked | Not started; hypothesis with nothing pointing to it. Unparks if priority 4 or 6, or E9's audit, finds single-bin gaps. |
| E5 | checked | Hold stays: it is the only thing carrying tracking into the target. |
| E6 | done | Report half: judge's notes reach the response. Rate half: the corpus's `natural_droop`, reported not gated under the content principle. |
| E7 | checked | Fixed extraction bands kept; the targets barely move. Revisit if the plateau rule changes. |
| E8 | done | Digital silence excluded from both frame classes. |
| E9 | done | Every candidate records its boost past the evidence ceiling. Real titles: none over 0.5 dB. Steep variants: accepted up to 4.0 dB over half an octave. No gate. |
| E10 | parked | Not started. A fresh protocol for the content goal; unparks before a default change (priority 3) or A1-style tuning. |
| T1 | done | `counterfactual` re-sums under the playback model. |
| T2 | parked | Not started. Joins priority 4 if a cap size explains the weaker winners. |
| T3 | done | Channels restored on their own texture, not a 14 dB/oct slope. |
| T4 | checked | No plateau change. Dossier 137 decided: abstain via the sub-band blocker, which since 2026-09-28 fires only when nothing in the sub band tracks. |
| T5 | checked | Folded into T4. |
| T6 | done | Judged band ends at the deficit anchor, not a fixed 45 Hz. |
| T7 | checked | Low priority; no verdict depends on it. |
| T8 | **open** | Chained tracking rejected. The floor is a noisy threshold decision: on Black Bag's own scenes it lands at 25.1 Hz only 55% of the time, and injection moves it within that spread. No leakage bias. Next: a floor rule that accounts for the uncertainty (priority 7). |
| F1 | done | The drift screen charges a fragile cascade its drift instead of vetoing it; Hulk BW8 @ 30, −80 dB unblocked. The smooth penalty cannot help there (the target is fragile at any accuracy). |
| F2 | **open** | Not started. Priority 10: needs a device-behaviour harness first. |
| F3 | done | Band mismatch fixed; Black Bag accepted. The "one more section" question is parked (a time trade-off). |
| F4 | checked | Not adopted: both versions tried lose selections (a wrong decline on Bugonia; a corpus true positive). The fit's exposure is not what acceptance judges. Judging alternatives is parked. |
| A1 | done | No tolerance moves. |
| C1 | checked | `parametric` stays on by default; shared computation done. |
| C2 | done | Limitations reported once. |
| C3 | done | The parametric stage cache is keyed on everything its derivation reads; defaults unchanged. |
| C4 | done | Rescoped by C5 to headroom's peak, 82% of judging: blocks that provably cannot hold the peak are skipped. Bit-identical; 3.5x faster on real programme. |
| C5 | done | Records carry elapsed time, what no stage covers, judging's breakdown and the fit statistics; reports keep their own copy of the fit cost. |
| C6 | done | AGENTS.md corrected on identification's role, `parametric`'s own fit and the stage shares. |
| R1 | done | Responses name their build; the server writes replayable records. |
| R2 | split | Split into R2a and R2b, agreed with beqdesigner's `design/designer-by-reference.md` (`63976c2`); answers to its §6 in Progress. |
| R2a | done | `serve-designer --cache-dir DIR`: a repeat request skips the analysis (Alto Knights 110 s cold, 50 s warm); the frozen build keys the cache on baked digests (the packaged `beqforge design` had crashed on its default cache); smoke test proves a warm hit in the executable. Follow-up: a write held off by a reader on Windows retries, then skips rather than raising. |
| R2b | done | `serve-designer --shared-root DIR`: arrays by reference (contract 1.2) — decoded, checked, 422 naming the array when unusable; `/health` advertises it. On a 2.7 h title the wire goes from 7.8 s to 1.7 s a request. beqdesigner's caller side (their D1.1-D1.4) is theirs to build. |

**Done outside the IDs above:** designer diagnosis (`found`/`correction`/`alternatives`);
the response explains content, not cause; clipping stated in the response; shaping fraction
and level-invariance floor fixed; goal tilt and goal tolerance dials; texture blocker; the
sub-band blocker and its content condition; overshoot past the goal (checked, no change);
noise-floored injection (`inject_variants.py --noise-db`) and its ground-truth scoring
(`score_injected.py`); the steep-filter opt-in `--content-edge` (default off); the probe
now judges exactly as `run` does (`snapshot --content-edge` for the opt-in); designer contract
1.1 — every design the judge failed goes back in `rejected` with its reasons, review only,
beside the answer or the decline (probe unchanged; no decision touched).

### Priority order

What to do next, most valuable first. Each entry says why it sits where it does. Reorder here,
not in "Suggested order" below, which is the historical order the plan was worked in.
Reordered 2026-09-29 when the core-pipeline review was folded in (see Progress): two cheap
correctness fixes go first, and the `--content-edge` decision, which waits on evidence from
outside the harness, moves behind them.

1. **C3: key the parametric stage cache on everything it reads (S), with C6's doc fixes.** A
   correctness bug with no cost to fix: a CLI rerun that changes a goal dial can silently reuse
   a stale `parametric` proposal. It comes first because every experiment with `--goal-tilt` or
   `--goal-tolerance` until it is fixed is suspect. C6 is docs only, but AGENTS.md is what the
   next change is planned from, so correct it in the same sitting (its own commit).
2. *(F4, checked — not adopted; see Progress.)* Neither way of letting the fitter choose among
   more of its own fits helped: its accuracy-plus-drift measure is not what acceptance judges.
3. **Decide `--content-edge`'s default (steep filters).** The only open *policy* question, and
   the synthetic evidence is exhausted: it recovers 17 of 18 noise-floored steep injections
   against 2, touches no real title, but lifts noise where loud scenes stand clear of a floor
   that dominates on average (up to 17 dB on injected Hulk). What decides it is evidence the
   harness cannot give, which is why it sits below two fixes that can be done now:
   * listen to it: the option's output on a noise-floored variant with a large lift (Hulk
     BW16 @ 30, −80 dB: +16.8 dB where noise dominates) against the default's decline;
   * real steep titles: the catalogue's large, steep corrections that several authors agree
     on (Master and Commander, Kingdom of Heaven DC, Hunger Games: Songbirds & Snakes,
     Nobody, Wreck-It Ralph, Battleship; also Mad Max 2, Midnight Run). None is on hand yet;
   * a floor other than white: codec-like or coloured noise in `inject_variants.py`;
   * the corrected noise level, now measured (see Progress): with the option on, the noise
     floor on the steep injections ends up 28-80 dB below the plateau; the worst lift is Hulk
     at a −40 dB floor, +12 dB to −28 dB re plateau. The +16.8 dB case above leaves it at
     −63 dB. Whether −28 dB of lifted noise in the sub band is acceptable is the listening
     question. Still open on the scoring side: coloured floors, and a truth band declared per
     recipe instead of the fixed 60 Hz top.
  Priority 4 adds to this: on steep injections the shape clauses reject the candidate
  closest to truth, in both modes.

   A change of default is a decision change: E10's protocol should exist before it.
4. *(Checked — ranking retained; see Progress.)* Weak winners on steep variants are an
   acceptance question, not a ranking one: the better candidate, almost always `flatten`, fails
   a shape clause on the steep edge. That joins 3, the steep-filter policy.
5. *(E9, done — see Progress.)* Records now say how far each cascade boosts past the ceiling.
   No gate: the only material exceeding it is steep injections, where 4 and 3 already look.
6. *(F1, done — see Progress.)* Its follow-ups. Done: the screen now jitters the published
   parameters, as `accept` does (see Progress). Checked, no change: the screen measures over
   the whole 3-400 Hz grid while the fit scores from 5 Hz — the screen exists to predict the
   drift the verdict reports, which is also over 3-400 Hz, so they agree; the fit's own band is
   where it searches, a different question. Done: what each robustness quantity means is in
   AGENTS.md ("Publication, playback and verification"); writing it down found that
   `fit_error_db` means two things (TODO 5).
7. **T8: the tracking floor is a noisy threshold decision (steps 1-2 done, see Progress).**
   The floor decides where the target is held flat and where the judged band starts. It is the
   first half-octave band, walking down, whose envelope correlates below 0.5 with the
   plateau's — and on Black Bag that correlation's 90% interval is 0.27-0.59 in the band that
   sets it, so resampling the title's own scenes moves the floor between 35.5, 25.1 and 8.9 Hz.
   Next, a decision change: a floor rule that respects that uncertainty — e.g. stop only where
   the band fails with confidence (the bootstrap's upper bound below the threshold), or take
   the floor as the lowest band of the contiguous run the plateau reaches with confidence —
   judged with the probe and `refit_probe.py` (the floor moves targets and judged bands), and
   the synthetic protocol and corpus, since a lower floor can license more boost.
8. *(C5 and C4, done — see Progress.)* Runs account for their time; headroom's peak is exact
   and 3.5x faster. What is left of judging is small; the fitter is the cost now.
9. *(R2a, done — see Progress; R2b stays parked on its timings.)* **R2a: the designer server uses the stage cache (S/M; split from R2 2026-09-29).** A
   redesign of a title already analysed then skips `diagnose`/`extract`/`identify` and a
   parametric fit whose key did not move. Implementation plan, five commits:
   [plans/R2a-server-stage-cache.md](plans/R2a-server-stage-cache.md). beqforge only, no contract change; beqdesigner
   already caches its own extraction, so this is the whole of the redesign saving. After the
   items above because none of them waits on it. Its warm-request timings decide R2b, so
   time them under `systemd-inhibit` with the transfer and decode reported separately. R2b
   (requests by reference, contract 1.2) is parked behind it: nothing is built for it until
   those timings exist and beqdesigner has agreed the §6 answers (Progress, "R2 split").
10. **A device-behaviour harness, then F1/F2's limits for extreme sections (M/L).** `verify`
   models coefficient quantisation at the declared precision, not the device's arithmetic
   (internal word length, rounding noise in the recursion, limit cycles), and that is where
   high-Q, very-low-frequency sections go wrong. Relaxing `max_q = 6.0` (F2), or trusting a
   steep inverse's sections, needs measurements of a real device playing them. F2 is decided
   here, not before. Blocked on device data; nothing else here waits on it.
11. **E1: held-out verification (M, insurance).** `flatten` derives its target from the mix and
   `verify` judges on the same mix, so tilt, level, extent and unevenness mostly confirm the
   cascade matches its own target. Deriving from one half of the programme (split by scene) and
   judging on the other would catch a target that overfits. Nothing is known to be wrongly
   accepted today (corpus gate 0/45), so this is insurance, not a fix.
12. **Parked**, each with what would unpark it:
   * E10 (a fresh validation protocol): before 3 changes a default, or before any tolerance is
     tuned again. The current corpus has informed every decision since E2.
   * E4 (ceiling holes): only if 4, 6 or E9's audit find unevenness failures or excess that
     trace to single-bin gaps in a priced target. Nothing seen so far points to it.
   * F3's second half (one more section): a time trade-off (fit cost grows as M(M+1)/2 runs),
     and a fifth section moved no verdict when tried. Unpark if 4 or 6 show steep candidates
     failing only because four sections cannot draw the shape (catalogue authors use 9-10).
   * T2 (`restore_caps_db` swept): priority 4 found no cap binding a weak winner; unpark only
     if a cap is shown to.
   * judging fit alternatives (F4's follow-up): carry the best few publishable fits per target
     through `_judge` and select on the verdict, not the residual. Several `_judge` calls per
     target (about 7 s each), so a time cost. Unpark if 4 finds a winner lost because its
     target's only fitted cascade failed a clause another fit would have passed.
   * rescoring corpus negatives against the goal (the gate is stricter than the dials);
   * a sloping passband inside the sub band (leave until a title needs it);
   * watch: Black Bag (1.08×) and Bugonia (1.09×) clear the texture blocker by under 10%;
     T8's table puts Incredible Hulk at 1.01× (deficit 8.6 dB, ripple 8.6 dB);
   * Obsession's narrow band of level-dependent content ending the level-independence run,
     which no longer reaches the response;
   * external, in beqdesigner: thread the batch's bass management through `_design`, so
     `gain_reduction_db` arrives on the listener's own crossover.

## Findings and checks

Effort: S = a day or less, M = a few days. "TODO n" is the item's former number in `TODO.md`.

### Evidence and decision quality

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **E1** | **Acceptance mostly re-checks the fit against the target it was handed** *(verified)*. `flatten`'s target is the mix's deficit against its own plateau and `verify` measures that same mix, so the tilt, level, extent and wobble clauses (judged against intent) largely test fit quality. Only overshoot, cliff, turnover, section contribution and stability ask whether the filter is *wrong*. | Held-out verification: derive the target from one half of the programme (split by scene, not by time) and judge on the other. Partition by separated scene blocks, guarding filter and window edges so no event's frames cross folds; derive everything (evidence, reference, target, filter) on one side and evaluate the fixed correction on the other, then swap. Use internal helpers over explicit block selections rather than passing concatenated excerpts through `run` as complete programmes. Scene-specific bass is content: do not require every scene to be flat. Pass: false accepts on the negative corpus (E2) fall without losing any true positive, and a target that overfits one half fails on the other. Report it first; making it a gate is a separate decision. | M |
| **E2** | **The false-accept rate is measured on four development negatives** *(verified)*. One of four is falsely accepted; four held-out show none; there is no interval on either. Absorbs TODO 10 and the parametric-path note on calibrating scene segmentation against a false-positive rate. | Build a negative corpus of 50 or more constructed cases across the track shapes below; report the false-accept rate with a Clopper-Pearson interval, per shape. Gate a scheduled test on the interval's *upper* bound. Real tracks supply content, the harness supplies ground truth (see "Variants"). | M |
| **E3** | **Selection rewards ambition, and is unstable** *(verified; observed)*. `Report.accepted` ranks by departure from the requested (flat) shape, so the least-clipped, most-boosting candidate wins even when its support is weakest. Absorbs TODO 6, which asks for a written decision either way. **Observed:** on 28 Years Later, HEAD selects `parametric` (+19.5 dB shelf at 23.6 Hz with a −7 dB peak at 38 Hz, recovered fraction 0.99) over a passing `flatten` (+6.1 dB, recovered 0.86), on a spread difference of 0.6 dB (11.6 vs 12.2). The designer server's older build shipped the `flatten` answer for the same title. A 0.6 dB shape margin chose a filter three times as large. `parametric` also passes with a recovered fraction above 1 on Send Help (1.54): it boosts past the measured deficit. | Re-rank passing candidates by support (`correction_support_score` or `recovered_fraction`) before shape, and treat any recovered fraction above 1 as a failure, not a ranking input. Also a stability check: the accepted strategy and peak gain must not move when the ranking margin is under `ranking_tie_db` plus the fit residual. Pass: on the negative corpus, the selected candidate's recovered fraction does not exceed what the injected truth licenses; on real tracks compare with `compare_verdicts.py` and review every changed decision by eye (28 Years Later first). Either outcome is written down here. | S |
| **E4** | **The evidence ceiling is unsmoothed and punches holes** *(verified that it is per bin; effect is hypothesis)*. It is peak-minus-quiet contrast minus `z` standard errors per bin, applied with `np.clip`, so isolated unsupported bins become zero inside a supported region and reach the fitter as structure. | Smooth the ceiling with a running minimum over about a third of an octave. Pass: fit residual, wobble and section count improve or hold on every track; no accepted filter gains boost the raw ceiling did not license. | S |
| **E5** | **Two mechanisms for one job** *(verified that both exist; redundancy is hypothesis)*. `flatten` holds its boost flat below the tracking floor *and* prices by contrast. If the ceiling already zeroes those bins the hold is dead code; if it does not, the ceiling is not doing what it claims. | Ablate the hold. Pass: verdicts unchanged means delete it; verdicts changed means find which bins the ceiling let through and why. | S |
| **E6** | **The ceiling measures dynamic range, not missing content** *(verified, acknowledged in AGENTS.md; observed)*. A naturally drooping mix with strong scene-to-scene contrast is licensed up to its plateau. **Observed:** Send Help (+13.1 dB) and Obsession (+28.2 dB) are accepted with `shaping_fraction` 1.00 and 1.02: all of the correction sits below the level-invariance floor (22.7 and 24.2 Hz), with confidence 0.94 and 0.92. Neither is known to be wrong, but this is exactly the shape E6 describes, and nothing in the response tells a reviewer so. | Not fixable from programme audio alone (see AGENTS.md's "preference shaping"). The check is to *quantify* it: false-accept rate on natural-droop variants (E2) reported separately, and surfaced in the report so a reader can see when a title looks like that shape. A `shaping_fraction` near 1 should reach the designer response as a first-class warning, not a commentary number. | M |
| **E7** | **Extraction's scene and reference bands are fixed constants** *(verified; effect observed)*. `ExtractionParams.scene_band_hz = (10, 60)` picks loud frames, and `reference_band_hz = (60, 120)` picks quiet ones, for every title and every channel. That is the fixed-band mistake the principles forbid, sitting under the boost ceiling. **Observed:** on Dossier 137, whose mains are filtered at 28-42 Hz, the 10-60 Hz scene band is mostly stopband, and only 260 of 13,597 mix frames qualify as loud. | Derive both bands from the subject's own plateau (the scene band ends at, and the reference band is, the plateau). Pass: loud-frame counts rise on Dossier-shaped titles and no accepted boost grows beyond what the old ceiling licensed on the other eight. | S |
| **E8** | **Digital silence yields near-infinite contrast** *(observed)*. Where a channel's quiet frames are exact zeros, the median margin reads about 2,900 dB (the `1e-300` log floor). Seen on 4 of 9 real titles: LFE on Black Bag, Send Help and Bugonia; LFE, Ls and Rs on Dossier 137. Frame counts also go wrong: Dossier's Ls/Rs report 7,866 of 13,597 frames "loud". `boost_allowance` for such a channel is then bounded only by `restore_caps_db` and the mix-level pricing. No verdict is yet known to depend on it. | Treat exact-zero frames as absent, not quiet (exclude them from the quiet percentile, and mark a channel with too few non-silent frames unavailable). Pass: no channel margin above the extraction's dynamic range; verdicts unchanged, or each change explained. | S |
| **E9** | **Nothing measures boost the published cascade delivers beyond the evidence ceiling** *(verified that it is unmeasured; size unknown)*. `priced_by_evidence` caps the *target*; the fit only approximates it, and the ceiling is enforced on the cascade itself only below the judged band, and only with `--content-edge`. A cascade can exceed the licensed boost between grid points, across a hole in the ceiling (E4) or inside an exclusion, and no record says so. | Record-only first: on the exact published, quantised device response, record the largest excess over the ceiling, its frequency, its contiguous width in octaves, the integrated positive excess, and excess inside exclusions separately. Bins below the analysis range are unmeasured, not zero allowance. Audit the nine titles, the injected variants and the corpus. Any gate or fit constraint is a separate decision change with its own corpus numbers; a biquad cannot always realise zero at an isolated bin inside positive gain, so a gate needs an explicit realisation allowance, not the level tolerance borrowed. Pass: the record carries it and the audit is written down here. | S |
| **E10** | **The frozen protocol and the corpus answer an older question, and have been tuned against** *(verified)*. `evidence_validation.json` labels negatives by provenance; the goal is now content (see AGENTS.md on `natural_bass_light`). The corpus (gated 0/45, upper bound 7.9%; 0/9 per shape, upper bound 33.6%) has informed every decision since E2, so its intervals no longer describe held-out performance, and 0/9 is weak evidence per shape. | Version a new protocol without editing the old one. Predeclare, before running the held-out half: case families (coloured, nonstationary and correlated noise; finite stopbands; limited programme; sparse and continuous bass; channel cancellation; filters on some channels only), seed and source-title partitions (variants of one title are not independent), goal settings, failure classes (unnecessary intervention, unsupported noise lift, missed recovery, device failure) and sample sizes from the interval wanted. Keep the legacy counts beside the new ones. Once held-out results inform tuning, they become development and a new holdout is reserved. | M |

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
| **F4** | **The fitter discards alternatives before it knows which can be published** *(verified; real-title impact unmeasured)*. Within each section count `_escalate` (`filters.py`) keeps only the structure/seed result with the lowest raw objective (`best = min(window, ...)`), and only then prunes it, measures its published drift and screens it. A slightly worse fit that prunes cleanly or drifts less is already gone, and F1's fallback cannot bring it back. A mocked escalation reproduces it (robust one-section fit at 2.0, rejected two-section at 0.1, usable two-section at 0.2: the one-section fit is returned); how often it happens on real material is unknown. | Prune, publish and screen every structure/seed result in a tier, then choose the tier's representative by F1's rule; break ties deterministically, never by worker completion order. Change nothing else in the same commit (optimiser, drift policy, section budget). Pass: unit tests for an unstable best with a stable alternative, a fragile best with a robust alternative, and all-invalid; serial and parallel agree; **real refits** on the nine titles and the steep variants (the probe rejudges recorded filters, so it cannot see this), every changed winner's corrected curve reviewed, extra screening cost reported. Decision-changing: synthetic protocol and corpus too. | S |

### Calibration and clean-up

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **A1** | **Acceptance tolerances were tuned on titles with no negatives** *(verified)*: level 3 dB, tilt 2 dB/octave, spread margin 2 dB, cliff 2 dB/octave, overshoot 3 dB plus slack, extent 1.2x. That is the catalogue-calibration failure in miniature. | After E2 exists, sweep each tolerance and plot false-accept rate against true-positive rate. Move a tolerance only where the curve shows a clear knee; otherwise record it as a stated preference. | M |
| **C1** | **`parametric` costs about a quarter of a run and rests on the weakest component** *(verified from AGENTS.md and the cache)*. The claim that it never produces the selected filter no longer holds: at HEAD it wins 28 Years Later, the largest boost on offer (see E3). Its passing candidates reach recovered fractions of 1.54 (Send Help), and it is rejected for 1.90 and 2.01 on Bugonia and Caught Stealing. Settle E3 before making it opt-in, since the verdicts are no longer identical without it. `plateau_reference` and `mean_spectrum` are also recomputed in `run`, `diagnose`, `flatten_targets`, `counterfactual_targets` and per candidate in `judged_band_hz`. | Make `parametric` opt-in and compute the shared plateau once on `Diagnosis`. Pass: identical verdicts across records, wall time down. **Exact-preserving; own commit.** | S |
| **R1** | **The baseline must be reproducible from a record, and the review queue's output is not** *(observed)*. The designer server that produced the review queue is a PyInstaller build (`dist/beqforge serve-designer`) three days older than HEAD. On 28 Years Later it shipped a different filter from HEAD on input identical to 24-bit rounding (beqdesigner's `mono.wav` against the extracted mix: RMS difference 7e-6). HEAD itself is deterministic (a rerun reproduced every section). The designer response carries only the accepted candidate and no code revision, so a queue entry cannot say which build made it or why the losers lost. | Stamp the response (commentary or metadata) with the record fingerprint's revision and source hash. Have the server write the same `.run.json.gz` record `design_beq.py` does, beside the extraction. Pass: every queue entry can be replayed with `tools/replay.py`, and a stale build is visible without guessing. | S |
| **R2** | **The designer path cannot share or reuse work** *(verified)*. A request carries every channel inline as base64 float64 (`designer.py`), so the server holds a copy of material beqdesigner already has on disk, and `designer.design` runs `pipeline.run` with no stage cache at all: every redesign of a title repeats `diagnose`/`extract`/`identify` (21-100 s) and the parametric fit even when only a goal dial changed. The pieces for reuse already exist for the CLI — the stage cache is keyed on a SHA-256 of the samples, the effective parameters and a digest of exactly the source files that compute each stage (`cache.ANALYSIS_MODULES`, `PARAMETRIC_MODULES`), so a code change that can move a stage invalidates it and one that cannot does not. Three gaps. (a) No way to name material by path, and the ffmpeg extraction beqdesigner does (and `tools/extract.py` duplicates) has no shared, keyed output either. (b) The cache lives beside the material, one file per title, written non-atomically and without locking — unsafe with two processes on a shared filesystem. (c) `cache.digest_of` reads `.py` sources, which a frozen build does not ship: the executable could not compute a stage key at all (records solve the same problem with a baked `BUILD_REVISION`; the cache would need a baked per-stage digest). | **Split 2026-09-29 into R2a and R2b (rows below); the shared cache is withdrawn (Progress, "R2 split", Q2).** Original check, kept for the record: design first, in agreement with beqdesigner's `designer-interface.md` (theirs to amend): a request form that names a shared location — the extracted `.npz` or the source, plus the layout/provenance fields the inline form carries — alongside the inline form, not replacing it; a cache directory both sides read and write, keyed by content (sample digest), not by path, so a moved or renamed file still hits; atomic writes (write then rename) and entries that are never mutated in place, so concurrent readers are safe without locks; stage keys stamped with per-stage code digests baked at build time for frozen builds, and the extraction step keyed on its own code and ffmpeg parameters so it can be shared too. "Materially changes": a whole-file digest over-invalidates on a comment edit — the safe direction — and a hand-bumped per-stage version would under-invalidate on a forgotten bump, so keep digests. Pass: a second request for the same title with a different goal dial reuses the analysis (timed, `compare_records.py` identical to a cold run); a request by path and one inline produce identical records; two servers or a server and the CLI on one cache never read a partial entry; the frozen executable hits the cache (`smoke_test_exe.py`); a changed analysis module misses. | M |
| **R2a** | **The designer server repeats the analysis on every request** *(verified; split from R2)*. `designer.design` runs `pipeline.run` with no stage cache, and the cache as it stands cannot serve it: it is one file per title beside the material (a request has no path), `cache.store` rewrites that whole file in place (a reader can see a partial one), and `cache.digest_of` reads `.py` sources the frozen build does not ship. | A server flag `--cache-dir DIR` (off by default, like `--record-dir`): entries addressed by `material_fingerprint` and stage, one file per entry, written to a temporary name in the same directory and renamed, never changed in place, so concurrent readers need no lock. Take `material.name` out of `material_fingerprint` — nothing cached carries it — so the same samples get the same key whatever they are called (inline request, request by path, CLI). Bake each stage's module digest into the frozen build beside `BUILD_REVISION` (`beqforge.spec`), and have `digest_of` read it when sources are absent; a frozen build with neither refuses to cache rather than keying on nothing. Pass: a second request for the same title with a different goal dial reuses the analysis and its record is `compare_records.py`-identical to a cold one; a changed analysis module misses; a reader racing a writer never loads a partial entry (test); `smoke_test_exe.py` sends its request twice and the second hits; timings of cold and warm requests with base64 decode and JSON parse reported apart — that split is R2b's evidence. | S/M |
| **R2b** | **Requests by reference** *(design; beqdesigner's D1, `design/designer-by-reference.md`)*. A request may name a WAV under a shared root plus a SHA-256 of the decoded array instead of carrying the array as base64. Saves only the wire: about 690 MB of base64 in one POST for an 8-channel, 2-hour title. | Parked until R2a's warm timings show transfer and decode matter, or the designer runs on another host. Then build to beqdesigner's §3 with the amendments in Progress ("R2 split", Q5): a `--shared-root` server flag, 422 when a `file` cannot be honoured, digest checked before use, the loader keeping `name="designer-request"`. Pass: a request by path and the same request inline give identical keys and records; each §3 refusal answers 422 naming the array. | S |
| **C2** | Duplicate limitation notes (attached to every proposal; `evidence_notes` computed twice) and legacy aliases (`mv_adjust_db`, `is_filtered`, `confidence`). | Deduplicate notes; keep aliases only where the external contract needs them. Exact-preserving apart from note text. | S |
| **C3** | **The parametric stage cache is keyed on too little** *(verified)*. The configuration in its key is `parametric_params`, the fitter's `DesignParams`, but `parametric_targets` also calls `low_end_deficit_db`, `priced_by_evidence` and `_worth_correcting`, which read the goal dials and target rules on `PipelineParams`. The review found goal tilt, goal tolerance, `flatten`'s taper ratio and the verification floor each left the key unchanged. `PARAMETRIC_MODULES` also omits `verify.py`, where `house_curve_db` lives. A CLI rerun that changes one of these reuses a stale proposal. The designer server does not use the stage cache, so its responses are unaffected. | Key on a derivation configuration holding every field the call graph reads, and add `verify.py` to the modules; over-invalidating is the right direction to be wrong in. Pass: for each consumed setting, a warm run after changing it equals a fresh run at that setting (targets, filters, method, verdict), including a tilted goal, a tolerance that suppresses the proposal, exclusions and `--content-edge`; an edit to the fitter still reuses the analysis; probe at `--tol 0` shows nothing on defaults. | S |
| **C4** | **The same device waveform is computed twice per candidate, and the sub feed once per candidate** *(verified)*. `_judge` rebuilds the bass-managed sub feed for every candidate; `verify` and `measure_headroom` each call `device_waveform` on that feed with the same cascade (the second only to keep the ring-out); the unfiltered spectrum and plateau reference are recomputed each time too. Headroom's 16x peak interpolation is real work either way. | Build the sub feed, its spectrum and its reference once per run; apply the device once per stable cascade with its ring-out, Welch the programme slice, peak the whole. Keep the unstable and no-filter paths explicit, and release each waveform after measuring. Identical published cascades may share measurements but are still assessed against their own intent. **Exact-preserving; own commit:** `compare_records.py` identical, headroom included (the probe skips headroom); programme slice equal to `include_tail=False` in a test. | S |
| **C5** | **A run's time and fitting cost are not fully accounted for** *(verified)*. `Timings.total_s` sums the timed stages, so cache I/O, hashing, blockers and reference work are invisible. `FIT_STATS` sums worker wall time, not CPU, and is a process-wide object `Report.fit_stats` aliases: the next run's reset changes an earlier report. The record carries no fit statistics. | Record whole-run elapsed time beside the stage sum with the remainder explicit; split judging into sub feed, device application, spectra, peak and assessment; copy fit statistics into each report and the record (evaluations, worker time, screening time, cache hits, candidate counts). Old records stay readable. Instrumentation only: probe unchanged. Then time cold, warm and repeat runs under `systemd-inhibit` before C4, so C4's saving is measured. | S |
| **C6** | **AGENTS.md no longer matches the code in places** *(verified)*. It calls identification "diagnostic and confidence only, not on the path to a target", but `parametric` builds its target from it; says the fit is "one shared fit", but `parametric` fits inside `design` before `_fit_all`; and gives the fitter "~75% of a run", where the nine baseline records (mixed revisions, analysis cached) put fitting at ~49%, judging ~41% and targets ~10%. | Correct each statement and date the measurements that stay. Docs only; no decision moves. | S |

## Suggested order

The order the plan was worked in, kept for its reasoning. Steps 0-3 are complete; what
remains of steps 4 and 5 (E4, T2, E1, F1, F2) is ranked with everything else under "Priority
order" in "Status" above, which supersedes this list.

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
* **E3 — done, by fixing the evidence rather than the ranking.** The ambition was not in
  selection. It was that only `flatten` got the tracking-floor hold and was bounded by the
  measured deficit. On 28 Years Later, below the 20.5 Hz floor, `parametric` and
  `counterfactual` asked for 16.4 and 15.5 dB where `flatten` asked 6.4. `priced_by_evidence`
  now applies the hold and a cap at the mix's measured deficit (`mix_deficit_db`) to every
  strategy, before the contrast ceiling. `flatten` is untouched: its targets are identical at
  `--tol 0` on every title. Real runs on the eight titles the probe named:
  * 28 Years Later still selects `parametric`, now +6.9 dB against `flatten`'s +6.1 (was
    +18.7).
  * Caught Stealing and Send Help switch to `parametric`. Both are flatter, not bigger: spread
    3.27 against 3.44, and 10.6 against 12.6 dB. Send Help's +17.5 dB fills a bottom octave
    that was 12-15 dB down, with no overshoot on its chart and the same recovered fraction
    (0.93).
  * Every other winner is unchanged. The largest recovered fraction is now 1.00 (was 2.01).
  * The synthetic protocol **loses its one development false acceptance** (`natural_bass_light`,
    won by counterfactual, now abstains): 0 of 4 on both seeds. The held-out positive recovers
    slightly less (13.86 against 13.11 dB RMS from the full inverse).

  Re-ranking by `correction_support_score` was not adopted: it is near-identical across one
  title's candidates (0.91-0.92 on 28 Years Later), so it cannot separate them. A separate
  "recovered fraction above 1 fails" rule is unnecessary once the cap exists.
* **C1 — opt-in rejected; shared computation done.** `parametric` stays on by default. Since
  E3 it wins three of eight accepted titles with results flatter than `flatten`'s, so making it
  opt-in would change those answers for the worse. The recomputation half is done: `analyse`
  finds the mix plateau once (it asked twice), and `run` hands every `_judge` the judged band
  `analyse` already found. Honest size: a mean spectrum is 0.12 s, so this saves under a
  second on a 70-170 s run; it is done for one source of truth, not for speed. Exact: probe
  at `--tol 0` unchanged, Bugonia's full record byte-identical.
* **E2 — done: the corpus exists. It failed its own gate at first; it passes since "Texture is
  not a deficit", below.** `harness.corpus_case` builds
  two-channel titles in seven shapes, every parameter drawn from the seed.
  `tools/negative_corpus.py` runs them one process each and reports per shape, with 95%
  Clopper-Pearson intervals. Baseline, 9 seeds (63 cases), committed as `negative_corpus.json`:

  | Shape | Result | Interval | Size of what was accepted |
  | --- | --- | --- | --- |
  | broadband | 4/9 false acceptances | 0.14-0.79 | +2.0 to +3.2 dB, all `flatten` |
  | varying_source | 3/9 false acceptances | 0.07-0.70 | +1.4, +3.4 and **+18.7 dB**, all `parametric` |
  | sparse_dialogue, rumble, stationary_noise | 0/9 each | 0-0.34 | — |
  | **gated negatives** | **7/45 (16%)** | **0.06-0.29** | gate 0.10: **fails** |
  | natural_droop (reported, not gated) | 4/9 | 0.14-0.79 | +17 to +25 dB, counterfactual/parametric |
  | filtered (positives) | 7/9 true positives | 0.40-0.97 | +21 to +32 dB; median recovery 1.26 dB RMS |

  The frozen protocol (`validate_evidence.py`) is unchanged and still shows 0/4 on both seeds.
  The corpus is harder because its events carry per-event spectral colour and level-dependent
  emphasis, which is closer to real programme. Two findings:
  1. **`flatten` fills ripple on unfiltered material** (+2 to +3 dB, one to three sections).
     The diagnosis says so itself — no channel knee, level-invariant and tracking to the bottom
     of the band — yet nothing in acceptance asks for evidence of a rolloff before correcting.
     Not yet decided: whether "no evidence of a rolloff" should be an abstention reason, and
     how to state it without a constant. Mastering support is unavailable from programme
     alone (AGENTS.md), but a knee, level-invariance and tracking are all measured.
  2. **`varying_source/6`: a +18.7 dB, four-section `parametric` correction on a never-filtered
     source.** A full-size false acceptance — fixed; see "E2 finding 2" below.

  The evidence score does not separate these from true positives (0.91-0.96 on both), which
  confirms it cannot serve as a gate. The recovery gap between `flatten` (1-2 dB RMS) and the
  one `parametric` true positive (15.6 dB RMS) is also worth a look. The gate (upper bound
  0.10) is a stated preference; `--gate` changes it. No scheduled CI job was added: at 15-20
  minutes it belongs in the regression workflow (AGENTS.md step 4) until the pipeline passes
  it.
* **E2 finding 2 — fixed: every strategy is capped at the *low-end* deficit.** The worst corpus
  false acceptance (`varying_source/6`, +18.7 dB parametric at 88 Hz) was a bass-heavy source
  whose plateau sits at 4-12.6 Hz. The raw plateau-relative deficit therefore covered
  everything above, and E3's cap allowed a model inversion to fill it. The cap is now
  `low_end_deficit_db`: the deficit from the bottom up to its first settled end, tapered —
  exactly `flatten`'s unpriced target, so `flatten` is unchanged (probe, `--tol 0`). Results:
  * **Corpus:** gated false acceptances 7/45 → **4/45** (interval 0.06-0.29 → 0.02-0.21).
    varying_source 3/9 → 0/9. Positives unchanged: 7/9, median recovery 1.26 dB RMS.
    natural_droop unchanged at 4/9. The gate (0.10) still fails, on the four broadband ripple
    fills.
  * **Frozen protocol:** identical decisions on both seeds.
  * **Real titles:** targets move only in the tails, by at most 1.6 dB. Full runs on the four
    titles past tolerance: Caught Stealing and Send Help go back to `flatten`. Their
    `parametric` target now equals `flatten`'s wherever the model asked for more, so it fits the
    identical cascade and the tie goes to `flatten`. Send Help's earlier, flatter parametric
    result (spread 10.6 against 12.6 dB) came from boosting in the taper zone above `flatten`'s
    anchor, where the low end is not missing. Bugonia's and Obsession's winners are unchanged.
  * **Consequence worth knowing:** under a shared cap, `parametric` and `counterfactual` can
    only differ from `flatten` by asking for less. Records refreshed for the four titles;
    `negative_corpus.json` is the new corpus baseline.
* **Goal below the knee — a preference dial, now generative (TODO 7's house-curve half).**
  `AcceptParams.target_tilt_db_per_octave` (CLI `--goal-tilt`; 0 flat by default, positive a
  rise toward the bottom, negative a gentle rolloff) used to be acceptance-only: asking for a
  rise discarded flat candidates. Now every strategy's target is measured against the goal
  (`low_end_deficit_db` via `verify.house_curve_db`), pivoting at the top of the judged band —
  the same point acceptance anchors `requested_db` at. `intent_db` no longer adds the house
  curve on top of a target that already carries it, and `recovered_fraction` measures the
  deficit against the goal. Exact at the default (probe `--tol 0` unchanged). Black Bag at
  +2 dB/octave: `flatten` accepted at +11.9 dB against +9.0 flat, low end 2-4 dB above the
  reference over 13-25 Hz, held flat below the 25 Hz tracking floor, 98% recovered. This
  reframes E2: on a flat goal, a 2-4 dB dip *is* a departure from the preference, so filling it
  is the dial working. What counts as worth correcting is the tolerance dial, next.
* **Goal tolerance — a preference dial (1.5 dB), replacing an unstated 1 dB minimum.**
  `AcceptParams.goal_tolerance_db` (CLI `--goal-tolerance`): no strategy proposes a correction
  whose priced target never exceeds it, and a run where none do abstains with a stated
  reason, `within_goal_tolerance`. Probe: one target gone, Ballad of Wallis Island's failing
  `counterfactual/25dB` (1.02 dB); its full run keeps the same winner. Corpus unchanged at
  4/45, positives unchanged. Frozen protocol identical on both seeds. **On E2's remaining
  false acceptances:** at the default flat goal and 1.5 dB tolerance, broadband's 2.4-3.7 dB
  dips depart from the goal by more than the tolerance, so correcting them is the preference
  as set, not an error. A user who wants them left alone sets `--goal-tolerance 4`. The
  corpus's gate treats any intervention on a negative as false, which is stricter than the
  dials now say; whether to rescore negatives against the goal is open.
* **Texture is not a deficit — the corpus gate now passes.** The remaining false acceptances
  were `flatten` filling 2-4 dB wiggles on unfiltered titles: the programme's own texture,
  which it shows just as much above the knee. New blocker: a low end whose deepest shortfall is
  no larger than the passband's crest-to-trough ripple above the correction
  (`passband_ripple_db`) abstains with `within_programme_ripple`. Measured first (low-end
  deficit ÷ that ripple): unfiltered corpus titles at most 0.77×, real titles 1.08-4.33×
  (Dossier 18.9×), injected filters 6.2-20.3×. The boundary is 1× — the title's own yardstick,
  no constant. A one-sided dip was tried first and rejected: the reference sits on the crests,
  so noise reached 1.59×. Results: corpus gated false acceptances 4/45 → **0/45** (interval
  0-0.08; the 0.10 gate **passes**), positives unchanged (7/9, 1.26 dB RMS); frozen protocol
  identical; probe at `--tol 0` unchanged on all nine real titles. **Watch:** Black Bag
  (1.08×) and Bugonia (1.09×) clear the line by under 10%. They are the two most marginal real
  corrections, and a change that tips them to abstain would be the rule working, not a
  regression — but look.
* **A1 — done: no tolerance moves.** `tools/experiments/a1_sweep.py` collects every candidate
  once (the corpus with the texture blocker off, plus the nine real titles from their records;
  95 candidates, about 25 minutes). It then re-assesses them under each tolerance at multiples
  of its default, with selection re-run, in seconds. It reports two views: as shipped, and
  acceptance alone. The default reproduces the baseline exactly (as shipped: 0/45 gated, 4/9
  natural droop, 7/9 positives at 1.26 dB RMS; acceptance alone: 4/45).

  | Tolerance | Effect of moving it | Decision |
  | --- | --- | --- |
  | level 3 dB | ×0.5 loses a positive and changes Bugonia's winner; ×2 or off admits a 5th natural droop | keep; the default sits on the safe side |
  | tilt 2 dB/oct | nothing changes from ×0.5 to off, except droop 4 → 3 at ×0.5 | keep; inert today, a stated preference |
  | spread margin 2 dB | tighter loses a positive; looser changes nothing | keep |
  | cliff 2 dB/oct | ×1.5 or more: positives 7/9 → 9/9, no new false acceptances, no real title changes | **keep** — the two it would admit are 11.9 and 13.9 dB RMS from the true inverse (median 1.2): every candidate on both *steepens* the input's worst cliff (29 → 31-40 dB/oct at 5-10 Hz). The clause is doing its job |
  | section contribution 1 dB | 0-1 identical; 1.5-2 declines Black Bag, loses positives, changes Ballad's winner | keep |
  | minimum judged octaves 1 | 0-1 identical; 1.5 declines 28 Years Later and Black Bag | keep |

  Acceptance alone never takes false acceptances below 4/45 without losing positives. It is the
  texture blocker, not these tolerances, that separates unfiltered material. Not swept: the
  extent clause's 1.2× (hard-coded in `assess`), the overshoot slack (tied to level plus
  roughness), and the goal dials (they shape targets, so a sweep would need refits).
  **New finding (for a later item):** the two injected LR4 filters near 22 Hz fail because
  every strategy's cascade relocates the cliff to 5-10 Hz. Their priced targets likely end in
  a steep edge where the evidence stops licensing boost, and the fitter reproduces it. That is
  a target-shape problem, not a tolerance one.
* **Shaping fraction and the level-invariance floor — fixed (reporting only).** Obsession
  reported a shaping fraction of 1.019 on what is plainly a corrected rolloff. Two faults:
  1. The fraction subtracted the cascade's gain at the floor, so a floor gain of −0.53 dB
     counted boost that does not exist. That gain is now floored at zero, so the fraction
     stays in [0, 1]; the shaping note had the same arithmetic.
  2. The floor itself was set by single-bin estimator noise. The spread between loudness
     strata was taken per 0.24 Hz bin unsmoothed, swinging 2-19 dB between neighbours, and the
     first bin over tolerance ended the run. Each stratum is now smoothed as the deficit is
     before the spread is taken.

  Probe: no verdict or winner moves (the floor feeds only notes and reporting). Floors:
  28 Years Later, Alto Knights and Caught Stealing 22-25 Hz → the bottom of the band (their
  shaping fractions of 0.60-0.85 were noise and are now about 0); Dossier 142.8 → 59.3 Hz;
  small moves elsewhere. **Obsession stays near 24 Hz, and rightly.** Its loudest scenes carry
  extra energy at 20.5-23.5 Hz that quieter scenes do not (a real 8-19 dB spread that survives
  smoothing), and the rule stops at the first break below the plateau, although the strata
  agree again from 20 Hz down to 13 Hz. The response now says what the check measures ("loud
  and quiet scenes agree on the shape of the low end down to X Hz…") instead of claiming the
  loss "stops behaving like a fixed filter". **Open:** whether a narrow band of
  level-dependent *content* just under the plateau should end the run when agreement resumes
  below it.
* **The response explains content, not cause.** Whether to boost at a frequency is a question
  of whether there is real programme there to lift. Tracking answers it (the band moves with
  the higher-frequency programme, so it is not noise) and contrast bounds it. Whether a filter
  removed the bass cannot be told from the audio and decides nothing. The response now says,
  per frequency, what was wanted, what the content supports and the low end before → after,
  and where real bass content ends. The level-independence floor, "shaping" and the channel
  "steep knee" line — filter-identification diagnostics — are out of the response, and the
  shaping note is gone from `assess` (`AcceptParams.shaping_note_db` removed). `shaping_fraction`
  stays in the record, clamped to [0, 1]. Obsession now reads "real bass content all the way
  down … content supports +28.2 dB at 5 Hz, low end −28.8 → −1.6", where it used to call a
  plain corrected rolloff "100% shaping". Probe `--tol 0`: nothing moved. The Obsession
  question above (a narrow band of level-dependent content ending the level-independence
  run) no longer touches anything a reviewer sees.
* **Overshoot past the goal — checked, no change.** Every accepted filter pushes some point
  past both its start and the goal band, by 0.4-5.3 dB: smooth shelves lift the narrow content
  spikes that sit where they act (Bugonia's 8 Hz spike, +7 → +12 dB; Black Bag's 40-50 Hz
  spikes). Those spikes are content, so restoring the low end lifts them too. The existing
  overshoot check (a ceiling at the higher of start and goal, plus 3 dB and half the input's
  roughness) sits 7-11 dB above every curve and trips on none. Swapping its allowance for the
  title's own ripple would move that ceiling up on some titles and down on others and reject
  nothing. Left as it is: it guards against gross errors, and what matters for spikes is
  clipping.
* **Clipping is now stated in the response.** Headroom was measured on every run but surfaced
  only as one line buried in `verdict_notes`, and the typed `gain_reduction_db` field was always
  `None`, because beqdesigner's worklist never sends `bass_management` (`pipeline/library/run.py`
  `_design` omits it). The commentary now carries `clipping`: the sub-feed peak, and how far to
  turn the sub down, saying whether the model is the request's or the assumed LR4 80 Hz. Black
  Bag: "+1.3 dBFS — turn the sub channel down by 1.3 dB"; every other accepted title is under
  full scale (Bugonia peaks at 42%). **Pending, in beqdesigner:** thread the batch's bass
  management through `_design` into `design_if_needed`, so the typed field arrives on the
  listener's own crossover. Waiting for that repo's local work to finish first.
* **The two LR4 positives that abstain — diagnosed; fix tried and reverted.** filtered/4 and
  /5 (LR4 near 22 Hz) fail because the contrast ceiling pins the target near the bottom
  (+33 dB at 8.5 Hz, +16 at 5 Hz). The priced target peaks mid-band and *falls* toward the
  bottom, so the corrected curve drops faster than the input and the cliff check rejects it.
  Every cliff failure in the corpus has a target falling ≥4.8 dB toward the bottom; every
  real-title winner falls ≤2 dB. You chose "content first" — lift each frequency as far as
  its content supports and accept the steep edge where it runs out — over capping the target
  at the bottom's level. Two implementations were tried and **both reverted**:
  1. Exempt the cliff check below a per-candidate "content edge" (where the target is pinned
     at the ceiling). Corpus positives stayed at 7/9 (flatten then fails wobble and extent).
     On the held-out protocol seed, steep_leakage was accepted and natural_bass_light falsely
     accepted.
  2. Start the judged band at a title-level content edge, the contrast counterpart of the
     tracking floor. Corpus positives 7/9 → 8/9 (filtered/5 via parametric), gated false
     acceptances still 0/45, natural droop 4 → 6/9, real titles exactly unchanged. But the
     frozen protocol falsely accepted natural_bass_light on **both** seeds and accepted
     steep_leakage on both — a case that must abstain.

  **Why:** content running out and stopband leakage from a very steep filter look the same
  to this evidence. Both pin the target at the ceiling with a steep fall below, and the cliff
  check judged over the full band is what keeps leakage out. (B) needs a way to tell them
  apart before it is safe. **Also found:** with the edge exempted, flatten still fails on fit
  quality — four sections cannot follow a steep, evidence-limited LR4 inverse (13.5 dB wobble
  against 5.6) — while `parametric` fits it. **Latent bug, since fixed:** the extent check
  used the tracking floor as where content ends, so with a floor below the band's 5 Hz edge
  (4.0-4.2 Hz on three natural-droop cases) no extent could ever pass. It now uses
  `max(floor, band low)`. Real titles unchanged (probe `--tol 0`); corpus natural droop
  4/9 → 5/9, everything else unchanged; frozen protocol identical.
* **T3 — done.** Which channels `counterfactual` restores is now decided by each channel's own
  texture, not a fixed 14 dB/octave steepest slope. A channel is restored when its low-end
  deficit against its own plateau exceeds its own passband's crest-to-trough ripple
  (`channels_missing_low_end`): the texture rule per channel, the same 1× boundary, no
  constant. Measured first on the corpus. The slope decided on noise: it missed filtered/3's
  filtered LFE (13.5 dB/oct) and flagged broadband/4's and /9's unfiltered LFE (22.9, 17.5).
  The texture test separated them completely: filtered channels 4.6-19.1×, unfiltered
  0.15-0.82×. On real titles it drops mostly-silent or texture-level channels (Black Bag's
  LFE at 0.13×, surrounds ≈0.45×; Bugonia's and Caught Stealing's LFE) and adds 28 Years
  Later's centre (8.2×, 13.3 dB/oct). `knee_slope_db_per_octave` stays as a descriptive label
  only. Probe: only counterfactual targets move. Full runs on the four titles concerned: no
  winner changes; losing counterfactual candidates' verdicts shift. Corpus and frozen protocol
  unchanged.
* **T6 — done.** The judged band's fixed 45 Hz floor is replaced by "the deficit anchor, at
  least `min_judge_octaves` above the floor" (`verify_band_hz` → `verify_floor_hz`), so checks
  measure where the correction is (Send Help 5-15.5 Hz; spread 12.6 → 5.7 dB). No real winner
  changes and the corpus is unchanged. On the frozen protocol, natural_bass_light is now
  accepted on both seeds: parametric had only been failing it on unevenness, by 0.1-0.7 dB,
  over the over-wide band. Under the content principle that case is real, attenuated programme
  and correcting it is the goal dial working, so it is reported like `natural_droop` rather
  than counted as a false acceptance. The protocol file is untouched, and noise and broadband
  still abstain (AGENTS.md). Failure messages now say "uneven: X dB of ripple about its trend"
  instead of "wobbles".
* **Item 1 (content edge vs steep leakage) — first real-texture evidence, from injection.**
  An unfiltered original of a real title is almost never available, so ground truth comes
  from differential injection instead: `tools/experiments/inject_variants.py` applies known
  high-passes to every channel of a real title (the mix rebuilt with the extraction's gains).
  The title before injection is the reference, so its own state cancels. The Incredible Hulk
  (5.1, 112 min, fairly full bandwidth; accepted itself with `flatten` +5.6 dB). Each variant
  against the original's own corrected result:

  | Injected | Outcome | Restoration |
  | --- | --- | --- |
  | BW2 @ 25 Hz | counterfactual +31 dB | within ~1 dB from 8 Hz up |
  | LR4 @ 20 | flatten +44 dB | matches from 8 Hz up; −4 dB at 5 Hz where content runs out |
  | LR4 @ 25 | flatten +45 dB | within ~1.5 dB from 8 Hz up; −12 dB at 5 Hz |
  | LR4 @ 30 | flatten +45 dB | within ~2 dB from 10 Hz up |
  | LR4 @ 35 | counterfactual +44.5 dB | within ~2 dB from 13 Hz up; −24 dB at 5 Hz |
  | BW8 @ 30 | declined (flatten: wobble — 4 sections cannot follow an 8th-order inverse) | — |
  | BW12 @ 32 | declined (flatten: tilt) — the leakage regime, abstaining as the protocol requires | — |

  None of the accepted filters clips: sub-feed peaks 0.44-0.86 of full scale, against the
  original's 0.60. A large boost restoring removed content costs little headroom. **Reading:**
  on real programme, "content first" already happens for moderate filters. Every LR4 is
  restored down to where the content supports it, with the steep edge below, and the cliff
  check does not object. The corpus's two LR4 failures look like an artefact of synthetic
  material, whose ceiling falls off near the bottom in a way this real title's does not. What
  remains open is steep filters (8th order and up): lift partway to where content allows, or
  abstain. That is a fitting limit plus a policy call. **Next:** repeat on two or three more
  real titles (a sparse one such as Black Bag, and Send Help) before closing item 1 on one.
* **Injection on two more real titles (Black Bag, Send Help), compared as shapes.** Each
  variant's corrected curve against the original's own corrected curve, each relative to its
  own reference (an injection near the plateau lowers the reference too, which no pipeline
  could detect):
  * **Hulk (full bandwidth):** BW2 and LR4 restored within ~1 dB down to 8-13 Hz.
  * **Send Help (content to the bottom):** within ~3 dB, except a consistent 4-8 dB hole around
    20 Hz on the LR4 variants. Send Help has a +7.9 dB content hump there; once the filter
    flattens it, restoration aims at the goal's shape and cannot know it existed.
  * **Black Bag (sparse; nothing tracks below 25 Hz):** restored within ~1 dB above 25 Hz and
    not below, which is correct by the content rule. LR4 @ 35 and BW8 are accepted but 9-16 dB
    short (partial targets the evidence limited).
  * **Steep (BW8/BW12):** decline, or come out heavily partial, on all three.

  **Finding — the sub-band blocker false-declines a filtered real title.** On Black Bag with
  LR4 @ 30 the injection turns its 50-83 Hz plateau into a slope, so the only flat region left
  lies above 80 Hz and "no reference in the band the sub plays" declines, although content
  still tracks down to 25 Hz. A plateau above the sub band is not always "no bass passband";
  the rule needs a content condition (e.g. only when nothing below the plateau tracks the
  programme); fixed, see below. **Item 1 conclusion so far:** moderate filters are handled
  well wherever there is content, on all three titles, with no rule change; only steep
  filters remain open.
* **Sub-band blocker — fixed: it now needs an absence of content, not just a high plateau.**
  It fires only when the mix plateau starts at or above the sub edge *and* the mix's tracking
  floor (`diagnosis.noise_floor_hz`) is there too, so nothing inside the sub band tracks the
  programme. NaN (every band tracked) counts as content. The two real cases separate
  cleanly: Dossier 137 stops tracking at 143.3 Hz, the bottom of its plateau, and still
  declines, now naming that floor; Black Bag + LR4 @ 30 (plateau 100.7-129.9 Hz) tracks to
  9.2 Hz and is no longer blocked. The synthetic Dossier fixture had to change: noiseless, its
  8th-order stopband tracked the programme to 10.6 Hz (the leakage case the evidence rules
  warn about), so it now carries low-level material unrelated to the programme below 80 Hz,
  as Dossier does; a new test covers a sloped passband above the sub edge that still tracks.
  Probe at `--tol 0`: only Dossier's blocker text moves. Synthetic protocol, both seeds:
  identical before and after. Negative corpus: identical to `negative_corpus.json` (gated
  0/45, gate passes). **Real run, Black Bag + LR4 @ 30:** `flatten` accepted (low shelf
  33.45 Hz +15.9 dB, peak 50.09 Hz +4.9 dB; judged 9.2-54.9 Hz). Against the original's own
  corrected curve, each relative to its own reference: within ~1 dB at 25-50 Hz, 1.9 dB short
  at 20 Hz, 7 dB at 16 Hz and more below, where the priced target licensed no boost. The same
  pattern as the other LR4 variants. **Watch (T8):** the variant's tracking floor, 9.2 Hz
  against a 100-130 Hz reference, is lower than the original's 25 Hz against 50-83 Hz. Tracking
  still inherits the reference.
* **Steep filters — do they exist, what is right, and an opt-in (`--content-edge`).**
  * **The catalogue says they exist.** Every entry in `~/.ezbeq/database.json` rendered from its
    96 kHz biquads (15,345 with filters) and scored by the most gain it adds in one octave going
    down: median 12 dB, 261 entries ≥ 30 dB (beyond an LR4 inverse), 57 ≥ 36, 6 ≥ 42 (near an
    8th-order inverse), mostly held to 5 Hz with 40-60 dB peak boost. Several authors agree on
    the same steep correction for Master and Commander, Kingdom of Heaven DC, Safe House,
    Hunger Games: Songbirds & Snakes, Nobody, Wreck-It Ralph and Battleship. A pointer to test
    material only; nothing here calibrates anything.
  * **A real steep title is already handled.** Safe House (2012, 5.1, 110 min; extracted as
    `data/Safe_House_2012.npz`, not in the baseline set) has a 39-51 dB/oct edge at 26-33 Hz on
    every channel, then a flat floor ~32 dB down that is real, tracking programme (40-43 dB
    loud-quiet contrast): a steep filter with a finite stopband. The default accepts `flatten`
    (+32.3 dB, 4 sections, no clipping), flat within 1.3 dB from 5 to 63 Hz. mobe1969's
    authored 2012 filter undoes the same edge to within ~2 dB and then goes ~10 dB past flat
    below 20 Hz (a taste the goal-tilt dial can express). The two catalogue entries labelled
    2025 are for a different 90-minute film and do not fit this track.
  * **Noise-floored injection.** Without a floor after the filter, a steep stopband is clean
    programme that tracks perfectly all the way down, which is easier than any real disc.
    `inject_variants.py --noise-db` adds independent white noise per channel after the filter,
    at a level below the mix plateau, so where the programme drowns (the recoverable edge) is
    known exactly. −80 dB is about a 24-bit floor. `score_injected.py` scores each run: median
    shortfall inside the recoverable band against the original's own corrected curve, and the
    frozen protocol's measure, the most the cascade gains where noise dominates. BW8/12/16 @ 30
    Hz at −40/−60/−80 dB on Black Bag and Hulk: **the default accepts 2 of 18**, and declines
    almost all the rest on "introduces a cliff of 90-220 dB/oct" at the recoverable edge.
  * **Why.** The priced target is already right: contrast falls to zero where the programme
    drowns, so the target asks for the inverse down to there and nothing below, and the fits
    follow it. The shape clauses, judged from the tracking floor, reject that fall into the
    noise as a cliff.
  * **Opt-in: judge from the content edge.** `judge_from_content_edge` (`--content-edge`;
    default off) starts the judged band at `content_edge_hz`, where contrast stops licensing
    the whole deficit, and below it `_within_ceiling` allows a cascade no more boost than
    contrast licenses (+ `level_tolerance_db`). Prototype results: 17 of 18 noisy variants
    accepted, median shortfall 0-1.6 dB on 15 (5.2-5.7 dB on two Black Bag variants won by a
    `counterfactual`); the six no-noise controls accepted (0.4-1.5 dB on five). Hulk BW8 @ 30,
    −80 dB still declines, on device drift (F1). Real titles: probe at `--tol 0` unchanged on
    all ten, option on or off; Safe House unchanged. Frozen protocol: identical except
    `steep_leakage`, accepted on both seeds (it abstains by default). Corpus: gated 0/45 as
    before; positives 7/9 → 8/9 (filtered/5 recovered); natural_droop 5/9 unchanged.
  * **Why it is off by default.** Contrast measures loud scenes. Below a steep edge it licenses
    boost wherever loud scenes stand clear of the floor, and so lifts the floor under every
    other scene: gain where noise dominates 0-4 dB on most Black Bag variants (7 dB on BW16 @
    −80), 4-17 dB on Hulk's, 6.6-7.4 dB on `steep_leakage`. Three bounds on "how far the
    programme stands above the noise on average" were tried and **all failed**: frame mean
    power (a few transient frames at scene changes own it: 25 dB above both envelopes at 5 Hz
    on `steep_leakage`), frame median (sparse programme hides under it: corpus positives 7/9 →
    5/9, variants 2/18), and mean over loud-or-quiet frames (the same transients sit inside the
    loud class: 8.3 dB into noise on `steep_leakage`). Whether a lift that loud-scene contrast
    bounds is acceptable is a listening question, now priority 1.
  * **Bugs found on the way, fixed before the numbers above:** the guard first judged below
    the design range (rejecting sound candidates on "boosts 0.2 Hz"); the content edge moved
    every fully licensed band up by one grid bin; and the probe's rejudge re-derived the judged
    band itself, so it could not see a judging change at all. It now judges exactly as `run`
    does, and `snapshot --content-edge` probes the opt-in.
  * **Checks on the committed code.** Option off: probe at `--tol 0` unchanged on all ten real
    titles; test suite 500 passed, 1 skipped. Option on: probe at `--tol 0` unchanged on all
    ten; Safe House unchanged; all 24 variants reproduce the prototype's winner, shortfall and
    gain where noise dominates exactly; `steep_leakage` accepted on both seeds as above (7.4
    and 6.6 dB into noise). The synthetic protocol and corpus figures above are the
    prototype's; the port reproducing the variants and `steep_leakage` exactly is why they
    were not rerun.
* **F1 — done: the drift screen charges a fragile cascade its drift instead of vetoing it.**
  * **The inconsistency.** `AcceptParams.max_drift_db` says the fitter uses drift only to
    *prefer* a robust cascade among equals; `accept` judges the published, quantised response
    and does not gate on drift. But when no section count reached the residual target,
    `_Escalation.finish` kept the most accurate cascade *inside* the limit however much worse
    it was, and the most accurate of all when none was inside. So drift decided on luck. On
    Hulk BW8 @ 30, −80 dB every 2-4 section fit reached 0.5-1.9 dB and drifted 3.5-9 dB (p90);
    the lone section happened to drift 2.1, and a 13.9 dB fit was kept over a 0.5 dB one.
    Where nothing was inside the limit, drift was ignored entirely: Send Help's accepted
    `flatten` drifts 3.9 dB, Obsession's losing `counterfactual/35dB` 21 dB.
  * **The planned check (a smooth pole-radius penalty) cannot fix it.** It was tried as P20
    (e573354): a far better predictor of p90 drift, rejected at 2.25x the fit cost. A cheap
    closed form, Σ 20·log10(1 + step·(1/|A(e^jω)| + 1/|B(e^jω)|)) per bin (log correlation 0.94
    with p90 over 150 random low-frequency cascades), was tried here in the cost on Hulk's
    `flatten` target. The fits get more robust but not robust enough: 3-4 sections at residual
    3.4-3.7 dB and p90 3.4-4.5 dB, against 0.5 dB and 3.8 unpenalised. No cascade reaches
    both, because an 8th-order inverse at 30 Hz needs poles near z = 1 at 96 kHz (the worst
    drift sits at 6-7 Hz, below the tracking floor). The limit is a property of the target.
  * **The change.** `finish` keeps the cascade with the least *exposure*: the residual inside
    the drift limit (so the order there is exactly as before), residual **plus** drift outside
    it — the triangle-inequality bound on how far what plays can sit from the target. Ties go
    to fewer sections. `settle` (first count that both publishes and reaches the target) is
    untouched. Taking the *larger* of residual and drift was tried first and **rejected**: on
    the corpus's `filtered/1` it swapped a publishable 3.85 dB shelf for a 2.28 dB cascade
    drifting 3.5, realised 3.6 dB off on the device and rejected for a cliff (a lost true
    positive). Dropping the screen altogether was worse again: on Obsession a 2.0 dB cascade
    drifting 11.1 dB with 1.8 steps of DC headroom displaced a 4.65 dB shelf and still passed.
  * **Hulk BW8 @ 30, −80 dB, `--content-edge`:** now accepted — `flatten`, 3 sections (low
    shelf 13.32 Hz −12.5 dB, low shelf 21.15 Hz +14.5 dB, peak 16.67 Hz +26.0 dB), spread
    3.0 dB, tilt +0.2 dB/oct, 0.60 dB of device rounding error. Against injected truth:
    median shortfall 0.5 dB inside the recoverable band, 11.4 dB gained where noise dominates
    (its neighbours: 10.7 on −60, 16.8 on BW16 −80 — the opt-in's known cost, not new). By
    default it still declines, on the cliff, as before.
  * **Real titles.** Probe at `--tol 0`: unchanged on all eleven (it does not refit). Real runs
    on all eleven, with a scratch-only log line naming every fallback that differs from
    HEAD's rule: two fits on two titles, **no winner changes**. Obsession's
    `counterfactual/35dB` goes 3 sections → 1 and fails either way. Send Help's
    `counterfactual/25dB` (neither fit inside the limit) goes from a 1.35 dB fit drifting
    6.7 dB, which passed, to a 2.17 dB fit drifting 4.8, which fails on tilt: a passing loser
    lost, recorded rather than tuned around. Every other difference `compare_verdicts.py`
    shows against the baseline records (28 Years Later, Bugonia, Caught Stealing) predates
    this change; the log line did not fire there.
  * **Synthetic protocol**, both seeds, HEAD against the change: no decision moves; failure
    text changes only on candidates rejected both times (natural_bass_light, varying_filtered,
    steep_leakage).
  * **Negative corpus:** identical to `negative_corpus.json` on all 63 cases (selection,
    sections, recovery): gated 0/45, gate passes; natural_droop 5/9; positives 7/9.
  * **Steep variants** (31: Black Bag, Hulk, Send Help), option on and off. The log line fired
    on 11 in each mode; those 22 were rerun at HEAD to compare (the rest are unchanged by
    construction). **On:** Hulk BW8 @ 30, −80 dB declined → accepted (above); two no-noise Hulk
    controls change winner and get no worse (BW12 @ 32: `parametric` 1.2 dB median shortfall →
    `counterfactual/50dB` 0.7; BW16 @ 30: 0.5 → 0.4). Noise-floored variants accepted: 18/18
    (was 17). **Off (default):** Black Bag BW16 @ 30, a no-noise control, declined → accepted
    as `counterfactual/50dB` with a 6.5 dB median shortfall: nothing lifted where there is no
    noise, but a weak partial answer — the same pattern as priority 3. Hulk BW8 @ 30, −80 dB
    declines either way; only the reason changes.
  * **Records** not refreshed: no real title's winner moved.
* **Core-pipeline review folded in (2026-09-29).** A second review of the pipeline, its
  caches and its validation, checked against the code at f8ca290. Planning only: no code,
  threshold or record changed, and no run was made.
  * **New items:** C3 (parametric cache key), F4 (fits discarded before screening), C4
    (duplicate waveforms), C5 (timing and fit-stat accounting), C6 (AGENTS.md corrections),
    E9 (boost past the ceiling, record-only), E10 (a fresh protocol, parked). C3, F4 and C4
    were confirmed by reading the code; the review also reproduced F4's mechanism in a mocked
    escalation; its frequency on real titles is not known.
  * **Folded into existing items:** noise scoring into priority 3; the `departure_db`
    weighting hypothesis into 4; the meaning of each robustness measure into 6 (F1's
    follow-ups); scene-block resampling into 7 (T8); the scene-partition design into E1.
  * **Reordered.** Priorities are renumbered: old 1 (`--content-edge` default) is now 3, old
    2 (F1's follow-ups) 6, old 3 (steep-variant selection) 4, old 4 (T8) 7, old 5 (device
    harness) 9, old 6 (E1) 10. Earlier Progress entries keep the numbers they were written
    with.
  * **Not taken up:** sharing and caching fit requests across strategies and titles, reusing
    more analysis features, and further optimiser experiments. No measurement shows the same
    fit request recurring, and at 40-80 s a title the complexity is not yet paid for. Listed
    under `TODO.md`'s Performance, to revisit once C5's numbers exist.
* **C3 — done.** The parametric stage cache's key now holds `ParametricDerivation`
  (`pipeline.parametric_derivation`): the fitter's `DesignParams` plus every other setting
  `parametric_targets` reads through the deficit, pricing and goal-tolerance steps — goal tilt,
  goal tolerance, `min_judge_octaves`, `verify_floor_hz`, the deficit-anchor settings
  (`flatten_settled_octaves`, `flatten_deficit_floor_db`), `flatten_taper_ratio` and the
  exclusions. `Strategy` gained `cache_params`, separate from `effective_params`, so what a
  proposal records it ran with (still the `DesignParams`) is unchanged. `verify.py` joins
  `PARAMETRIC_MODULES` (`house_curve_db`). Existing entries miss once and are rebuilt.
  * **Tests:** each setting above changes the key; acceptance-only settings
    (`level_tolerance_db`, `restore_caps_db`) do not, so judging tweaks still reuse the fit;
    a warm run after changing goal tilt or goal tolerance equals a fresh run at the new
    setting. Both warm-vs-fresh tests fail on the previous code. Full suite passes.
  * **Probe** at `--tol 0`: nothing moved on any of the eleven titles (all parametric
    proposals were recomputed under the new key, so the cached defaults were not stale).
  * **Real run**, 28 Years Later (`parametric` wins it), `--no-cache`, previous commit in a
    worktree against this change: `compare_records.py` identical. No decision can move on
    default settings, so the synthetic protocol and corpus were not rerun.
* **C6 — done.** AGENTS.md: identification is on the path to a target through `parametric`
  (layout table, order of a run, "the target is the outcome"); `parametric` fits inside
  `design` before `_fit_all`; the fitter's "~75% of a run" replaced by the shares re-measured
  from the ten baseline records' stage timings (analysis and `parametric` cached): fit 234 s
  (49%), judging 196 s (41%), targets 50 s (10%). Docs only.
* **T8 step 1 — reference versus tracking floor under injection (2026-09-29).** Analysis
  only, from the stage caches: for Black Bag, Incredible Hulk and Send Help and their 43
  injected variants, the mix plateau, tracking and level-invariance floors, deficit anchor,
  judged band and deficit-to-ripple ratio (default parameters, analysis modules unchanged
  since the baseline).
  * **The reference is stable.** Black Bag keeps −61.1 dB over 50.2-82.8 Hz on 16 of 18
    variants (LR4 @ 25 and @ 35 move it by under a dB and 0.1 octave); only LR4 @ 30 moves it
    (−63.8 dB, 100.7-129.9 Hz). Hulk and Send Help move by at most 1.8 and 3.9 dB, the
    region's lower edge following the injected corner.
  * **The tracking floor is not, and not because of the reference.** Black Bag original: 25.1
    Hz. Same reference, filter injected, no noise: BW8 @ 30 8.9 Hz, BW12/BW16 @ 30 17.7 Hz,
    BW12 @ 32 35.5 Hz. LR4 @ 35 keeps its reference and still drops to 9.2 Hz. Adding a
    delivery floor raises it again (BW8 @ 30: −80 dB 12.5, −60 dB 17.7, −40 dB 25.1 Hz).
    Hulk and Send Help originals track to the bottom of the band; their noiseless variants do
    too, and noise floors put Hulk's at 11-21.7 Hz. A steep filter makes the bands below its
    corner look tracked: most likely leakage from the tracked passband — the filter's own
    stopband output, or the estimator's window at over 100 dB of attenuation. Not yet told
    apart.
  * **Decision:** step 2 (scene resampling) not run; it measures estimator variance, and this
    is a bias. Priority 7 now asks which leakage it is, on the harness. No code changed.
* **F4 — checked, not adopted (2026-09-29).** The mechanism is real: `_escalate` screens only
  the lowest-objective fit per section count. Two ways of using the fits it discards were
  built and run against HEAD (41b9a6d), each with a scratch-only log naming every fit where
  it chose differently, so "before" runs were needed only there. Neither is merged.
  * **Every fit in a tier competes** (the review's proposal): on the 11 real titles a wrong
    decline and two lost passes. Bugonia's accepted one-section `flatten` became a failing
    three-section one (fit 0.559 → 0.518 dB; two sections under 1 dB of contribution, extent
    short); Caught Stealing's `counterfactual/35dB` (2 → 4 sections) and Hulk's
    `counterfactual/25dB` (a new cliff) lost their passes. When nothing reaches the residual
    target, the fallback takes the least exposure over every fit, and some three- or
    four-section fit always wins by hundredths of a dB. Stopped after the real titles.
  * **Substitute only when the tier's best cannot publish**, and only by a publishable fit
    with less exposure (F1's rule inside the tier). Real titles: verdicts identical on all 11;
    Send Help's accepted `flatten` changed from a 0.328 dB fit drifting 3.89 dB (nothing in
    its budget published) to a 1.062 dB one drifting 2.59, corrected curve within 1.3 dB and
    flatter (spread 5.65 → 4.64 dB, tilt 2.38 → 1.0 dB/oct). Steep variants, default: the
    substitution fired on 29 of 43; 3 winners changed — Hulk LR4 @ 25 (`counterfactual/50dB`
    → `flatten`) and LR4 @ 35 (→ `counterfactual/45dB`) score the same against truth (median
    shortfall 0.5 → 0.4, 0.9 → 0.2 dB), and Black Bag BW12 @ 30, a no-noise control, went
    from declined to a `counterfactual/35dB` 12.2 dB short; 3 candidates gained a pass, 2
    lost one. `--content-edge`: fired on 32; of the 22 compared, no winner changed (1 gained,
    1 lost); the remaining 10 were not run once the corpus had decided. Synthetic protocol,
    both seeds: identical. **Negative corpus:** gated false acceptances 0/45 unchanged,
    natural_droop 5 → 4, but **positives 7/9 → 6/9** — filtered/1's robust one-section
    `parametric` (the case in F1's own docstring) lost to a more accurate multi-section
    cascade that fails on a cliff at 6.6 Hz. filtered/7 improved (1.18 → 0.77 dB RMS).
  * **Decision:** not adopted — a lost true positive is a worse selection, which the
    regression rules do not allow. Both failures are the same finding: widening the set the
    fitter picks from, on its own objective, finds cascades acceptance rejects. The residual
    is not a proxy for the verdict ("never trust a residual", from the other side). Using the
    discarded fits properly means judging them; parked under priority 11.
* **F1 follow-up — the drift screen jitters the published parameters (2026-09-29).**
  `_published_drift` ran the p90 jitter on the optimiser's raw floats, `accept` on the
  canonical rounded ones; now both use `publication_filters`, so the screen predicts the drift
  the verdict reports (a test asserts they are equal on a raw fit; it fails on the old code).
  Validated like F4, against HEAD, with a scratch-only log naming every fit whose final answer
  the change moved, and "before" records reused from F4's validation (same fitter).
  * **Real titles:** the change fired on Bugonia and Caught Stealing; no winner or accepted
    cascade moved. Bugonia's `parametric` newly passes (one shelf in place of a shelf and a
    peak); Caught Stealing's `counterfactual/35dB` newly fails (a 0.514 dB fit in place of
    0.905, with 15.8 dB of ripple against 2.8 in the material).
  * **Steep variants, default:** fired on 21 of 43. Winners changed on 4, each scored against
    truth: Hulk LR4 @ 20 (`flatten` → `counterfactual/50dB`, median shortfall −0.1 → 0.0 dB,
    worst 6.8 → 7.8), Send Help LR4 @ 25 (`flatten` → `counterfactual/50dB`, −0.8 → −1.6,
    worst 19.8 → 21.3), LR4 @ 30 (`counterfactual/50dB` → `flatten`, 0.6 → −1.3, worst 28.4 →
    27.4), LR4 @ 35 (`flatten` → `counterfactual/50dB`, −0.1 → 0.8, worst 31.9 → 30.1).
    Accepted cascades changed on 2 more: Black Bag BW8 @ 30 (8.8 → 8.6) and LR4 @ 35 (11.3 →
    8.8). No gain where noise dominates on any.
  * **`--content-edge`**, by rejudging both record sets (the fits do not depend on it; 33
    titles checked): winners changed on 2 — Black Bag BW8 @ 30 (`counterfactual/35dB` →
    `/25dB`, 5.4 → 4.8 dB median short) and LR4 @ 35 (`counterfactual/35dB` → `parametric`, a
    +2.9 dB cascade 15.7 short against 11.3: weaker, the pattern priority 4 is about).
  * **Synthetic protocol**, both seeds: identical. **Negative corpus** against HEAD's (E9's)
    run: gated 0/45, positives 7/9, both unchanged; natural_droop 5 → 4; filtered/8
    recovers 1.00 → 1.15 dB RMS.
  * **Decision:** adopted. It corrects what the screen measures rather than tuning it, loses
    no true positive and admits no false acceptance; the winner changes score as well
    against truth, give or take a dB, except one weaker opt-in answer. Records not refreshed.
* **F1 follow-up, docs (2026-09-29).** AGENTS.md now says what each robustness quantity
  measures and over what — fit objective, `fit_error_db`, p90 drift, exposure, device error
  and the corrected curve — and that stability is a separate veto. Writing it down found
  `fit_error_db` carrying two meanings: the objective (target error or quantisation change,
  whichever is larger) unless pruning dropped a section, then the target error alone. Added to
  TODO 5; changing it moves what `residual_target_db` compares against, so it is not done here.
* **R2a follow-up — cache writes on Windows (2026-09-30).** CI on `38ef5a0` failed
  `test_no_reader_ever_sees_a_partial_entry` on Windows, both stores: `os.replace` raised
  `PermissionError` (WinError 5) because Windows refuses to rename over a file another
  process has open, and the concurrent reader had it open. Step 2's "a reader sees the old
  file or the new one" held; the writer crashed instead, which would have failed a run or a
  request whenever two processes shared a cache. `_write_atomic` now retries the rename
  through short waits (`REPLACE_RETRY_S`, about 1.9 s in all), and if the entry is still
  held, drops the write with a warning: what is already there is the same payload or a stale
  one, so a skipped write costs a recompute, never a wrong answer. Tests: a rename refused
  twice then allowed lands; one refused throughout is skipped without raising, leaves the
  old entry and no temporary file. Probe (`--tol 0`): nothing on any title; `cache.py` is in
  no stage key. Full suite passes locally.
* **R2b step 2 — the server, and timed (2026-09-30). R2b done on beqforge's side.**
  `serve-designer --shared-root DIR` (must be a directory; off by default) passes the root to
  `request_from_json`. An `UnusableReference` is answered **422** with
  `{"error", "array", "reason"}`; a malformed body stays **400**. `GET /health` answers
  `{"status": "ok", "contract_version": "1.2", "shared_root": true|false}` — `status` kept for
  anything already polling it (beqdesigner's §3 names only the other two; to tell them).
  `CONTRACT_VERSION` is 1.2; responses echo the request's version, as before.
  * **Checks:** in-process server tests — `/health` with and without a root; a request by
    reference answers exactly as the same request inline over a real socket; a reference
    without a root is 422 naming `mono_mix`; an escaping path is 422 naming the channel; both
    forms in one array is 400. Full suite passes. `smoke_test_exe.py` now also sends its
    request by reference (float64 WAVs under `--shared-root`) and requires the same answer;
    it passes on a local Linux build.
  * **Timing** (`request_timing.py --reference`, idle machine): One Battle After Another,
    beqdesigner's measured title — 2.7 h, 8 channels, a 932 MB body. Warm, inline: caller 5.74 s
    (base64 and JSON) + wire 2.02 s (read 0.19, parse 0.67, decode 1.16) = 7.76 s. By
    reference: caller 0.69 s (SHA-256) + wire 0.96 s (read the WAVs, check) = 1.65 s. Design
    33.5-33.9 s either way. So 6.1 s saved a request, about 15% of a warm one end to end —
    the same as beqdesigner's own figures (8.4 against 2.2 s).
  * **To tell beqdesigner:** beqforge serves 1.2 by reference now; their D1.1 (contract text,
    schema, conformance rows), D1.2 (binding), D1.3 (sources) and D1.4 (configuration) are
    theirs. `/health` carries `status` beside the two §3 fields.
* **R2b step 1 — arrays by reference (2026-09-30).** Unparked on request, against R2a's
  timing decision; beqdesigner's own measurement (`design/designer-by-reference.md` §2: 8.4 s
  inline against about 2.2 s by reference on a 2.7 h title, counting the caller's encoding)
  supports it. Built to their §3, which carries our §6 amendments. New `beqforge/reference.py`:
  `resolve` refuses an absolute or backslashed path, a `..` component, and anything whose real
  path (after symlinks) leaves the root's; `read_column` decodes one WAV column by the
  contract's arithmetic (integer `s / 2**(b-1)`, float widened) with `scipy.io.wavfile`, each
  file decoded once per request; `array_from_reference` checks rate (refused, never
  resampled), channel range, frame count and the SHA-256 of the decoded column, all before
  the array is used. A reference that cannot be honoured raises `UnusableReference` naming the
  array — deliberately not a `ValueError`, which the server answers 400. `request_from_json`
  takes `shared_root` and accepts exactly one of `data_base64` or `file` per array (both, or a
  `file` without `sha256`, is malformed); requests may mix the two; the material stays
  "designer-request".
  * **Checks:** s16, s24 (plain and WAVE_FORMAT_EXTENSIBLE, as ffmpeg writes), s32 and float
    WAVs written byte by byte decode exactly by the arithmetic; u8 refused; each path escape
    (absolute, `..`, backslash, a symlink out of the root) refused; channel, shape, digest,
    missing file, non-WAV, rate and no-shared-root each refused with the array named; a mixed
    request by reference equals the inline one array for array and in cache key. Against the
    caller's own decoder: beqdesigner's `soundfile` and ours give identical SHA-256s for
    Ballad of Wallis Island's real `mono.wav` and all six columns of its `multichannel.wav`
    (s24). That title by reference and inline through `design()`: `compare_records.py`
    identical, and the same record name (audio digest). Full suite passes; probe at
    `--tol 0`: nothing moved.
* **R2a step 5 — proved in the executable, and timed (2026-09-30). R2a done.**
  * `smoke_test_exe.py` now starts the executable with `--cache-dir` and sends its request
    twice: the second answer must be identical, its record's stages must include
    `analysis/cached`, and the directory must hold entries. The server refuses the cache unless
    every cached stage's baked digest is present, so that hit covers them all (the request is
    `flatten` only, as before; `parametric`'s reuse is covered by the in-process server
    tests). Passes on a local Linux build; CI runs it on every platform.
  * The server logs one timing line per request (body size; read, parse, decode, design,
    respond). `tools/experiments/request_timing.py` POSTs a real title as beqdesigner does,
    cold then warm twice, under `systemd-inhibit` on an otherwise idle machine. Alto Knights
    (8 channels, 123 min, the largest): body 708 MB; cold 110.5 s (wire 1.41 s, design
    109.0); warm 50.6 and 50.7 s (wire 1.51 and 1.48 s — read 0.13, parse 0.50, decode 0.87 —
    design 49.1-49.2). Client-side encode, beqdesigner's cost, 1.87 s.
  * **R2b decision:** stays parked. Requests by reference would save only the wire, 3% of a
    warm request when both run on one host. Its other trigger stands: a designer on another
    host, where 708 MB is about 6 s at 1 Gb/s. **To tell beqdesigner** (their D1): R2a is in,
    no contract change; D1 waits on a remote-host deployment.
* **R2a step 4 — `serve-designer --cache-dir DIR` (2026-09-30).** Off by default, like
  `--record-dir`. When set, the server builds one `DirStore` at start-up and
  `designer.design(..., cache=store)` passes it to `run`; the start-up line names it. Several
  servers may share the directory (step 2's atomic writes; each server single-threaded).
  * **Checks** (real servers in-process, one directory): the same request twice — the second
    reuses the analysis and `parametric`, and the responses are identical; a second server
    with `--goal-tilt` 1.0 reuses the analysis and recomputes `parametric`, both
    configurations' entries kept; a request differing only in `bass_management` reuses the
    analysis; without `--cache-dir` nothing is written. Designer tests whose fake `run` took
    only `(material, params)` now accept the keyword. Full suite passes.
  * **Real title** (Send Help, sent as beqdesigner would, default settings): uncached 102.5 s,
    cached cold 103.1 s, warm 47.2 s (beside the test suite; not a benchmark). The three run
    records are `compare_records.py`-identical.
* **R2a step 3 — the frozen build keys the cache on baked digests (2026-09-29).** Found
  first, as the plan asked: a PyInstaller build of the current tree ran `beqforge design
  <title>.npz` straight into `FileNotFoundError: …/beqforge/__init__.py` from
  `cache.digest_of` — the packaged CLI could not run with its default cache. A live bug,
  independent of R2a. Now `beqforge.spec` writes `STAGE_DIGESTS.json` beside
  `BUILD_REVISION`: `cache.bake_digests` over `pipeline.cached_module_sets()` (the analysis
  and every caching strategy's modules — the one list both the keys and the bake read). When
  frozen, `digest_of` reads it; without it, or without the set asked for, it raises
  `cache.CacheUnavailable`, and `run` checks that once, warns once and runs uncached. Unfrozen,
  nothing changes.
  * **Also fixed here, from step 2:** `mkstemp` made every cache file private (0600), where
    they had been 0644; a directory shared between processes, possibly under different users,
    needs the ordinary mode, so the temporary file now gets `0666 & ~umask` (tested).
  * **Checks:** the baked map equals `digest_of` for every set and covers every caching
    strategy; frozen keys equal unfrozen keys without reading a source; a frozen build without
    the map raises; a run without it completes uncached with exactly one warning. Full suite
    passes; probe at `--tol 0`: nothing moved. The rebuilt executable: `beqforge design` on
    Ballad of Wallis Island ran cold (56.8 s, both stages cached) and then warm (19.5 s, both
    reused); `smoke_test_exe.py` passes.
* **R2a step 2 — atomic entries and a directory store (2026-09-29).** `cache.Store` is now
  a protocol with two stores. `FileStore` is the CLI's per-title file, unchanged in layout,
  now written to a temporary name beside it, fsynced and renamed, so a reader sees the old
  file or the new one. `DirStore(root)` keeps one file per entry at
  `<root>/<stage>/<sha256 of the canonical key>.json.gz`, written the same way and never
  rewritten with different content, so configurations sit side by side; `load` still checks
  the stored key. `analyse`/`propose`/`run` take a path (wrapped in `FileStore`) or a store,
  so no caller changed; the module-level `load`/`store` remain as `FileStore` wrappers.
  * **Checks:** both stores round-trip bit for bit; another key is a miss; `DirStore` keeps
    two configurations; an entry holding another key is a miss; a truncated entry is a miss;
    `analyse` works with a `DirStore`; and, for both stores, a reader looping while another
    process rewrites a ~2 MB entry 25 times only ever sees a miss or the whole payload. Full
    suite passes. Probe at `--tol 0` against step 1's: nothing moved. 28 Years Later, warm
    (both stages reused): record identical to step 1's.
  * **Size:** 0.32 MB a title for analysis and `parametric` (largest 0.37), so about 32 MB
    for 100 titles, plus one `parametric` entry per extra configuration. No eviction needed.
  * **Found for step 3:** a frozen build of this tree (PyInstaller 6.22.3) runs
    `beqforge design <title>.npz` straight into `FileNotFoundError: …/beqforge/__init__.py`
    from `cache.digest_of`: the packaged CLI cannot run with its default cache at all. It
    predates R2a (`digest_of` is unchanged); step 3 fixes it.
* **R2a step 1 — the cache key is the samples, not the name (2026-09-29).**
  `cache.material_fingerprint` no longer hashes `material.name`, so a renamed or moved file
  hits, and so will a designer request (always named "designer-request") for the same
  samples. Tests: same samples under two names share a key; `fs`, coverage, a channel label or
  one sample still move it; a real `analyse` + `propose` of a uniquely named title leaves no
  trace of the name in the cache file. Key change only: every stored entry missed once. Probe
  (analysis recomputed) at `--tol 0` against C5's snapshot: nothing moved. 28 Years Later with
  the new warm cache (analysis and parametric reused): `compare_records.py` identical to C4's
  record. Full suite passes.
* **C4 — done, rescoped (2026-09-29).** C5 put headroom at 82% of judging; the duplicated
  waveform and sub feed C4 was written for cost about 2 s a run, so that version was not
  built. `verify.waveform_peak` now skips blocks that cannot hold the peak: every interpolated
  value is a weighted sum of the samples in the kernel's reach, so a block's peak is at most
  its largest sample times the kernel's largest polyphase gain (`resample_poly` scales the
  kernel by the factor; a 1e-9 margin covers rounding). Blocks are taken loudest first and the
  loop stops at the first whose bound is below the peak found. Same per-block computation, and
  a maximum does not depend on order, so the answer is bit-identical.
  * **Checks:** a test against the whole-signal interpolation on six stress signals
    (programme-like transients, a near-Nyquist tone with large intersample overshoot, the
    loudest sample on a block edge, equally loud blocks, a quiet block that must not be skipped,
    silence): exactly equal. Real programme (28 Years Later's sub feed through a shelf):
    identical, 4.93 s → 1.42 s. Full suite passes. Real runs, `--no-cache`, 28 Years Later and
    Send Help against records of the same code: `compare_records.py` identical (headroom is in
    the record; the probe skips it).
  * **Time:** 28 Years Later's headroom 18.3 → 6.6 s a run (one run, beside the test suite, so
    not a benchmark).
* **C5 — done (2026-09-29).** `Timings` now stamps the run's wall time (`elapsed_s`) and
  reports what no stage covers (`unattributed_s`), and times judging's parts (`details`:
  sub feed, verify, headroom, assess) beside the stages rather than inside them, so nothing
  is counted twice. Each report gets its own copy of `FIT_STATS` — it aliased the
  process-wide counter, which the next run reset. The record's `timings` carries all of it
  plus the fit statistics (optimiser runs, worker seconds, cost evaluations); older records
  simply lack them, and nothing reads them. `design_beq.py` prints them.
  * **Checks:** tests (elapsed covers the stages; details are not in the total; a report's
    fit cost survives a reset; the record carries it); full suite passes. Probe at `--tol 0`
    against E9's snapshot: nothing moved. 28 Years Later, `--no-cache`, against the F1
    follow-up's record of the same code: `compare_records.py` identical.
  * **What it measured** (28 Years Later, cold, one run): 129.7 s elapsed, 0.9 s outside any
    stage. Judging 22.3 s: headroom 18.3, verify 2.7, sub feed 1.2, assess 0.02. Fitting: 30
    optimiser runs, 200 s of worker time, 1.65M cost evaluations. This rescoped C4.
* **Priority 3, scoring — corrected noise level (2026-09-29).** `score_injected.py` now
  reports where the noise ends up, not only how much it was lifted: the injected floor is white
  at `noise_db` below the plateau, so the corrected noise is `gain − noise_db` re plateau.
  On the 18 noise-floored steep variants with `--content-edge` (winners from the refit-probe
  baseline): Black Bag's lifts are 0-7 dB, leaving the floor 36-80 dB down; Hulk's are 4-17 dB,
  leaving it 28-76 dB down, the worst at −40 dB floors (BW8 @ 30: +12.1 → −27.9 dB; BW12 @ 30:
  +11.7 → −28.3). Tools only; no decision touched.
* **T8 steps 2-3 — why the floor moves (2026-09-29).** Analysis only, on Black Bag and its
  variants (the reference plateau is 50.2-82.8 Hz on all used here, per step 1).
  * **Not leakage in the measurement.** Each band's envelope comes from a 4th-order
    Butterworth bandpass through `sosfiltfilt` (about 48 dB/oct skirts). Replacing it with a
    brick-wall FFT band changes every band's correlation by at most 0.10 and its level by
    under 2 dB, on the original, BW8 @ 30, LR4 @ 35 and BW8 @ 30 −80 dB alike.
  * **A marginal band decides it.** The original's floor is 25.1 Hz because 17.7-25.1 Hz
    correlates at 0.43 — while 12.5-17.7 and 8.9-12.5 track at 0.62 and 0.56. The walk stops
    at the first failure. BW8 @ 30 tilts that band's energy toward its top edge, next to
    tracked programme, and it reads 0.57; the walk continues to 8.9 Hz. Delivery noise takes
    the lower bands to about zero, which is why noise raises the floor again.
  * **The correlation is noisy.** A moving-block bootstrap (120 s blocks, 400 resamples, all
    bands resampled together) gives 17.7-25.1 Hz a 90% interval of 0.27-0.59 and a 36% chance
    of clearing 0.5. The floor itself, recomputed per resample: 25.1 Hz 55%, 35.5 Hz 14%,
    8.9 Hz 18%, 12.5 Hz or lower 12%, 50.2 Hz 2%. On BW8 @ 30: 8.9 Hz 34%, 35.5 Hz 24%, 17.7 Hz
    18%. The drop step 1 attributed to the filter is inside the original's own spread.
  * **Decision:** no code change. Step 1's "leakage" reading is withdrawn; the finding is that
    a per-title decision (hold and judged-band start) rests on a statistic whose sampling
    spread spans 1.5 octaves on a real title. Priority 7 now proposes a floor rule that
    accounts for it, as a decision change.
* **Priority 4 — weak winners on steep variants: checked, ranking retained (2026-09-29).**
  Every candidate on all 43 steep variants, from the refit-probe snapshot at a91e24c (both
  modes), scored against the injected truth as `score_injected.py` does (median shortfall
  against the original's own corrected curve inside the recoverable band). A winner is weak
  when another candidate was more than 1 dB closer. 63 winners across both modes; 13 weak:
  * **11 are acceptance.** In 10 the better candidate is `flatten`, within about 0-2 dB of
    truth where the winner is 3.5-15.7 dB short. Default mode rejects it on the steep edge: a
    cliff it relocates rather than removes (Black Bag BW8/BW16 @ 30, LR4 @ 35: 57-137 dB/oct
    at 16-22 Hz), unevenness (the −40 dB noise-floor variants, 13-19 dB of ripple), or one
    section contributing 0.98 dB against the 1 dB limit. With `--content-edge` it fails the
    ceiling check below the edge instead ("lifting the quiet floor": Black Bag BW12 @ 30
    −80 dB, BW8 @ 30). Hulk BW8 @ 30 with `--content-edge` is the one case the other way:
    `flatten` wins, and two `counterfactual` candidates that overshoot truth fail.
  * **2 are ranking, and both are the rule working.** Hulk BW16 @ 30 −40 dB
    (`--content-edge`): `flatten` 0.1 dB short against `counterfactual/35dB` 1.6, departures
    1.50 and 1.39 — inside `ranking_tie_db`, so fewest sections decides (3 against 4). Send
    Help BW8 @ 30 (`--content-edge`): the candidate truth prefers overshoots the original by
    2.5 dB; departure picks one 0.7 short.
  * **None is the proposal or the fit, and none is a cap.** Where `counterfactual` wins weakly
    it is because its target is small — 5.6-6.7 dB peaks on the −40 dB variants against
    `flatten`'s 20-24 — with pricing removing nothing, so T2's cap sizes are not what binds.
  * **Decision:** ranking retained, T2 stays parked. The departure-weighting hypothesis (linear
    Welch bins over-weighting 20-40 Hz) has nothing to act on: no weak winner is a ranking
    loss. What decides these titles is how the shape clauses judge a steep correction, which
    is priority 3's policy question — the evidence here goes to it: on steep injections the
    clauses reject the candidate closest to truth, in both modes, by different clauses.
* **R2 — added (2026-09-29).** Requested: let beqforge and beqdesigner work off a shared
  filesystem, with requests able to point at files and one cache both sides use, so a
  redesign skips the extraction. Reading the code for it: the server takes audio inline and
  uses no stage cache; the stage keys already carry the per-stage code digest the request
  asks for; `cache.digest_of` would fail in the frozen build. Placed at priority 9; the
  device harness and E1 move to 10 and 11. No code yet.
* **E9 — done (2026-09-29).** Every candidate now carries `evidence_excess`
  (`pipeline.evidence_excess`, into the record and, for the selected one, the corpus's per-case
  output): the exact published, quantised device response against `contrast_ceiling_db`, over
  the design grid inside the analysed band only (unmeasured bins are left out, not read as
  zero licence) — largest excess and where, its contiguous width, integrated positive excess
  in dB·octaves, whether it sits on a bin with no licence at all, and the largest boost inside
  exclusions reported apart. Unstable cascades get none (no steady-state gain). Record-only.
  * **Checks:** unit tests (a shelf over a flat ceiling, a one-bin hole, exclusions,
    unmeasured range, instability, a run's record); a run's verdicts are identical with the
    field stripped. Full suite passes. Probe at `--tol 0` against C3's snapshot: nothing moved.
    Negative corpus: selections, sections and recovery identical on all 63 cases, gate 0/45.
    Five cases' *losing* candidates carry different failure text from the committed
    `negative_corpus.json`; natural_droop/1 rerun at HEAD without E9 matches this run, so the
    committed file predates HEAD there, not this change.
  * **Audit** (published cascades against a ceiling rebuilt from each title's cached analysis;
    real titles from HEAD reruns, variants from their records): on the 11 real titles no
    candidate, accepted or not, exceeds the ceiling by more than 0.5 dB (worst accepted: Black
    Bag, +0.13 dB at 4.9 Hz). On the 43 steep variants, 72 of 191 candidates exceed it by over
    0.5 dB and 17 by over 3; accepted ones reach +4.0 dB over 0.58 octave (Black Bag BW16 @ 30,
    `counterfactual/50dB`, the weak winner priority 4 is about), the rest of the accepted under
    2.7 dB, mostly at the bottom of the band (4.9-8.7 Hz) or 18-20 Hz under a steep corner. The
    largest are rejected candidates on Hulk BW8 @ 30, −80 dB (`flatten` +14.1 dB over 1.3
    octaves). Corpus selections: filtered positives within +0.9 dB, except filtered/1's robust
    one-section shelf (+5.6 dB over 0.28 octave); natural_droop's accepted ones +0.7 to +4.8.
  * **Decision:** no gate. Real material never exceeds the ceiling; steep injections do, where
    the tracking floor is also falsely low (T8), and they are what priorities 3 and 4 are
    already examining. The field is there for them, and for the next review of a curve.
* **R2 split — answers to beqdesigner's `design/designer-by-reference.md` §6 (2026-09-29,
  their `63976c2`).** Nothing built; R2b waits on these answers being agreed.
  * **Q1, the split: accepted.** R2a (priority 9) and R2b (parked) are separate rows above.
    beqdesigner already caches its extraction, so the redesign cost R2 was about is our
    analysis, which R2a removes with no contract change. What R2a leaves unsolved is only
    the wire, which is R2b's whole case, to be settled by R2a's timings.
  * **Q2, no shared stage cache: agreed.** Only the audio is shared. beqforge never reads
    `manifest.json` or relies on the `work_dir` layout; beqdesigner never reads our stage
    cache. R2's "one cache both sides use" is withdrawn: there is nothing in it beqforge
    needs that the audio named in the request does not give. Atomic writes stay in R2a,
    because the server and the CLI may share a cache directory.
  * **Q3, the name: taken out of the key**, in R2a. No cached stage carries the material's
    name, so it only ever stopped a renamed file hitting. The by-path loader will also keep
    `name="designer-request"`, so records stay as today. Either alone gives a request by
    path and the same request inline the same key; doing both means the CLI's `.npz` and a
    designer request for the same samples share it too.
  * **Q4, digests as the key: no — keep hashing the samples in one pass.** The per-array
    `sha256` stays a check in the contract, not our key, so the contract does not pin our
    cache format and our key can change without a contract revision. The second hash costs
    about 0.25 s against the 21-100 s a hit saves.
  * **Q5, the wire rules: accepted, with these amendments before D1.1.**
    * State the digested bytes exactly: the selected column after decoding, as a
      C-contiguous little-endian float64 1-D array of `shape` elements.
    * "Resolves outside the root" means after resolving symlinks (`realpath`), not just a
      lexical `..` check; a symlink under the root pointing out of it is refused.
    * `channel` must be within the file's channel count; a WAV whose rate differs from `fs`
      is refused, never resampled.
    * Keep 400 for a body that does not parse or fails the schema (as `designer_server.py`
      does now), and 422 for a well-formed `file` that cannot be honoured: bad path, format,
      rate, shape, digest, or **no shared root configured on this server**. The body names
      the array (`mono_mix` or the channel label) and the reason.
    * Advertise the capability: `GET /health` reports the interface version and whether a
      shared root is configured, so a caller registered as `by_reference` can find a
      mismatched server at registration rather than on its first title.
    * Agreed as proposed: relative POSIX paths against a root each side configures, absolute
      paths and `..` refused; opt-in per designer; no inline fallback on 422; 422 never a
      decline; a request may mix inline and `file` arrays; channel labels stay the caller's.
  * **Q6, the follow-ons: yes to both, optional, after R2b.** A `design-request.json` would
    be an input for `design_beq.py` (a loader beside the `.npz` one), not for `replay.py`,
    which works from a record and needs no audio. It would stop the CLI re-extracting a title
    beqdesigner already has; `tools/extract.py` stays for use without beqdesigner. For
    records, we would rather not learn the `work_dir` layout (Q2): the request could carry an
    optional `record_path`, relative to the shared root, which the caller chooses and the
    server writes to, falling back to `--record-dir`. The designer-side drift banner is the
    caller's; `beqforge_revision` is already in every response for it.

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

**Records refreshed after E3 (d68eba0).** The table above is the state at 4858a45. The
`data/*.run.json.gz` records the probe re-judges against now come from d68eba0, with
Bugonia, Caught Stealing, Obsession and Send Help refreshed again at b168669. Current winners:
`parametric` on 28 Years Later; `flatten` on Alto Knights, Ballad of Wallis Island, Black Bag,
Bugonia, Caught Stealing, Obsession and Send Help; Dossier 137 abstains (`no_usable_plateau`,
see Progress). The next refresh is due when a change is accepted that
moves targets. **The Incredible Hulk** (5.1, 112 min, fairly full bandwidth) joined the set as a
tenth title at 0431bbc, the source for the injection experiments.

**Dossier 137 should not have been declined.** *(Superseded — see "Dossier 137 — decided" in
Progress: abstaining is right; the original reason was wrong.)* Every main channel is steeply rolled off (L 48.5
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
detection (TODO 11, beyond the tripwire above), the parametric/identification open questions,
and the performance ideas the 2026-09-29 review raised but that no measurement yet justifies
(TODO's Performance).
