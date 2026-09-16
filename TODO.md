# TODO

Live backlog for `beqanalyser`. What's built and why lives in [AGENTS.md](AGENTS.md) (and
[README.md](README.md) for day-to-day usage) — this is what's left, ordered by cost and
confidence, not urgency. Reprioritise as new titles or new material change what's actually
blocking, rather than working straight down the list on inertia.

This replaces `AUTOMATED_DESIGN.md`, `PERFORMANCE.md` and `DESIGN_EVIDENCE.md` (retired
September 2026, once their "how it works and why" content was folded into AGENTS.md). Full
historical derivations, numbers and the play-by-play that produced the resolved items now in
AGENTS.md remain in git history if a future decision needs to see the original working —
`git log --follow -- AUTOMATED_DESIGN.md` from before the retirement commit.

## Automated design (`beqanalyser/design/`)

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
  (`beqanalyser/design/diagnose.py`), so region selection and region validation are now
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

Fixed with `_trim_to_flat_subwindow` (`beqanalyser/design/diagnose.py`): before rejecting a
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
issue in "Do next" item 1 below, not a new defect from either fix here.

### Do next — cheap: replaces a known-wrong constant with a measurement `diagnose` already makes

1. **Derive `restore_caps_db` (currently a sweep of 25/35/45/50 dB) from `filter_floor_hz`
   instead.** `diagnose` already computes each filtered channel's attenuation at its own
   level-independence floor; nothing consults it. Every derived cap measured so far sits
   *below* the smallest swept constant, meaning every `counterfactual` candidate produced to
   date has already inverted past the point R2 says it is still safe to call a filter.
2. **Replace `knee_slope_db_per_octave` (14.0) with per-channel R2.**
   `diagnose.stratified_response` already measures the property (filter vs. natural envelope)
   the slope threshold is a poor proxy for; running it per audible channel removes a threshold
   known to misclassify — it must catch a real 15.9 dB/octave filter and spare a natural
   13.5 dB/octave channel, a 2.4 dB/octave margin a 2nd-order Butterworth sits inside of.

### Do soon — bounded, improves reliability of what's already shipped

3. **A smooth pole-radius penalty for the fitter/judge drift disagreement.** `_fit_structure`
   minimises drift at exact coefficients; `assess` measures the p90 across publication
   rounding, so the optimiser can settle on a cascade that measures robust and is not (poles
   near z=1 at 96 kHz). The cheap remedy (jittered evaluations inside the cost function) was
   tried and measured worse on every axis; the smooth one (penalise pole radius directly) has
   not been tried at all.
4. **`max_q = 6.0` contradicts the documented argument against constraining Q.** Q is
   downstream of the target; a Q rule penalises the correct inversion of a steep filter, and
   it's near-binding in practice — one title produced sections at Q 5.2–6.0. Either relax it
   or write down why it's needed after all.
5. **Reconcile `fit_error_db`/`residual_db` being reported for every candidate**, including
   `parametric`'s non-`fitted` ones. Useful in practice — it's how three abstaining titles
   were shown to be under-corrected by their *target* rather than by the fitter — but this was
   never reconciled with the external `designer-interface.md` contract's older wording that
   `non_parametric` candidates should leave it `None`. Check whether that wording has since
   been revised before treating this as settled either way.
6. **`Candidate.confidence` doesn't reorder `Report.accepted`.** The external contract wants
   candidates ranked by confidence; `Report.accepted` still selects by departure from the
   requested shape. Current reading: *don't* reorder — a scalar score overruling the
   acceptance model reintroduces the aggregate-blindness the evidence policy exists to defeat
   — but that should be a written decision, not a permanently open question.

### Backlog — real, but nothing on hand is asking for it yet

7. **A fraction dial, and a house curve reaching target construction.** The still-unbuilt half
   of the partial-correction work (steps 1–5 are built — see AGENTS.md). No title tried has
   asked for anything but flat, so there's nothing to size this against yet.
8. **Catalogue comparison / disagreement detector.** Not started. Hypothesis to test first:
   38% of authored corrections demand ≥24 dB/octave, a single low shelf can't sustain that
   below its knee, and 92% of authored responses *are* a single low shelf — so a meaningful
   share of existing filters may under-correct in the octave below the corner. Not a score:
   where the tool and an author differ substantially, look at the case.
9. **Expose `H_protect`'s default corner as a parameter.** Cheap, but nothing requires it
   until someone actually wants a non-default alignment.

### Blocked on data — don't schedule engineering time against these

10. **Does the guard generalise to real sparse material?** The item that most matters for
    trusting the acceptance model on a title unlike the eight on hand. Proven synthetically
    and on two titles with a measured floor at the *edge* of the content band; none of the
    eight has a floor sitting *inside* it, which is the case the guard exists for. Watch for
    the right material rather than manufacturing another synthetic case — that's how the
    guard's evidence got this far without settling the question.
11. **Dynamic processing (compression/limiting) detection + an abstain path.** No linear
    filter inverts a non-LTI system. Unscoped — worth designing the day a title is actually
    suspected of this, not speculatively before then.
12. **Reconcile time-frequency resolution.** `extraction.frame_samples` is 1024 (1.02 s,
    0.98 Hz bins); `diagnose.WELCH_NPERSEG`/`charts.NPERSEG` are 4096 (4.1 s, 0.24 Hz).
    Nothing reconciles them today. Low urgency until a title's verdict is shown to actually
    depend on which is right.

### Open questions specific to the parametric/identification path

Deprioritised: `flatten` and `counterfactual` have produced every accepted filter so far;
`parametric` has never won.

* What `N(f)` form and fit band generalise past one title — needs a corpus, not more analysis
  of one file.
* Scene segmentation algorithm and the absolute margin for it — currently a hand-picked
  constant; should be calibrated on the synthetic harness against a false-positive rate, per
  the "no per-title decision from outside that title" principle.
* Uncertainty quantification method for `identify` is unnamed (bootstrap over frames? profile
  likelihood? something else?).
* Automatic detection of an authored feature (e.g. a narrow LFE hump) that should be excluded
  before fitting — currently only reachable via `--exclude`, by hand.
* What to do when `channel_scope` reports `"mixed"` (per-channel diagnostics disagree) — the
  field exists to carry the finding; there's no policy for it yet.

### Known contradictions / rough edges in the current implementation

* Everything in "Do soon" above (items 4–6).
* `charts.py`'s `peak` curve is a per-bin maximum over frames — biased +9.3 dB on stationary
  noise for a two-hour title, by construction (max of chi-squared-2 samples). Deliberate,
  because it's what lets a chart be read against a published catalogue one — a high
  percentile (99.9th) would remove the bias and break that comparison. Not affecting any
  decision path: `extraction.py`'s peak envelope is a 95th-percentile, not a maximum.
* Cosmetic, low priority: many docstrings/comments across `beqanalyser/design/` and `tests/`
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

## External follow-up (not this repo's to fix, but worth tracking)

* A set of six proposals were sent upstream to the `designer-interface.md` contract in the
  sibling `beqdesigner` repo: a clipping-cost headroom field (not the cascade's peak
  magnitude), passing the sub-feed/bass-management config as an input, passing the target
  device's coefficient format and rate as an input, `confidence` as an ordinal in v1 rather
  than an uncalibratable probability, allowing `residual_db` for `non_parametric` methods, and
  a stated rule for what the designer may decline versus must report. All six are already
  adopted **internally** here (see AGENTS.md). Confirm the upstream contract document gets
  amended to match — this repo doesn't own that file, so can't close this on its own.
