# Texture yardstick: measure it in the band the sub plays

**Status: implemented (17 October 2026), as a cubic detrend over the unchanged band, not as
either width-normalised measure below.** See [Outcome](#outcome-17-october-2026). The rest of
this document is the original handoff, from the beqdesigner library design run (October
2026), where every decline of the full JRiver library (~1,290 films) is being reviewed. The
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

## Outcome (17 October 2026)

### Neither width-normalised form separates the corpus

Both forms were scored offline before any code changed. Each candidate measured the same
residual as `passband_ripple_db`, over the full band and capped at the sub edge, on all 63
corpus cases (seeds 1-9), the 11 baseline titles, the 43 variants and the 8 library titles
above. A scaled spread took the corpus median of crest-to-trough/spread over the full band as
its scale. Shortfall/yardstick, where above 1 is accepted:

| Sub-band yardstick | Worst gated negative | 9 | Beauty and the Beast | Despicable Me 3 |
| --- | --- | --- | --- | --- |
| crest-to-trough (the patch) | 1.11 (`sparse_dialogue/9`)\* | 1.22 | 1.20 | 1.39 |
| 4.79 x standard deviation | 1.05 (`broadband/5`)\* | 1.15 | 1.10 | 1.09 |
| 1.48 x 5th-95th percentile | 1.06 (`broadband/5`)\* | 1.33 | 0.99 | 1.12 |
| largest ¾-octave window | 1.11 (`sparse_dialogue/9`)\* | 1.14 | 1.13 | 1.30 |

\* Excluding `sparse_dialogue/5`, at 3.2-5.2x on every one. Its judged top is 77 Hz, so its
sub band is 0.06 octaves wide. A sub-band yardstick also needs a minimum width, which neither
form had.

The handoff's premise is only half right. `broadband/5`'s sub band is smoother in fact, not
just shorter: its standard deviation falls from 0.9 to 0.6 dB, and so does every
width-invariant statistic. A shorter band also lets the linear trend take up more of the slow
structure. No statistic over the sub band left a margin worth calling a separation.

### What was built: a cubic trend over the same band

The knee is a trend problem, not a band problem, so the band stays where the 1x boundary was
calibrated (judged top to `diagnose.band_hz[1]`), and only the mix's detrend changes.
`passband_ripple_db` takes `trend_degree` (1 by default). The mix's texture blocker passes
`MIX_TEXTURE_TREND_DEGREE` = 3. `channels_missing_low_end` keeps the line, as the handoff
advised.

The same study, full band, mix rule:

| Trend | Worst gated negative | Lowest real/filtered/variant | 9 | B&tB | CSL | DM3 | Carrie |
| --- | --- | --- | --- | --- | --- | --- | --- |
| line (before) | 0.77 | 1.01 (Incredible Hulk) | 0.71 | 0.98 | 0.98 | 0.62 | 0.82 |
| quadratic | 0.82 | 1.05 (Bugonia) | 1.21 | 1.00 | 1.06 | 1.31 | 0.86 |
| hinge at 80 Hz | 0.77 | 1.05 (Bugonia) | 1.00 | 1.01 | 1.08 | 1.14 | 0.87 |
| **cubic** | **0.76** | **1.08 (Bugonia)** | **2.79** | **1.11** | **1.06** | **1.43** | **0.85** |

The cubic is the only trend that widens the separation at both ends. Over all 125 items, it
changes the texture verdict on exactly four: 9, Beauty and the Beast (1991), Crazy, Stupid,
Love and Despicable Me 3. A cubic can raise a yardstick as well as lower it (`sparse_dialogue/9`
measures 5.54 dB about it against 5.24 about a line), but no verdict went that way. Battle: Los
Angeles (0.28) and Changeling (0.89) stay declined.

### Regression check

* **Probe** (11 baseline titles, default params): unchanged on every title.
* **Protocol**, seeds 101 and 947, before in a HEAD worktree (`a4b4d06`, the code of `fd9ae22`) and after: every decision,
  score and failure identical. The only difference is the ripple figure quoted in two
  `within_programme_ripple` notes per seed.
* **Negative corpus**, seeds 1-9: 0/45 false acceptances on the gated shapes, upper bound
  0.079 against 0.100, **pass**. All of `broadband/*` abstains. Ungated: `natural_droop` 4/9,
  `filtered` 7/9 true positives, median recovery 1.27 dB RMS. The committed
  `negative_corpus.json` is from an older revision (`4c6d5c3`), and 7 cases differ from it:
  5 in recovery or peak boost on accepted cascades, and `natural_droop/7`, now abstaining.
  None is this change: no corpus case's texture verdict moves under the cubic, and the
  blocker is all the change touches. The committed file was not refreshed.
* **Library titles**, real `designer.design` runs with the deployed request shape (bass
  management `lpf_fs` 80):

  | Title | Material digest | Accepted | Confidence |
  | --- | --- | --- | --- |
  | 9 (2009) | `c942feb4…`, matches the deployed request | `flatten`: LowShelf 13.0 Hz +6.4 dB Q 0.72 | 0.97 |
  | Beauty and the Beast (1991) | `8d98789b…` | LowShelf 13.8 Hz +2.4 dB, LowShelf 35.1 Hz +1.0 dB, PeakingEQ 24.4 Hz +4.6 dB | 0.95 |
  | Crazy, Stupid, Love | `df2456f6…` | `flatten`: LowShelf 34.5 Hz +10.0 dB Q 0.79, PeakingEQ 28.6 Hz −7.6 dB Q 2.07 | 0.93 |
  | Despicable Me 3 | `7cf1e523…` | LowShelf 28.2 Hz +1.6 dB, LowShelf 15.0 Hz +1.0 dB | 0.96 |

  9 is the correction the handoff expected, and Beauty and the Beast is the cascade the
  patch's second attempt found. Crazy, Stupid, Love's cascade looks odd until its corrected
  curve is checked: the average goes from a steep fall below about 25 Hz to flat at about
  −72 dB down to about 5 Hz. The cut shapes the shelf; it does not fight it.
* **Carrie stays declined**: an 8.4 dB shortfall against 9.9 dB of ripple about a cubic
  (10.3 about a line). Its judged band starts at 10 Hz, so its passband runs 4.3 octaves,
  and the texture there is broadband, not a knee. Shortening the band would accept it. Nothing
  measured here licenses doing that.

### Caveat: the degree is a choice made on this data

Degree 3 was picked from three degrees and a hinge after seeing the corpus and the library
ratios. That is a modelling choice informed by the corpus, so the completion criterion's E10
clause applies. Fresh validation should precede treating it as settled. The hinge at the
crossover is the one variant with no free choice (its bend is the playback crossover). It
leaves every corpus ratio as it was, but puts 9 at exactly 1.00x, so it does not fix the
reported title.
