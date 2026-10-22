# The playback contract: build the sub feed the caller describes (TODO row 1)

**Built 22 October 2026** (TODO row 1, `DESIGN_VERSION` 6). `designer-interface.md` §2's `bass_management` was read
for its crossover alone; the sub feed was always beqforge's own model. Now the feed is built as
the request describes it.

## What was wrong

`designer.design` replaced only `PlaybackParams.crossover_hz` with `lpf_fs`. Everything else
stayed beqforge's model: an LR4 low-pass on each main, the LFE unfiltered, a second LR4 on the
summed bus, and fixed gains of -20.2 dB on the mains and -10.2 dB on the LFE. The clipping line
then said "with your bass management" while quoting those fixed gains.

beqdesigner's own chain (`model/signal.py`, `BassManagedSignalData.sum`) is different:

* `lpf_position` "Before" applies one LR4 at `lpf_fs` to *every* channel, LFE included, before
  summing; "After" applies one to the sum; "Off" applies none. Linear and identical in every
  channel, "Before" and "After" are the same feed.
* `headroom_type` "WCS" attenuates the mains by the coherent sum of the mains plus the LFE at
  +10 dB, `20·log10(n_mains + 10^(10/20))`, and the LFE by 10 dB less; a number attenuates by its
  magnitude plus 10 dB. beqforge's -20.2 is WCS for 7.1 to within 0.1 dB, and 2 dB too low for
  5.1.
* `clip_before`/`clip_after` clip each channel, or the sum, at full scale.

The caller already sends it: beqdesigner's batch design and library runs pass `bass_management`
from the profile or the preferences (`pipeline/library/bass.py`), so the TODO's "caller
propagation" subtask was done on that side.

## How much the feed differed

beqforge's feed against beqdesigner's ("Before"/"After", WCS, 80 Hz) on the 11 baseline titles,
from their channels: the peak, and the median spectrum difference per band (dB, theirs minus
ours).

| Title | Layout | Peak | 5-20 | 20-40 | 40-60 | 60-80 | 80-120 Hz |
|---|---|---|---|---|---|---|---|
| 28 Years Later | 7.1 | -0.2 | 0.0 | -0.1 | 0.0 | +0.5 | +1.4 |
| Alto Knights | 7.1 | +2.0 | +0.1 | -0.2 | +3.1 | +5.1 | +11.0 |
| Ballad of Wallis Island | 5.1 | +1.6 | +2.0 | +1.8 | +2.8 | +8.3 | +12.1 |
| Black Bag | 5.1 | +2.1 | +1.4 | +1.6 | +3.1 | +5.5 | +11.6 |
| Bugonia | 7.1 | +0.4 | -0.1 | -0.2 | -0.8 | -0.9 | +8.2 |
| Caught Stealing | 7.1 | -1.6 | +0.1 | 0.0 | +0.4 | +3.5 | +11.4 |
| Dossier 137 | 5.1 | +7.6 | +2.0 | +2.5 | +3.6 | +5.8 | +12.5 |
| Incredible Hulk | 5.1 | +1.1 | +1.9 | +1.8 | +2.1 | +3.0 | +5.7 |
| Obsession | 7.1 | -2.9 | -0.4 | -2.2 | -5.9 | -0.5 | +11.9 |
| Safe House | 5.1 | +2.0 | +2.0 | +2.1 | +2.1 | +3.7 | +11.6 |
| Send Help | 7.1 | +1.0 | +0.1 | +0.2 | +1.0 | +3.8 | +9.6 |

Two effects. The gains move a 5.1 title's whole feed by about 2 dB, which reaches the clipping
figure but not a deficit (the deficit is read against the feed's own plateau, and the
mains-to-LFE ratio is the same 10 dB in both). The second low-pass on the mains changes the
feed's shape above about 40 Hz by up to 8 dB below 80 Hz and 12 dB above, and where mains and
LFE meet out of phase (Obsession, -5.9 dB at 40-60 Hz) it changes what sums. "Off" differs far
more (+17 to +23 dB above 80 Hz). The judge reads the corrected curve from the mix
(`verify`'s `reference_samples`), so the feed reaches a decision only through the over-lift bar
(`overlift_allowance`) and the clipping figure; whether that moves an answer was measured below.

## Change

* `PlaybackParams.mains_lowpass_hz` ("crossover", a corner, or None), beside `sub_lowpass_hz`:
  the default keeps beqforge's two low-passes, so a CLI run or a request without
  `bass_management` is unchanged. `crossover_hz` now means the crossover, the band the sub plays,
  whether or not anything is low-passed there. `--mains-lowpass` on `beqforge design`.
* `designer.playback_from_bass_management` builds the model from §2: "Before"/"After" are the bus
  low-pass alone, "Off" none; the gains from `headroom_type` with the contract's `n_mains` (every
  `channels` key except "LFE"). A malformed field is a 400 at `request_from_json`.
* `clip_before`/`clip_after` are not simulated: `gain_reduction_db` is the reduction that keeps
  the feed from clipping at all, and clipping it first would hide the very peak it measures. The
  clipping line names them as not simulated, and describes the model it did use (where each
  low-pass sits, the gains) instead of "LR4 crossover at" with the fixed gains.
* `DESIGN_VERSION` 6, shared with TODO 28's fit change, both unreleased: a request carrying
  `bass_management` can get a different answer.

One difference from beqdesigner's code remains, on purpose: for a layout without an LFE it counts
every channel but one as a main (`len(channels) - 1`); the contract, followed here, counts every
key except "LFE". They agree whenever an LFE is present.

## Outcome

Regression against TODO 28's commit (`f6dca94`):

* Default path (no `bass_management`, the CLI's defaults): probe 11 of 11 unchanged at tol 0.
  The default model's description is word for word what it was.
* The caller's model, as beqdesigner sends it ("Before"/"After" LR4 at 80 Hz, WCS: mains -18.24
  / LFE -8.24 dB on the 5.1 titles, -20.14 / -10.14 on the 7.1), real runs of all 11 titles
  (`--mains-lowpass off` and the gains) against the default model's answers at the same code:
  every candidate's verdict, every winner and every accepted corrected curve identical. The
  over-lift bar moved nothing here.
* What does move is clipping. The same filters under both models (`measure_headroom`):

  | Title | Layout | Accepted | Peak, default | Peak, caller's | Gain reduction |
  |---|---|---|---|---|---|
  | Black Bag | 5.1 | flatten | +1.4 dB | +3.2 dB | 1.40 to 3.16 dB |
  | Incredible Hulk | 5.1 | parametric | -4.5 | -2.6 | none |
  | Safe House | 5.1 | flatten | -6.9 | -5.1 | none |
  | Ballad of Wallis Island | 5.1 | flatten | -19.6 | -17.8 | none |
  | Alto Knights | 7.1 | flatten | -7.4 | -5.8 | none |
  | Send Help | 7.1 | parametric | -10.2 | -9.3 | none |
  | 28 Years Later | 7.1 | flatten | -11.0 | -11.1 | none |
  | Caught Stealing | 7.1 | parametric | -5.1 | -5.4 | none |
  | Obsession | 7.1 | flatten | -6.2 | -7.5 | none |

  (Bugonia and Dossier 137 decline under both.) The 5.1 titles rise by the 1.8-1.9 dB the WCS
  gains add; the 7.1 titles move -1.3 to +1.6 dB with the mains' second low-pass gone. So the
  caller's `gain_reduction_db` was understated by up to 1.8 dB on these titles, and that figure
  is part of the answer: `DESIGN_VERSION` 6 (shared with TODO 28) covers it.
