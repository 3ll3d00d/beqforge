# Implemented design and pipeline changes

**Status: archived, review completed 2026-09-30.** This is historical evidence, not a
work queue. Original hypotheses and intermediate states below describe the code at the
time of the review; later outcomes supersede them. All outstanding follow-ups are tracked
only in [TODO.md](../TODO.md). Current behaviour is documented in [README.md](../README.md).

## Completed review status


Completed review outcomes; current priorities are exclusively in TODO.md. “Done” means
implemented; “checked” means measured with the existing behaviour retained. Detail follows
in this document or the research archive.

| ID | Status | Outcome, in one line (detail under "Progress") |
| --- | --- | --- |
| E2 | done | Corpus built (`negative_corpus.json`). Gated false acceptances 7/45 → 4/45 (low-end cap) → 0/45 (texture blocker); the gate passes. |
| E3 | done | Hold and deficit cap applied to every strategy; the ranking is unchanged. |
| E5 | checked | Hold stays: it is the only thing carrying tracking into the target. |
| E6 | done | Report half: judge's notes reach the response. Rate half: the corpus's `natural_droop`, reported not gated under the content principle. |
| E7 | checked | Fixed extraction bands kept; the targets barely move. Revisit if the plateau rule changes. |
| E8 | done | Digital silence excluded from both frame classes. |
| E9 | done | Every candidate records its boost past the evidence ceiling. Real titles: none over 0.5 dB. Steep variants: accepted up to 4.0 dB over half an octave. No gate. |
| T1 | done | `counterfactual` re-sums under the playback model. |
| T3 | done | Channels restored on their own texture, not a 14 dB/oct slope. |
| T4 | checked | No plateau change. Dossier 137 decided: abstain via the sub-band blocker, which since 2026-09-28 fires only when nothing in the sub band tracks. |
| T5 | checked | Folded into T4. |
| T6 | done | Judged band ends at the deficit anchor, not a fixed 45 Hz. |
| T7 | checked | Low priority; no verdict depends on it. |
| T8 | checked | Chained tracking rejected; the floor's spread is real (Black Bag 25.1 Hz in 55% of resamples). A confidence-bound floor rule was built and measured: more conservative and *less* stable on 4 of 7 titles with a floor, and it cut real correction on 28 Years Later and Alto Knights. Not adopted; the point rule already lands on each title's modal floor. |
| F1 | done | The drift screen charges a fragile cascade its drift instead of vetoing it; Hulk BW8 @ 30, −80 dB unblocked. The smooth penalty cannot help there (the target is fragile at any accuracy). |
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
| R2a | done | `serve-designer --cache-dir DIR`: a repeat request skips the analysis (Alto Knights 110 s cold, 50 s warm); the frozen build keys the cache on baked digests (the packaged `beqforge design` had crashed on its default cache); smoke test proves a warm hit in the executable. Follow-up: a write held off by a reader on Windows retries, then skips rather than raising. |
| R2b | done | `serve-designer --shared-root DIR`: arrays by reference (contract 1.2) — decoded, checked, 422 naming the array when unusable; `/health` advertises it. On a 2.7 h title the wire goes from 7.8 s to 1.7 s a request. beqdesigner's caller side (their D1.1-D1.4) is complete. The executable passes the by-reference and warm-hit smoke tests on all three CI platforms. |

**Done outside the IDs above:** designer diagnosis (`found`/`correction`/`alternatives`);
the response explains content, not cause; clipping stated in the response; shaping fraction
and level-invariance floor fixed; goal tilt and goal tolerance dials; texture blocker; the
sub-band blocker and its content condition; overshoot past the goal (checked, no change);
noise-floored injection (`inject_variants.py --noise-db`) and its ground-truth scoring
(`score_injected.py`); the steep-filter opt-in `--content-edge` (default off); the probe
now judges exactly as `run` does (`snapshot --content-edge` for the opt-in); designer contract
1.1 — every design the judge failed goes back in `rejected` with its reasons, review only,
beside the answer or the decline (probe unchanged; no decision touched).

