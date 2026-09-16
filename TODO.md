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
