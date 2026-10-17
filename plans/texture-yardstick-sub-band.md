# Texture yardstick: measure it in the band the sub plays

**Status: design, not built.** A handoff from the beqdesigner library design run (October
2026), where every decline of the full JRiver library (~1,290 films) is being reviewed. The
person who owns both projects asked for the width-normalised measure below to be tried. The
first two attempts, which only shorten the band, are in
[texture-yardstick-sub-band.patch](texture-yardstick-sub-band.patch); it applies to `main`
at `fd9ae22`. It fails the corpus gate, so it was not committed.

## The problem

`pipeline.passband_ripple_db` measures the programme's texture as the crest-to-trough swing
of the smoothed mean spectrum about its own linear log-frequency trend. It runs from the top
of the judged band to the **top of the analysis band** (`diagnose.band_hz[1]`, 200 Hz). If the
deepest low-end shortfall is no bigger than that swing, the title is declined
`within_programme_ripple`. `channels_missing_low_end` uses the same function for each
channel.

Above the sub crossover (80 Hz), the mix's shape is not texture the sub plays. In an
LFE-led 5.1 mix the level falls away where the LFE content ends (about 60-100 Hz). A linear
detrend cannot remove that knee, so it is counted as ripple and the yardstick gets bigger.
The rule's 1x boundary was calibrated on the negative corpus, which is two-channel synthetic
material with no LFE knee. That is why calibration did not catch this.

## Evidence

**9 (2009)**, 5.1 DTS-HD, LFE carries 77% of the plateau. Local rerun at v0.2.1, with the
material digest matching the deployed request:

| Yardstick band | Ripple | Shortfall | Outcome |
| --- | --- | --- | --- |
| 23-200 Hz (current) | 8.8 dB | 6.2 dB | declined `within_programme_ripple` |
| 23-80 Hz (crossover) | 5.1 dB | 6.2 dB | accepts `flatten`: LowShelf 13.0 Hz +6.4 dB Q 0.72, confidence 0.97 |

- The community BEQ (aron7awol) is 2x LowShelf 10 Hz +3.2 dB + LowShelf 27 Hz +2 dB: the same
  kind and size of correction.
- The level-invariance evidence supports a real filter: the loudness strata agree down to
  4.15 Hz, and content tracks all the way down.

Other titles declined this way in the run (shortfall vs the ripple capped at the crossover):

| Title | Shortfall | Capped ripple |
| --- | --- | --- |
| Beauty and the Beast (1991) | 11.7 dB | 9.74 dB |
| Carrie (1976) | 8.4 dB | 6.32 dB |
| Crazy, Stupid, Love (2011) | 10.8 dB | 4.06 dB |
| Despicable Me 3 (2017) | 4.3 dB | 3.1 dB |

Battle: Los Angeles and Changeling are not affected: their capped ripple still exceeds their
shortfall.

## What was tried (the patch)

1. **Capping both rules at the sub edge** (`min(crossover_hz, bus_lowpass_hz)`, the edge the
   plateau blocker already uses). Corpus: 1 false acceptance in 45 gated (`broadband/5`,
   `counterfactual/25dB`). The gate's upper bound is 0.118, above 0.100: **fail**. Through the
   per-channel rule, counterfactual targets also grew on Bugonia, Caught Stealing (peak
   4.3 -> 12.3 dB) and Incredible Hulk.
2. **Capping the mix rule only** (`in_sub_band=True`; each channel keeps the whole passband).
   The probe is unchanged on all 11 baseline titles, and the protocol is identical on both
   seeds. 9, Beauty and the Beast and Carrie are all accepted:
   - 9: LowShelf 13.0 Hz +6.4 dB
   - Beauty and the Beast: LowShelf 13.8 Hz +2.4 dB, LowShelf 35.1 Hz +1.0 dB, PeakingEQ 24.4 Hz +4.6 dB
   - Carrie: LowShelf 6.5 Hz +3.7 dB

   The corpus still fails: `flatten` now accepts `broadband/5` (peak boost 2.6 dB), 1/45,
   upper bound 0.118.

**Why the gate fails:** crest-to-trough is an extreme-value statistic, so it shrinks as the
band holds fewer bins, even on pure noise. The 1x boundary was earned with the 200 Hz band.
Shortening the band therefore lowers every title's yardstick, the genuine negatives'
included. Fixing the band is really a recalibration.

## Wanted: a width-normalised measure

Measure texture with a statistic that does not depend on how wide the band is. Then the band
can end at the sub edge without moving the 1x boundary the corpus set. Two candidate forms;
the owner of beqforge chooses:

- **A scaled robust spread.** Compute the residual about the trend as now, then take a spread
  that converges with bin count instead of growing with it (standard deviation, or an
  inter-percentile range such as 5th-95th). Scale it by the ratio of crest-to-trough to that
  spread, measured over the full 200 Hz band on the calibration titles. Then, on the band the
  rule was calibrated on, the yardstick stays in units of what the corpus measured, while a
  shorter band no longer shrinks it just by being shorter.
- **A fixed-width window.** Take crest-to-trough over a sliding window of fixed octave width,
  inside the judged-top-to-sub-edge band (the largest or the median of the windows), so every
  title is measured over the same width. Choose the window from the corpus, and fall back to
  the current measure where the band is narrower than one window.

Either way, keep what the docstring already relies on: the reference sits on the crests, so
the yardstick must still span the whole swing a shortfall is measured across; hum notches stay
excluded (`mains_hum_notches` still searches the whole passband, because below 80 Hz only one
harmonic remains); and when the judged band already reaches past the sub edge, the analysis
band is kept.

Decide separately whether the per-channel rule moves too. The first attempt shows that a
smaller yardstick there judged more channels short, so leaving it alone is the safer
default.

## Completion criteria

- `tools/negative_corpus.py`: false acceptances 0/45, gate pass, with `broadband/5` declined.
- `tools/validate_evidence.py` and the protocol: unchanged on both seeds; the probe unchanged
  on the 11 baseline titles, or each change explained.
- 9 (2009) accepted with a correction of the size above. Beauty and the Beast and Carrie
  accepted, or the reason they are not recorded.
- If the measure needs any constant fitted to the corpus, the fresh validation E10 asks for
  applies before it becomes the default.

## Repro

The library run's audio and scripts are on the beq share (`/media/beq`):

```sh
python -I /media/beq/triage/scripts/ripple_counterfactual.py <beqforge checkout> \
    "/media/beq/work/9 - audio 1" \
    c942feb4b5f22f680bb4fc8fc484d63afe92c4dc796b1c26701a07a5b93c5739 <out dir>
```

It reruns the title as deployed, then with the yardstick capped at the crossover, and checks
the material digest against the deployed request. The patch's
`tests/test_design_ripple_band.py` has a synthetic LFE-led source (noise with a knee at 70
Hz) that is a reasonable unit test for any replacement.
