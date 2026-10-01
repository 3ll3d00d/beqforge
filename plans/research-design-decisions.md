# Research decisions: rejected approaches and retained rules

**Status: archived, review completed 2026-09-30.** This is historical evidence, not a
work queue. Original hypotheses and intermediate states below describe the code at the
time of the review; later outcomes supersede them. All outstanding follow-ups are tracked
only in [TODO.md](../TODO.md). Current behaviour is documented in [README.md](../README.md).

These spikes were measured and rejected, or concluded that the existing rule should stay.
Some entries also record tooling or an opt-in that shipped; retaining that does not adopt
the rejected default or gate. Revisit conditions live in TODO.md.

## Measured outcomes

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
* **C1 — opt-in rejected; shared computation done.** `parametric` stays on by default. Since
  E3 it wins three of eight accepted titles with results flatter than `flatten`'s, so making it
  opt-in would change those answers for the worse. The recomputation half is done: `analyse`
  finds the mix plateau once (it asked twice), and `run` hands every `_judge` the judged band
  `analyse` already found. Honest size: a mean spectrum is 0.12 s, so this saves under a
  second on a 70-170 s run; it is done for one source of truth, not for speed. Exact: probe
  at `--tol 0` unchanged, Bugonia's full record byte-identical.
* **Overshoot past the goal — checked, no change.** Every accepted filter pushes some point
  past both its start and the goal band, by 0.4-5.3 dB: smooth shelves lift the narrow content
  spikes that sit where they act (Bugonia's 8 Hz spike, +7 → +12 dB; Black Bag's 40-50 Hz
  spikes). Those spikes are content, so restoring the low end lifts them too. The existing
  overshoot check (a ceiling at the higher of start and goal, plus 3 dB and half the input's
  roughness) sits 7-11 dB above every curve and trips on none. Swapping its allowance for the
  title's own ripple would move that ceiling up on some titles and down on others and reject
  nothing. Left as it is: it guards against gross errors, and what matters for spikes is
  clipping.
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
* **T8 — a floor rule for the tracking floor's spread: checked, not adopted (2026-09-30).**
  Priority 7 asked for a floor rule that respects the correlation's uncertainty. Two rules came
  from the plan's own suggestions. Each was measured on the 11 titles
  (`tools/experiments/t8_floor_rules.py`, now kept); the bound rule was also built into
  `diagnose` and run through the whole regression workflow.
  * **Stop only where a band fails with confidence** (the upper bound, 95%, below 0.5). This
    tracks through bands whose best estimate says they are not tracked: Black Bag's floor goes
    from 25.1 to 4.4 Hz, and 28 Years Later tracks to the bottom through bands at 0.43-0.47.
    That licenses boost on missing evidence. Rejected without building it.
  * **Continue only while a band tracks with confidence** (`confident_tracking`: the
    correlation less `confidence_z` = 1.645 block-bootstrap standard errors must clear 0.5;
    resampled by contiguous runs of live samples, as the ceiling resamples runs of frames, so
    no block length is asserted; stored as the tracking curve, so a channel's restoration
    allowance used it too). Built and checked:
    * **Floors** (probe): 28 Years Later 20.5 → 29.0 Hz (the plateau's own edge), Alto Knights
      12.8 → 18.0, Black Bag 25.1 → 35.5, Bugonia 6.4 → 12.8, Send Help none → 4.3; the
      other six unchanged. Targets moved on 8 titles.
    * **Real runs** of the 8, against their baseline records: every title that accepted
      still accepts. Caught Stealing, Obsession, Send Help and Hulk publish the same
      corrected curve; Black Bag (+9.0 → +7.3 dB, within about 2 dB of the old curve) and
      Bugonia (+5.4 → +5.1) are close. **Alto Knights** keeps `flatten` but lifts less: at
      10 Hz −2.4 becomes −9.5 dB, and at 5 Hz −8.9 becomes −15.1. **28 Years Later** switches
      from `parametric` (+6.6 dB) to a `flatten` of +1.9 dB that leaves 16 Hz at −6.3 dB
      against −1.6. In both, the band that moved the floor has a point correlation of
      0.55-0.59 and a bound of 0.48-0.49.
    * **Synthetic protocol**, both seeds: identical selections and false acceptances. The
      corpus was not run, since the change was not adopted.
    * **Stability**, the question T8 asked: each rule re-applied to 400 resamples of the
      title's own runs, with the share landing on the modal floor. Point → bound: 28 Years
      Later 55% → 66%, Alto Knights 74 → 56, Ballad 66 → 97, Black Bag 68 → 48, Bugonia 51 →
      70, Obsession 97 → 65, Send Help 84 → 50 (the other four are 100% either way). Any
      threshold has marginal bands. A confidence bound only moves the threshold, so the coin
      flip lands on different bands, and more often below the plateau.
  * **Bagged floor** (the median of the resampled floors). Equal to the point floor on every
    title, so it would change nothing here while adding a bootstrap to every band.
  * **Decision:** no code change. The instability is real, but on every title the point rule
    lands on the floor its own resamples pick most often. The rule that addressed the spread
    cost correction without making the floor any steadier. The baseline records and the stage
    cache are untouched: the check ran in a scratch worktree.
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

## Original review findings and proposed checks

These are the original review questions, not current defect claims or assigned work.


Effort: S = a day or less, M = a few days. "TODO n" is the item's former number in `TODO.md`.

### Evidence and decision quality

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **E2** | **The false-accept rate is measured on four development negatives** *(verified)*. One of four is falsely accepted; four held-out show none; there is no interval on either. Absorbs TODO 10 and the parametric-path note on calibrating scene segmentation against a false-positive rate. | Build a negative corpus of 50 or more constructed cases across the track shapes below; report the false-accept rate with a Clopper-Pearson interval, per shape. Gate a scheduled test on the interval's *upper* bound. Real tracks supply content, the harness supplies ground truth (see "Variants"). | M |
| **E3** | **Selection rewards ambition, and is unstable** *(verified; observed)*. `Report.accepted` ranks by departure from the requested (flat) shape, so the least-clipped, most-boosting candidate wins even when its support is weakest. Absorbs TODO 6, which asks for a written decision either way. **Observed:** on 28 Years Later, HEAD selects `parametric` (+19.5 dB shelf at 23.6 Hz with a −7 dB peak at 38 Hz, recovered fraction 0.99) over a passing `flatten` (+6.1 dB, recovered 0.86), on a spread difference of 0.6 dB (11.6 vs 12.2). The designer server's older build shipped the `flatten` answer for the same title. A 0.6 dB shape margin chose a filter three times as large. `parametric` also passes with a recovered fraction above 1 on Send Help (1.54): it boosts past the measured deficit. | Re-rank passing candidates by support (`correction_support_score` or `recovered_fraction`) before shape, and treat any recovered fraction above 1 as a failure, not a ranking input. Also a stability check: the accepted strategy and peak gain must not move when the ranking margin is under `ranking_tie_db` plus the fit residual. Pass: on the negative corpus, the selected candidate's recovered fraction does not exceed what the injected truth licenses; on real tracks compare with `compare_verdicts.py` and review every changed decision by eye (28 Years Later first). Either outcome is written down here. | S |
| **E5** | **Two mechanisms for one job** *(verified that both exist; redundancy is hypothesis)*. `flatten` holds its boost flat below the tracking floor *and* prices by contrast. If the ceiling already zeroes those bins the hold is dead code; if it does not, the ceiling is not doing what it claims. | Ablate the hold. Pass: verdicts unchanged means delete it; verdicts changed means find which bins the ceiling let through and why. | S |
| **E6** | **The ceiling measures dynamic range, not missing content** *(verified, acknowledged in AGENTS.md; observed)*. A naturally drooping mix with strong scene-to-scene contrast is licensed up to its plateau. **Observed:** Send Help (+13.1 dB) and Obsession (+28.2 dB) are accepted with `shaping_fraction` 1.00 and 1.02: all of the correction sits below the level-invariance floor (22.7 and 24.2 Hz), with confidence 0.94 and 0.92. Neither is known to be wrong, but this is exactly the shape E6 describes, and nothing in the response tells a reviewer so. | Not fixable from programme audio alone (see AGENTS.md's "preference shaping"). The check is to *quantify* it: false-accept rate on natural-droop variants (E2) reported separately, and surfaced in the report so a reader can see when a title looks like that shape. A `shaping_fraction` near 1 should reach the designer response as a first-class warning, not a commentary number. | M |
| **E7** | **Extraction's scene and reference bands are fixed constants** *(verified; effect observed)*. `ExtractionParams.scene_band_hz = (10, 60)` picks loud frames, and `reference_band_hz = (60, 120)` picks quiet ones, for every title and every channel. That is the fixed-band mistake the principles forbid, sitting under the boost ceiling. **Observed:** on Dossier 137, whose mains are filtered at 28-42 Hz, the 10-60 Hz scene band is mostly stopband, and only 260 of 13,597 mix frames qualify as loud. | Derive both bands from the subject's own plateau (the scene band ends at, and the reference band is, the plateau). Pass: loud-frame counts rise on Dossier-shaped titles and no accepted boost grows beyond what the old ceiling licensed on the other eight. | S |
| **E8** | **Digital silence yields near-infinite contrast** *(observed)*. Where a channel's quiet frames are exact zeros, the median margin reads about 2,900 dB (the `1e-300` log floor). Seen on 4 of 9 real titles: LFE on Black Bag, Send Help and Bugonia; LFE, Ls and Rs on Dossier 137. Frame counts also go wrong: Dossier's Ls/Rs report 7,866 of 13,597 frames "loud". `boost_allowance` for such a channel is then bounded only by `restore_caps_db` and the mix-level pricing. No verdict is yet known to depend on it. | Treat exact-zero frames as absent, not quiet (exclude them from the quiet percentile, and mark a channel with too few non-silent frames unavailable). Pass: no channel margin above the extraction's dynamic range; verdicts unchanged, or each change explained. | S |
| **E9** | **Nothing measures boost the published cascade delivers beyond the evidence ceiling** *(verified that it is unmeasured; size unknown)*. `priced_by_evidence` caps the *target*; the fit only approximates it, and the ceiling is enforced on the cascade itself only below the judged band, and only with `--content-edge`. A cascade can exceed the licensed boost between grid points, across a hole in the ceiling (E4) or inside an exclusion, and no record says so. | Record-only first: on the exact published, quantised device response, record the largest excess over the ceiling, its frequency, its contiguous width in octaves, the integrated positive excess, and excess inside exclusions separately. Bins below the analysis range are unmeasured, not zero allowance. Audit the nine titles, the injected variants and the corpus. Any gate or fit constraint is a separate decision change with its own corpus numbers; a biquad cannot always realise zero at an isolated bin inside positive gain, so a gate needs an explicit realisation allowance, not the level tolerance borrowed. Pass: the record carries it and the audit is written down here. | S |

### Target construction and judging: consistency

| ID | Finding | Check and pass criterion | Effort |
| --- | --- | --- | --- |
| **T1** | **`counterfactual` ignores the playback model** *(verified)*. It re-sums with the module constants `MAIN_GAIN` and `LFE_GAIN`; verification and headroom use `params.playback`, which the CLI can change. | Unit test: changing `--lfe-gain-db` or `--main-gain-db` must change the counterfactual target. Identical at defaults, so exact-preserving. | S |
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
