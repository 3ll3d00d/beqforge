# TODO

Improvements to the design process itself live in [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md);
this file keeps what that plan does not cover.

Live backlog for `beqforge`. What's built and why lives in [AGENTS.md](AGENTS.md) (and
[README.md](README.md) for day-to-day usage) — this is what's left, ordered by cost and
confidence, not urgency. Reprioritise as new titles or new material change what's actually
blocking, rather than working straight down the list on inertia.

This replaces `AUTOMATED_DESIGN.md`, `PERFORMANCE.md` and `DESIGN_EVIDENCE.md` (retired
September 2026, once their "how it works and why" content was folded into AGENTS.md). Full
historical derivations, numbers and the play-by-play that produced the resolved items now in
AGENTS.md remain in git history if a future decision needs to see the original working — but in
the sibling `beqanalyser` repository this project was extracted from, not here: those files
were never under `beqanalyser/design/` and so weren't carried over by the extraction.
`git log --follow -- AUTOMATED_DESIGN.md` from before the retirement commit, there.

## Automated design (`beqforge/`)

### Resolved: the first real-title rerun since R1-R12 landed (16 September 2026)

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
issue in IMPROVEMENT_PLAN.md T2 (formerly "Do next" item 1), not a new defect from either fix here.

### Do next — cheap: replaces a known-wrong constant with a measurement `diagnose` already makes

Items 1 (derive `restore_caps_db` from `filter_floor_hz`) and 2 (replace
`knee_slope_db_per_octave` with per-channel R2) moved to
[IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) as **T2** and **T3**.

### Do soon — bounded, improves reliability of what's already shipped

3, 4. The pole-radius penalty for fitter/judge drift and the `max_q = 6.0` question moved to
   [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) as **F1** and **F2**.
5. **Reconcile `fit_error_db`/`residual_db` being reported for every candidate**, including
   `parametric`'s non-`fitted` ones. Useful in practice — it's how three abstaining titles
   were shown to be under-corrected by their *target* rather than by the fitter — but this was
   never reconciled with the external `designer-interface.md` contract's older wording that
   `non_parametric` candidates should leave it `None`. Check whether that wording has since
   been revised before treating this as settled either way.
6. `Candidate.confidence` not reordering `Report.accepted` moved to
   [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) as **E3**, which also asks for the decision to be
   written down.

### Backlog — real, but nothing on hand is asking for it yet

7. **A fraction dial.** The house-curve half is built: the goal below the knee
   (`--goal-tilt`, `--goal-tolerance`) now generates targets — see AGENTS.md. Still open: a
   dial for *how much* of the licensed deficit to restore. No title tried has asked for it,
   so there's nothing to size it against yet.
8. **Catalogue comparison / disagreement detector.** Not started. Hypothesis to test first:
   38% of authored corrections demand ≥24 dB/octave, a single low shelf can't sustain that
   below its knee, and 92% of authored responses *are* a single low shelf — so a meaningful
   share of existing filters may under-correct in the octave below the corner. Not a score:
   where the tool and an author differ substantially, look at the case.
9. **Expose `H_protect`'s default corner as a parameter.** Cheap, but nothing requires it
   until someone actually wants a non-default alignment.

### Blocked on data — don't schedule engineering time against these

10. **Does the guard generalise to real sparse material?** Still blocked on finding the
    material; the search, the stress-track shapes and the false-accept measurement are now in
    [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) (**E2** and "Stress tracks"). None of the eight
    titles on hand has a tracking floor sitting *inside* the content band, which is the case
    the guard exists for.
11. **Dynamic processing (compression/limiting) detection + an abstain path.** No linear
    filter inverts a non-LTI system. Unscoped — worth designing the day a title is actually
    suspected of this, not speculatively before then.
12. Reconciling time-frequency resolution (`extraction.frame_samples` 1024 vs
    `diagnose.WELCH_NPERSEG`/`charts.NPERSEG` 4096) is folded into
    [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) as part of **T7**.

### Open questions specific to the parametric/identification path

Deprioritised: `flatten` and `counterfactual` have produced every accepted filter so far;
`parametric` has never won.

* What `N(f)` form and fit band generalise past one title — needs a corpus, not more analysis
  of one file.
* Scene segmentation algorithm and the absolute margin for it — currently a hand-picked
  constant; calibrating it against a false-positive rate is part of
  [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) **E2**.
* Uncertainty quantification method for `identify` is unnamed (bootstrap over frames? profile
  likelihood? something else?).