## Implementation outcomes

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
* **Clipping is now stated in the response.** Headroom was measured on every run but surfaced
  only as one line buried in `verdict_notes`, and the typed `gain_reduction_db` field was always
  `None`, because beqdesigner's worklist never sends `bass_management` (`pipeline/library/run.py`
  `_design` omits it). The commentary now carries `clipping`: the sub-feed peak, and how far to
  turn the sub down, saying whether the model is the request's or the assumed LR4 80 Hz. Black
  Bag: "+1.3 dBFS — turn the sub channel down by 1.3 dB"; every other accepted title is under
  full scale (Bugonia peaks at 42%). **Pending, in beqdesigner:** thread the batch's bass
  management through `_design` into `design_if_needed`, so the typed field arrives on the
  listener's own crossover. Waiting for that repo's local work to finish first.
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
* **R2a/R2b — closed out (2026-09-30).** The executable workflow had not run since
  2026-09-17, so step 5's warm-hit check and R2b's by-reference request had only passed on a
  local Linux build. Dispatched on `3928780` (run 36717974193): built and smoke-tested on
  Linux, macOS and Windows, all passing — a cold and a warm request with `--cache-dir`, and
  the same request by reference under `--shared-root`, each through the frozen fitter's
  worker processes. beqdesigner's side of R2b (their D1.1-D1.4: contract text, binding,
  sources, configuration) is complete. `plans/R2a-server-stage-cache.md` is marked done.
* **R2a follow-up — request timeouts in CI (2026-09-30).** The same CI run failed two server
  cache tests on Linux with a client `TimeoutError` at 120 s. Not a hang: the server's late
  reply met a closed socket (`BrokenPipeError`), and the runner took 9 minutes over that test
  file against 2 locally, so the 33-41 s tests needed more than 120 s there. Every request in
  `test_design_designer_server.py` that runs a real design now waits `DESIGN_TIMEOUT_S`
  (900 s); `smoke_test_exe.py`'s defaults go from 20 s to 60 s for startup and from 90 s to
  600 s a request, ahead of its first CI run on the R2a/R2b build. Tests only; no probe.
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


## Windows output encoding and fit-pool sizing (3 October 2026)

