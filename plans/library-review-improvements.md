# Improvements from the library decline review

**Proposal, assessed and being built (see [Outcomes](#outcomes))** (from beqdesigner's full-library run, 19 October 2026; TODO row 29).

beqdesigner designed its whole JRiver library (1,287 titles) with beqforge 0.2.3 to 0.2.5. Every one of the 279
declines was reviewed against the run record (where one exists), the material and the community BEQ catalogue. 217
are genuine (old, quiet, stereo or dialogue-led mixes with nothing to restore), 29 are mono titles waiting on a policy
decision (beqdesigner's F3/F4, analysed separately), 10 are the documented steep-filter limitation, and the rest are
below, grouped by what would change them and in the order I would take them.

Where to look: queue entries `/media/beq/queue/<id>.json` (the decline message and the designer build), run records
`/media/beq/work/records/<record>` (designs from the image only; the Windows exe kept none, see TODO 27), the ledger
`/media/beq/triage/ledger.jsonl` (one verdict per decline, with evidence), and `/media/beq/triage/findings.md` (F1-F10,
O1, O2 in full). "Community BEQ" means a published BEQ for the same title in the catalogue: evidence that people hear a
loss, never a target.

## 1. An unmeasured tracking floor still reported as a measurement (F2, part 2; live on 0.2.5)

0.2.2 (`73a4deb`) fixed diagnosis losing a mix plateau at the band top. The second half of F2 is still there: when no
plateau is found, `_temporal_evidence` returns no strata and `noise_floor = band top` as a placeholder, and the plateau
blocker reports it as "tracking stops at 200.0 Hz" / "real bass content down to 200.0 Hz".

| Title | Id | Record | Community BEQ |
|---|---|---|---|
| FLOW (2024), 7.1 | `jriver-18bd9f7c1e48-2138016` | `designer-613deba0e48db872` | remixmark x2, ~+35 dB |
| Before the Devil Knows You're Dead (2007), 5.1 | `-1959276` | exe, none | mobe1969, ~+18 dB |
| Blink Twice (2024), 5.1 | `-2042567` | exe, none | kaelaria, remixmark, mikejl, +17..+21 dB |
| This Happy Breed (1944), stereo | `-2276057` | `designer-02b6c226963ec225` | none (outcome right, wording wrong) |

Proposal: require a measured floor before the blocker speaks, and find out why these three modern mixes have no
plateau at all (FLOW's record shows `strata NONE`). The earlier counterfactual tooling is in
`/media/beq/triage/scripts/counterfactual.py`.

## 2. A near-miss over-lift rejects the whole design (F9)

Seven declines fail first because flatten "lifts X Hz to +N dB, M dB above anything the material or the requested
shape supports there". The check is right to refuse boosting what is not content, but the response is all or nothing:
a candidate that overshoots the support ceiling by a fraction of a dB at one frequency is discarded with everything it
got right.

| Title | Over by | Id | Record | Community BEQ |
|---|---|---|---|---|
| Boyz n the Hood (1991) | 0.3 dB at 8.1 Hz | `-829682` | `designer-5e3281d9eba1819b` (exe) | mobe1969 |
| Christine (1983) | 0.4 dB at 31 Hz | `-2159569` | none | aron7awol, mobe1969 |
| Spirited Away (2001) | 1.9 dB at 10 Hz | `-188300` | none | mobe1969, halcyon888 x2, ~+10 dB |
| Crazy Heart (2009) | 2.6 dB at 7.1 Hz | `-380425` | none | none |
| Amy (2015) | 2.9 dB at 36.6 Hz | `-376080` | `designer-228ca118f5ab07d3` | none |
| Drive (2011) | 4.2 dB at 4.6 Hz | `-120004` | `designer-f63810790546d8fe` | mobe1969, halcyon888, mikejl |
| Alien Resurrection (1997) | 5.1 dB at 19.5 Hz | `-283738` | none | five, ~+25 dB |

Proposal: when a candidate fails only the support ceiling, refit it constrained to the ceiling (or reduce the
offending section's gain until it fits) and judge the result, rather than rejecting. Gate on the negative corpus: the
ceiling exists to stop false acceptances, and a constrained fit must not become a way round it.

## 3. The tilt check rejects modest corrections (F10)

Five declines fail first on "tilts X dB/oct where Y was intended, outside the 2 dB/oct allowed".

| Title | Tilt vs intended | Id | Record | Community BEQ |
|---|---|---|---|---|
| The Smurfs (2011) | -2.6 vs -0.3 | `-223768` | `designer-0711998c0c9367dc` | mobe1969 x2, ~+9 dB |
| Despicable Me 3 (2017) | +2.3 vs 0.0 | `-723521` | `designer-27fc8d43c7c4d6de` | aron7awol, mobe1969, +4..+6 dB |
| The Quiet Girl (2022) | +3.2 vs +1.0 | `-2019688` | `designer-7531617d5f111652` | none |
| Blood Simple (1985) | +4.2 vs 0.0 | `-203775` | `designer-3c7b8904281ba41f` | none |
| Synecdoche, New York (2008) | -4.6 vs -0.5 | `-2186889` | `designer-c65d1a05f013faad` | none |

Proposal: check the band the tilt is measured over. Despicable Me 3 was an F1 title (the LFE knee counted as ripple)
before 0.2.3 and now fails tilt instead, which suggests the tilt fit may also span the sub crossover knee.

## 4. The texture retune (TODO 26; its trigger, the end of the library review, is met)

| Title | Shortfall vs swing (band) | Id | Record | Community BEQ |
|---|---|---|---|---|
| Changeling (2008) | 10.0 vs 10.2 (26-200) | `-121241` | `designer-1c23cc39576c5575` | mobe1969, +12 dB |
| Mirai (2018) | 6.0 vs 6.5 (32-200) | `-909817` | exe | none |
| True Grit (2010) | 4.3 vs 5.4 (14-200) | `-203242` | exe | mobe1969, ~+5 dB |
| Fame (1980) | 10.6 vs 11.7 (34-200) | `-188099` | exe | (also F5-shaped) |
| Carrie (1976) | 8.4 vs 9.9 (10-200) | `-1773161` | exe | none |
| Song of the Sea (2014) | 5.8 vs 9.7 (18-200) | `-850598` | `designer-ebbd6f248e7c2b64` | remixmark, ~+11 dB |
| Parasite (2019), two copies | 4.0 vs 6.8; 4.2 vs 7.4 | `-1877833`, `-1877834` | `designer-f6bd00fcbdc06dff`, `designer-c79154373bfdb99f` | aron7awol, mobe1969 (small) |
| The Prestige (2006) | 3.7 vs 9.8 (10-200) | `-1707041` | exe | aron7awol, mobe1969, +6..+10 dB |

The first four miss by 0.2 to 1.1 dB. The library holds no known negatives, so it can show wrong declines but not
measure false acceptances: any retune still needs the corpus or the fresh E10 set.

## 5. The absolute 45 dB scene margin (F6)

| Title | Loudest frame over the floor | Id | Community BEQ |
|---|---|---|---|
| Blade II (2002) | 26.9 dB (continuous LFE bed) | `-191850` | ~+28 dB at 19 Hz |
| Jason Bourne (2016) | 42.2 dB | `-1706551` | aron7awol, mobe1969, ~+16 dB |
| Sunshine (2007) | 44.1 dB | `-454982` (`designer-4291a12bcbc97cb5`) | three, +10..+20 dB |
| Do the Right Thing (1989) | 1 frame of 14,051 clears it | `-235569` | +20..+27 dB |

Proposal: a margin measured per title (the distribution of 10-60 Hz frame levels) instead of a constant; beqforge's
own principles already warn against a constant standing in for a measurement.

## 6. A dialogue-band reference hides LFE bass (F5)

A Real Pain (2024, `-2100190`, `designer-4b0f81bb77f26ee5`) and Eastern Promises (2007, `-1838231`): the plateau sits
above the crossover and is carried by FC (53%, 64%), tracking against it stops at 71 and 52 Hz, and the judged band
never reaches the loss. Community BEQs +10..+21 dB. Fame and The Rainmaker share the shape. Proposal: take the tracking
reference from the band the sub plays; needs a counterfactual first.

## 7. A plateau that starts at the filter floor (new, one title)

So I Married an Axe Murderer (1993, 4.1, `-188163`, `designer-a3a8c6af7ab7c9f8`): plateau 36.7-106.8 Hz, filter floor
36.6 Hz, so no bin below the plateau is licensed; community BEQ 4x low shelf 23 Hz +8 dB plus a peak. Probably the same
family as 6.

## 8. Smaller items

- **O1, DC offset and its steps** (Desperately Seeking Susan): detect per-channel DC and steps, add a DC-blocking
  high-pass, count the cascade's 0 Hz gain in headroom. Rare, but a correction would ship audible thumps; the user asked
  for it to be handled.
- **O2, an infrasonic plateau as the reference** (7 titles, outcome right so far): refuse a plateau below
  `lowest_frequency_hz` as a reference.
- **Different answers by machine**: the library runs on the image (Linux) and the exe (Windows) at once. With
  counterfactual and parametric able to land on a different optimum per processor (0.2.6's golden), a title's design
  depends on which endpoint took it. Worth an option that makes the optimisers deterministic across hardware, or
  guidance to pin those strategies to one machine.

## 9. A design fills a mastering hum notch (F11, added after the first assessment)

Found while checking mono titles with their channel sent as FC (beqdesigner F4, now decided: recover content whatever
the channel count). A narrow notch at mains frequency is noise removed on purpose, not a rolloff; boosting it back
restores the hum along with the programme left in it.

| Title | Material at the frequency (vs ±2-8 Hz) | Design | Id |
|---|---|---|---|
| Bonnie and Clyde (1967), mono | -10.9 dB at 60 Hz, -9.6 dB at 120 Hz | PEQ 62.5 Hz +13.2 Q 5.96; PEQ 121.2 Hz +11.8 Q 3.54 | `jriver-18bd9f7c1e48-1180964` (v0.2.8 with FC; not deployed) |
| Butch Cassidy and the Sundance Kid (1969) | -8.6 dB at 61 Hz | PEQ 61.2 Hz +20.9 Q 5.85 | in the queue, pending review |
| The Birds (1963) | -10.2 dB at 120 Hz | PEQ 119.5 Hz +7.9 Q 5.95 | in the queue, pending review |
| White Heat (1949), mono | -10.3 dB at 100 Hz | low shelf 91.9 Hz +21.8 Q 5.57 beside it (unclear) | `-1818989` (v0.2.8 with FC) |

Measured with Welch, 0.5 Hz bins, on each title's 1 kHz `mono.wav`. Eleven other designs boost within 4 Hz of 50/60 Hz
or a harmonic without a notch in the material, so the guard must look at the material, not the frequency alone.
`b126055` already skips mains-hum notches in the ripple measure; the target and the fit do not. Proposal: treat a narrow
notch at 50/60 Hz or a harmonic as excluded from the target (as `--exclude` does by hand), so nothing is lifted into it.

## Not here

The mono policy is decided on the beqdesigner side: recover content whatever the channel count, so mono titles are sent
their one channel as FC (beqforge needs no change; it blocks only on a missing decomposition). At v0.2.8, 7 of 28 design
and 21 decline on content grounds. The steep-filter default stays with TODO 5/6.

## Outcomes

Assessed with beqdesigner (20 October 2026). Agreed: four fixes (items 1, 9, 2 and the drift scoring behind most of
item 3), the small items O1 and O2, then research on 1b/6/7, the texture retune (4), the scene margin (5) and row 28.
Each fix lands as its own commit with its own regression check against the commit before it.

### Fix 1: an unmeasured tracking floor is no longer reported as a measurement (item 1)

`Diagnosis.tracking_measured` is false when the mix has no plateau (or the material is shorter than one Welch
segment), so `noise_floor_hz` holds only the band-top placeholder. The summary now says where real bass content stops
was not measured, and the sub-band plateau blocker says tracking below the flat region could not be measured instead
of "tracking stops at 200.0 Hz". The flag is carried in the stage cache and the run record. Wording only: no decision
reads it, the decline prefix is unchanged, and `DESIGN_VERSION` stays at 4.

Regression: probe snapshot at HEAD against this change, `--tol 0`, analysis recomputed: 11 of 11 titles unchanged.
No refit probe or protocol run, since nothing the fit or the judge sees has changed.

Why FLOW has no plateau at all (its 40-150 Hz passband wanders 6-7 dB, so no window qualifies) is research item 1b,
not part of this fix.

### Fix 2: the fit is scored on the published parameters (item 3, and the drift behind it)

`_fit_structure` scored its residual and the device's coefficient rounding on the optimiser's unrounded floats, but
the filter is published with frequency rounded to 0.01 Hz, gain to 0.001 dB and Q to 0.0001. On a steep cascade the
device's rounding is very sensitive to those last digits, so what the fit scored was a point the published filter never
sat at: across 923 library records the published drift exceeded what was scored by more than 0.5 dB on 478 candidates,
more than 1 dB on 253 and more than 2 dB on 90. The cost now rounds the parameters exactly as `publication_filters`
does before scoring them, and the cascade returned is the rounded one, so the residual reported is the residual of the
filter published (`test_the_fit_reports_the_residual_of_the_filter_it_publishes`). `accept.py`'s `max_drift_db`
docstring no longer claims the published filter's own rounding is 0.006-0.014 dB. `DESIGN_VERSION` 4 -> 5; the golden's
flatten answer moved (residual 0.631 -> 0.613 dB).

Regression, each against HEAD (`6af2b34`, which decides exactly as fix 1's commit does):

- Probe: 11 of 11 titles unchanged at tol 0 (analysis untouched, as expected).
- Refit probe (11 titles, 43 injected variants): 53 of 54 move, as any fitter change does. Verdict flips 22 pass->fail
  and 27 fail->pass. Real titles: **Bugonia loses its design in both modes** (flatten -> none): its one shelf
  (0.559 dB) never met the 0.5 dB target, so the least-exposed cascade in the budget is taken, and honestly scored that
  is now a shelf plus a peak (0.509 dB), which the judge rejects for correcting only down to 8.1 Hz while content
  continues to 6.4 Hz. That is the fit-band/judged-band mismatch fix 4 addresses; recheck Bugonia there. Alto Knights
  counterfactual/25dB fails a cliff check but the winner is unchanged. Injected variants, scored against truth: default
  mode designs 21 -> 20 of 43 (Black Bag BW12 @ 30 Hz declines; its old design missed by 9.0 dB median), median
  |shortfall| 0.7 -> 0.8 dB on the 20 in common; content-edge mode designs 43 of 43 both ways, median |shortfall|
  0.7 -> 0.5 dB, 16 better and 8 worse by more than 0.2 dB.
- Protocol seeds 101 and 947: no false acceptance gained or lost (`natural_bass_light` was and stays one on both seeds;
  on 947 it is now counterfactual/35dB, not parametric); `varying_filtered` recovery 17.77 -> 18.05 and 13.55 -> 13.48 dB.
- Negative corpus, seeds 1-9, against a run at HEAD (the committed `negative_corpus.json` is 32 designer commits old):
  gated negatives 0/45 both, gate PASS; `natural_droop` 4/9 both; filtered true positives 7 -> 6, the one lost being
  filtered/1, whose HEAD pick (parametric) recovered at 15.6 dB RMS; median recovery 1.27 -> 1.16 dB RMS.
- The library titles that motivated it, run from beqdesigner's extracted material at HEAD and with this change: The
  Quiet Girl reproduces its decline at HEAD (tilt +3.2 against +1.0) and designs with it (flatten, low shelf 14.3 Hz
  +4.29 dB, peak 15.3 Hz +1.71 dB). The Smurfs and Despicable Me 3 already design at HEAD on this machine (their library
  declines came from 0.2.3-0.2.5, partly on the Windows exe; see row 28) and still design with it.

### Fix 3: a mains-hum notch is filled, not restored (item 9, F11)

`hum_notches` tests each 50/60 Hz harmonic on its own, as `mains_hum_notches` tests a comb, but about the surround's
log-frequency trend rather than its floor: a notch where the passband is falling away (Bonnie and Clyde's 16 dB notch
at 120 Hz, White Heat's 15 dB one at 100 Hz) scored 0.57 and 0.61 against the floor and was missed. `fill_hum_notches`
replaces each notch with that trend in the spectrum `_flat_deficit` reads, so the reference, the deficit, the knee and
the judged band all see the programme beside the notch, and every strategy, capped by that deficit, asks there for what
it asks beside it. Filled rather than excluded: an exclusion asks for zero correction (a dip inside a boost) and one in
the judged band withholds the run. `passband_ripple_db` still reads the raw spectrum with its comb rule, unchanged.
Measured over 20 real titles to 250 Hz: every notch the review listed qualifies (1.26-2.91 of the surround's swing),
none on the 11 baseline titles does (at most 0.80), and Butch Cassidy's 2 dB dips at 180 and 240 Hz do, which filling
moves by 2 dB. Shares `DESIGN_VERSION` 5 with fix 2, neither released.

Regression against fix 2's commit: probe 11 of 11 unchanged at tol 0; refit probe 0 of 54 titles moved; protocol seeds
101 and 947 and the negative corpus identical case for case. On beqdesigner's extracted material, before -> after:

| Title | Before (winner) | After (winner) |
|---|---|---|
| Bonnie and Clyde | flatten with peaks at 62.3 Hz +11.4 dB Q 4.8 and 120.1 Hz +12.5 dB Q 5.8 | flatten with no section at a harmonic |
| The Birds | flatten with a peak at 118.2 Hz +8.6 dB Q 5.7 | flatten, no section at a harmonic |
| White Heat | flatten with a peak at 101.1 Hz +11.0 dB Q 5.8 | flatten now fails a cliff; counterfactual/45dB (unchanged) wins |
| A Star Is Born | flatten | counterfactual/45dB; neither places a narrow section at 60 or 120 Hz |
| Butch Cassidy, Glory | flatten | unchanged |

Bonnie and Clyde's counterfactual candidates still carry a peak near 61 Hz (+5-6 dB); their targets were unchanged by
the fill, so it comes from the restored channel's shape below the deficit cap, not from the notch. Not the winner.

### Fix 4: the fitter is bounded by the judge's over-lift bar (item 2, F9)

The judge's over-lift check guards from the bottom of the design grid to the top of the judged band, below the band
the fit's residual is scored on, and at a narrow peak in the material lets the corrected curve rise only the level
tolerance plus half the material's roughness above it. The fitter never saw that bar, so a smooth boost lifted the
peak and the judge rejected the whole design. The bar is now one function, `accept.overlift_bar_db`, used by `assess`
unchanged and by `pipeline.overlift_allowance`, which measures it once per run on the unfiltered sub feed (it depends
on the material and the judged band, never on a filter). `_fit_structure` takes the allowance as a hard bound on the
quantised cascade's lift: every cascade under it ranks before every cascade over it, and the residual returned is the
larger of fit error and overshoot. `tools/experiments/refit_probe.py` passes it too. Parametric's own fit is not
bounded (it is fitted inside `design`). Shares the unreleased `DESIGN_VERSION` 5; the golden's flatten answer moved.

The bound's form was decided on the seven library titles the check rejected, from beqdesigner's extracted material,
at fix 3's commit, with the overshoot scored as one more error term, and as a hard bound:

| Title | Before | Error term | Hard bound |
|---|---|---|---|
| Crazy Heart | flatten over by 2.1 dB (counterfactual/25dB won) | over by 1.2 | **flatten passes and wins** |
| Spirited Away | over by 1.3 | over by 0.7 | not over; fails turnover |
| Alien Resurrection | over by 5.7 | over by 2.7, and tilt | not over; fails tilt |
| Amy | over by 3.5 | over by 1.4 | over by 0.4 |
| Drive | over by 3.6 | over by 3.0 | over by 2.1 |
| Boyz n the Hood, Christine | design | unchanged | unchanged |

As an error term the optimiser balances fit error against overshoot (1.9 dB each on a test target) and the judge,
which rejects any overshoot, still rejects it: nothing rescued. The hard bound rescues Crazy Heart's flatten and turns
two over-lifts into tilt and turnover failures, shapes a smooth cascade cannot make rather than near misses. Drive's
4.6 Hz peak sits just below a large boost starting at 5 Hz and no smooth cascade separates them. Amy's 0.4 dB is the
judge measuring a Welch spectrum of the corrected waveform, where the boost beside the narrow peak leaks into its bin,
while the fit scores the filter's exact response.

Regression against fix 3's commit:

- Probe: 11 of 11 unchanged at tol 0.
- Refit probe: 53 of 54 move (the bound changes the optimiser's path even where it never binds). Verdict flips: default
  5 pass->fail, 6 fail->pass; content-edge 12 and 17. Real titles: Caught Stealing's winner flatten -> parametric in
  both modes, shipping the same filter (flatten had matched parametric exactly and now fits 0.405 against 0.398);
  Bugonia still declines — its failure is the coverage check below 8.1 Hz, not the over-lift guard, so fix 4 was never
  going to reach it (corrected from fix 2's note). Injected variants: default designs 20 of 43 both ways, median
  |shortfall| 0.80 -> 0.50 dB (5 better, 4 worse by 0.2 dB); content-edge 43 of 43 both ways, 0.50 -> 0.50 (10 better,
  13 worse).
- Protocol: seed 101 identical but `varying_filtered` recovery 18.05 -> 17.98 dB; seed 947 identical but
  `natural_bass_light` (a false acceptance before and after) selected parametric rather than counterfactual/35dB.
- Negative corpus, seeds 1-9: gated negatives 0/45, gate PASS; filtered true positives 6/9 both, median recovery
  1.16 -> 0.90 dB RMS; `natural_droop` (reported, not gated) 4/9 -> 5/9, seed 7 now accepted (counterfactual/25dB, peak
  boost 22.5 dB).

### O2: an infrasonic plateau is refused as the reference

A reference is what a correction restores towards, so `analyse` now requires the mix plateau to start at least
`AcceptParams.min_judge_octaves` above `verify_floor_hz` (one octave above 5 Hz, so 10 Hz). Starting lower, there is
no low end beneath it to restore, and the run declines up front as "nothing worth correcting below the mix's plateau"
(`within_goal_tolerance`), without measuring texture or shortfall against it. No new constant and no contract change.
`lowest_frequency_hz` alone, as proposed, would have caught none of them: every such plateau extends above 5 Hz.

First written as `no_usable_plateau`, which the golden test's unfiltered case showed was wrong: an unfiltered mix,
flat across the band, also has a plateau starting at 4 Hz, as do many of the corpus's negatives (broadband, rumble and
varying-source plateaus from 4.0 Hz up to anywhere between 7 and 200 Hz). Neither the infrasonic plateau nor a whole
flat passband is unusable; what both lack is any low end beneath them to restore, which is the reason now given.

Plateau starts measured on 34 titles at hand: Don't Bother to Knock and Ace in the Hole 4.0, Sunset Boulevard 5.2, The
Favourite 6.5, Evil Does Not Exist 8.7; then All About Eve 12.2 (kept; it declines on loud events anyway), and every
other real title 15.0 or above.

Regression against fix 4's commit, run with the first wording (the decision is the same; only the reason text and code
differ): probe 11 of 11 unchanged, refit probe 0 of 54 moved, protocol seeds 101 and 947 and the negative corpus
identical case for case. The six titles all decline before and after. Don't Bother to Knock and The Favourite change
reason from `within_programme_ripple` to `within_goal_tolerance`; Ace in the Hole, Sunset Boulevard and Evil Does Not
Exist lead with an earlier blocker (loud events, positive correction) and keep their code, now with the plateau stated;
All About Eve is unchanged. The golden's unfiltered case moves from `within_programme_ripple` to
`within_goal_tolerance`. A decline reason is an answer, so this shares the unreleased `DESIGN_VERSION` 5.

### O1: a DC offset and its steps (findings; report-only detection to follow)

Measured on Desperately Seeking Susan before building anything. Headroom already counts the offset: `measure_headroom`
filters the sub feed with the device's full transfer, 0 Hz included, so a lifted static offset is in the measured
peak. A DC-blocking high-pass would not stop the thumps: at the steps FR's 4-20 Hz transient stands 15-22 dB above FL's
with no blocker and with a second-order one at 1, 3 or 5 Hz alike, since a step's energy runs far above any blocker's
corner. What is left is detecting the steps and saying so. Decided with beqforge's user: report-only, no answer change.

Built as `beqforge/dc_offset.py`, report-only. `analyse` adds an evidence note per channel found, so it reaches the
commentary, a decline message and the run record; no decision reads it and no answer moves. A channel is reported when
three things hold, with no dB constant: its slow DC level (the median of per-second means over 31 s) is persistently
large enough that a step in it would produce a 4-20 Hz transient above the 90th percentile of the channel's own
per-second peak in that band; a change in that level produces such a transient; and, with other channels to compare,
near the step this channel's band level stands out of every other channel's. Each test answers a false alarm the
prototype raised: against the median, every sparse channel (an LFE silent most of the time) reported drifts as steps;
without the persistent offset, every LFE stood out of the other channels, since it alone carries infrasonic content;
the cross-channel test separates a step in one channel from programme bass arriving in several at once.

On 34 real titles only Desperately Seeking Susan's FR is reported: a -48 dBFS offset stepping 32 times, the largest
transient 16.4 dB above the programme there (two of the review's seven times match to within ten seconds; the slow
level also follows drift between edits, so it finds more). Nothing on the 63 corpus cases. About 0.1-0.4 s a title.
Probe 11 of 11 unchanged; no protocol or corpus run, since nothing a decision reads has changed.