* Automatic detection of an authored feature (e.g. a narrow LFE hump) that should be excluded
  before fitting — currently only reachable via `--exclude`, by hand.
* What to do when `channel_scope` reports `"mixed"` (per-channel diagnostics disagree) — the
  field exists to carry the finding; there's no policy for it yet.

### Known contradictions / rough edges in the current implementation

* Item 5 in "Do soon" above, and the items now in [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) (F2, E3).
* `charts.py`'s `peak` curve is a per-bin maximum over frames — biased +9.3 dB on stationary
  noise for a two-hour title, by construction (max of chi-squared-2 samples). Deliberate,
  because it's what lets a chart be read against a published catalogue one — a high
  percentile (99.9th) would remove the bias and break that comparison. Not affecting any
  decision path: `extraction.py`'s peak envelope is a 95th-percentile, not a maximum.
* Cosmetic, low priority: many docstrings/comments across `beqforge/` and `tests/`
  still cite bare section numbers (`§2.1`, `§14.2`, ...) left over from the retired
  `AUTOMATED_DESIGN.md`. Only references naming the file by name were repointed when it was
  removed; the bare numbers don't point anywhere now. Harmless — each citation sits next to a
  self-contained explanation — but worth a pass to either drop them or repoint them at AGENTS.md.

### Standing validation-gap caveats (not action items — just don't forget them)

* **Sparse real-programme generalisation is unvalidated.** The predeclared synthetic
  protocol (results retained in `evidence_validation.json`) falsified the old "temporal
  contrast proves restoration" reading, but it did not — and cannot — establish safe
  automatic restoration of arbitrary real source material. A naturally coloured source can be
  observationally identical to a mastered one; no threshold or parametric gate resolves that
  without additional information (e.g. a reference release).
* **Never calibrate a designer threshold against the catalogue's authored `mvAdjust`
  values.** They measure the wrong quantity (cascade peak magnitude) and are close to
  *inverted* against actual sub-feed clipping cost — a gate built and calibrated against them
  had to be withdrawn. See AGENTS.md's "Publication, playback and verification" for the
  quantity that actually matters.

### Performance

* Remaining budget/precision trades: ~1.4x more with a real quality cost, not adopted.
* Further algorithmic ideas beyond what's already been measured and rejected (see AGENTS.md's
  Performance notes for the list of what not to retry) — not started, no specific plan yet.
* From the 2026-09-29 pipeline review, not scheduled until IMPROVEMENT_PLAN C5 says where the
  time goes:
  * **Share numerically identical fit requests.** `parametric` fits inside `design` before
    `_fit_all`, and identical priced targets from different strategies are fitted separately.
    Extract `parametric`'s target construction, gather every request at `_fit_all`, and
    deduplicate on the complete numerical identity (target, grid, score and placement bands,
    bounds, seeds, realisation), never on resemblance. Keep each strategy's own score-band
    handling; unifying it is a decision change. Worth it only if identical requests recur.
  * **Cache fit results across runs**, keyed on that identity plus implementation digest and
    library versions, independent of the material. Atomic writes, bounded size, honours
    `--fresh`/`--no-cache`; never caches verdicts or headroom. Only after the item above.
  * **Reuse more analysis features**: remaining repeats of `mean_spectrum`,
    `plateau_reference`, `_flat_deficit` and `supported_mix_change`, and unchanged blocks
    across `counterfactual` caps. Match each estimator's window exactly; never merge the
    1024- and 4096-sample estimators in the name of reuse.
  * **Optimiser experiments** (more seeds on large, steep targets; refining retained
    candidates): only if F4 or IMPROVEMENT_PLAN priority 4 shows a candidate lost because the
    search missed a usable fit. Batching, warm starts and reparameterisation are numerical
    trades, not exact changes.

## External follow-up (not this repo's to fix, but worth tracking)

* A set of six proposals were sent upstream to the `designer-interface.md` contract in the
  sibling `beqdesigner` repo: a clipping-cost headroom field (not the cascade's peak
  magnitude), passing the sub-feed/bass-management config as an input, passing the target
  device's coefficient format and rate as an input, `confidence` as an ordinal in v1 rather
  than an uncalibratable probability, allowing `residual_db` for `non_parametric` methods, and
  a stated rule for what the designer may decline versus must report. All six are already
  adopted **internally** here (see AGENTS.md). Confirm the upstream contract document gets
  amended to match — this repo doesn't own that file, so can't close this on its own.