`11fe3b9`: `beqforge.cli.main` reconfigures stdout and stderr to UTF-8 (the dispatch bypassed
each tool's own `__main__` reconfigure, so piped output on Windows was cp1252), and
`filters._physical_cores` asks Windows (`GetLogicalProcessorInformationEx`) and macOS
(`sysctl hw.physicalcpu`) for physical cores instead of falling back to `cpu_count()`. The
Linux `/proc/cpuinfo` path is untouched. Verified on Windows 11 when committed (full suite,
and extract/summarise/design end to end through a pipe).

* **Probe on the Linux baseline (2026-10-03).** "Before" at `a3eae69` in a worktree with its
  own `data/` of symlinks; "after" on `2f4fcb7`, whose `beqforge/` is identical to
  `11fe3b9`'s (the F2 commits since touch only `beqforge_device_check/`). All eleven
  `data/*.npz` titles: `compare --tol 0` reports nothing on any title, and the two snapshots
  are byte-identical. No real runs or synthetic protocol needed — nothing reaches a decision.
  Full suite on Linux: 684 passed, 2 skipped.


## Server startup configuration (30 September 2026)

`serve-designer --cache-dir DIR` previously created its directory on the first cache write;
`--shared-root DIR` required an existing directory. Both now create missing parents and
perform a temporary-file write/flush/cleanup before binding the HTTP socket. Creation or
write failure is an argparse startup error naming the option and path, rather than a
failure on the first request. Existing contents are preserved.

All 14 server configuration options accept `BEQFORGE_<OPTION>` environment variables,
with hyphens replaced by underscores. Explicit CLI values override the environment;
repeatable CLI options replace the corresponding environment list. Strategies use JSON
arrays of strings, exclusions JSON arrays of pairs, and boolean settings accept
true/false, yes/no, on/off or 1/0. `--no-content-edge` and `--no-quiet` allow disabling an
environment setting. Environment arguments use the existing argparse conversions and
configuration validation; `--help` lists the names and works even with invalid environment
settings. Other subcommands retain their existing configuration.

Checks: 29 startup/configuration tests passed, covering directories before binding,
obstructing files, failed writes, probe cleanup, all environment options, CLI precedence,
invalid inputs and help. The full suite passed 618 tests and skipped one in the restricted
sandbox; its 16 HTTP cases were blocked solely by socket creation. Those 16 passed when
rerun with loopback access (634 passed across the two runs). Ruff checks and formatting
passed. Only the transport script
changed: no `beqforge/` modules, targets, filters, judging or baseline records changed, so
the decision regression probe does not apply.

## Earlier real-title repairs (16 September 2026)

 the first real-title rerun since R1-R12 landed (16 September 2026)

Rerunning all eight titles surfaced two crashes and a genuine bug in R8's plateau discovery.
Full before/after is on the published Correction Ledger artifact. All three, fixed:

* `tools/design_beq.py` computed a `relevant`-channels list using
  `params.diagnose.min_passband_share`, a field R4/R5 deleted from `DiagnoseParams` — crashed
  every run, `--charts` or not, since it also feeds the record's stored curves. Replaced with a
  local, presentation-only `CHART_RELEVANCE_SHARE` constant; it does not feed any decision.
* `tools/render_ledger.py`/`ledger_template.html` assumed every record has at least one
  candidate (even a rejected one) to feature. R1's blockers can now stop a title before any
  target is built at all, leaving `candidates: []` — a case eight-for-eight prior runs never
  exercised. Both now render a "no candidate was ever constructed" state instead of crashing or
  linking a 404 image.
* **`plateau_reference`'s trend check read the wrong curve.** Region membership (the `within`
  mask) is decided from `discovery`, the 11-point median-filtered curve, specifically to
  "suppress estimator-bin scatter" (the function's own docstring) — but the width/slope
  admission test that follows read the raw, unfiltered `curve` instead. On real material that
  let ordinary bin-to-bin scatter reject a genuinely flat region: Tron's one candidate plateau
  (25.5-55.9 Hz, 1.1 octaves — well past the 1/3-octave minimum) measured +3.0088 dB/octave on
  the raw curve against the 3.0 limit, and +2.9228 on the very discovery curve `within` had
  already used to select it. Fixed by reading `discovery` for the slope too
  (`beqforge/diagnose.py`), so region selection and region validation are now
  consistent; regression test in `tests/test_design_references.py` reproduces it with a few
  synthetic estimator-bin spikes rather than needing real material. **Tron now recovers a
  filter** (`flatten`, 85% of the deficit, evidence score 0.95). Confirmed against all eight
  titles that no previously-accepting title's plateau region or level moved.

**Correction to the entry above: "Test 71 genuinely has no flat region" was wrong.** A human
looking at the spectrum sees it immediately — a clear plateau, a peak just below it in
frequency, then a rolloff — and the first fix's own diagnosis confirmed a real, wide (0.74-1.33
octave, depending how far it's trimmed) flat region exists at 24-63 Hz. What actually happened:
the one connected within-tolerance region (22.46-41.66 Hz) merged the peak's falling edge with
the genuinely flat stretch beside it, and the *whole region's* least-squares slope — -4.83
dB/octave — failed the 3.0 limit even though the flat part alone reads -1.99. That's a second,
distinct bug, now fixed: **`plateau_reference` tested each connected region as a single
all-or-nothing block instead of allowing a locally bad edge to be trimmed off.** A peak sitting
close enough in level to a real plateau to fall in the same tolerance band will always produce
this shape — the plateau does not stop being real because a peak sits next to it.

Fixed with `_trim_to_flat_subwindow` (`beqforge/diagnose.py`): before rejecting a
region outright, trim one point at a time from whichever end currently reduces the remaining
slope's magnitude more, stopping the moment the remainder is flat enough (or the width floor is
hit). A heuristic — it does not search every possible sub-window, so a region with the bad
influence spread through its middle rather than at an edge could still be missed — but it
targets exactly the failure found. Regression test in `tests/test_design_references.py` pins it
against the exact real Test 71 values (a direct test of the trim function, since reproducing
the failure through the full percentile pipeline synthetically turned out to depend on fine
bin-to-bin proportions that were impractical to fake convincingly). **Test 71 now recovers a
filter** (`flatten`, 93% of the deficit, evidence score 0.94) with a corrected curve that does
what a human would expect: the rolloff below the peak is lifted to meet the plateau, which is
left nearly untouched. Confirmed against all eight titles that no other title's plateau region
moved from this second fix.

**Two titles still correctly abstain, for reasons unrelated to either bug above:**
* **Blazing Saddles** finds a plateau (122.5-200 Hz) but still abstains — for a completely
  separate reason, "no qualifying loud events" (`extract`'s scene selection finds zero loud
  frames in 89 minutes). Plausible explanation: this is a mono-only extraction (`--mono-only`,
  a single downmixed channel), and summing a strong isolated LFE wall into dialogue/effects
  dilutes exactly the temporal peak-quiet contrast the scene detector looks for — not
  investigated further here; flagged as a real, separate limitation of mono-only material worth
  a second look if it recurs on other mono-only titles.
* **Nocturnal Animals** abstains on the `min_judge_octaves` guard (judged band collapsed to 0.5
  octaves under the tighter, more accurate boundary) — this looks like the guard correctly
  doing its job on a title that was always borderline (its own calibration used exactly this
  title).

**Current picture: 6 of 8 titles accept** (Alien, Test2 71, Test3 71, Test4 71, Test 71, Tron),
two abstain for the two distinct and separately-verified reasons above. Alien and Test4 71's
*selected* candidate shuffled between near-tied `counterfactual` boost-cap variants and
`flatten` across these reruns (e.g. Alien: 35dB → 25dB → 45dB) without their plateau or
evidence numbers changing — a symptom of the already-documented over-100%-recovery/near-tie
issue in the archived improvement review T2 (formerly "Do next" item 1), not a new defect from either fix here.
