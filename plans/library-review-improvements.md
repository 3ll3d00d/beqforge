# Improvements from the library decline review

**Proposal, not built; for beqforge to assess** (from beqdesigner's full-library run, 19 October 2026; TODO row 29).

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
