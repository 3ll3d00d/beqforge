# Baseline evidence and validation context

**Status: archived, review completed 2026-09-30.** This is historical evidence, not a
work queue. Original hypotheses and intermediate states below describe the code at the
time of the review; later outcomes supersede them. All outstanding follow-ups are tracked
only in [TODO.md](../TODO.md). Current behaviour is documented in [README.md](../README.md).

The baseline table and original wrong-decline assessments below are dated observations.
Black Bag was subsequently accepted after F3; Dossier 137's abstention was retained for
a different content reason. See the implementation and research outcome records.

## Baseline: 2026-09-26 track set

Nine complete programmes from UHD/BD discs, extracted at 1 kHz by beqdesigner's worklist
(`ffmpeg -drc_scale 0 … aresample=1000:resampler=soxr`, 24-bit) and designed through the designer
server. They were then re-extracted from the same `multichannel.wav` with `tools/extract.py` and
re-run at HEAD (4858a45) with default parameters and all three strategies. Filtered/unfiltered
status is **unknown for every title**: nothing here has an independent source, so none of these
is ground truth for E2 or A1.

| Title | Layout, runtime | Server | HEAD | Winner (sections, peak gain) | Recovered / shaping | Mix plateau | Tracking floor → judged band |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 28 Years Later | 7.1 (Atmos), 115 min | accept | accept | `parametric` 2, +18.7 dB (server: `flatten` 4, +7.7) | 0.99 / 0.77 | 28.7-81.2 | 20.5 → 20.5-45 |
| Alto Knights | 7.1 (Atmos), 122 min | accept | accept | `flatten` 3, +20.2 dB | 0.90 / 0.84 | 25.5-53.8 | 12.8 → 12.8-45 |
| Ballad of Wallis Island | 5.1, 100 min | accept | accept | `flatten` 3, +8.6 dB | 0.93 / 0.43 | 28.4-38.5 (0.44 oct) | 20.1 → 20.1-59.1 |
| **Black Bag** | 5.1, 94 min | **decline** | **decline** | — (`flatten` fails on F3 only) | 0.98 / 0.63 | 50.2-82.8 | 25.1 → 25.1-50.2 |
| Bugonia | 7.1 (Atmos), 119 min | accept | accept | `flatten` 1, +5.4 dB | 0.59 / 0.61 | 18.1-39.7 | 6.4 → 6.4-45 |
| Caught Stealing | 7.1 (Atmos), 107 min | accept | accept | `flatten` 2, +12.2 dB | 1.00 / 0.61 | 24.5-49.7 | none → 5-45 |
| **Dossier 137** | 5.1, 116 min | **decline** | **decline** | — (all fail on judged-band width) | — | **143.3-200.0** | **143.3 → 143.3-155.6** |
| Obsession | 7.1 (Atmos), 109 min | accept | accept | `flatten` 3, +28.2 dB | 0.92 / 1.02 | 24.3-40.1 | none → 5-45 |
| Send Help | 7.1 (Atmos), 113 min | accept | accept | `flatten` 2, +13.1 dB | 0.93 / 1.00 | 24.1-41.7 | none → 5-45 |

**Records refreshed after E3 (d68eba0).** The table above is the state at 4858a45. The
`data/*.run.json.gz` records the probe re-judges against now come from d68eba0, with
Bugonia, Caught Stealing, Obsession and Send Help refreshed again at b168669. Current winners:
`parametric` on 28 Years Later; `flatten` on Alto Knights, Ballad of Wallis Island, Black Bag,
Bugonia, Caught Stealing, Obsession and Send Help; Dossier 137 abstains (`no_usable_plateau`,
see Progress). The next refresh is due when a change is accepted that
moves targets. **The Incredible Hulk** (5.1, 112 min, fairly full bandwidth) joined the set as a
tenth title at 0431bbc, the source for the injection experiments.

**Dossier 137 should not have been declined.** *(Superseded — see "Dossier 137 — decided" in
Progress: abstaining is right; the original reason was wrong.)* Every main channel is steeply rolled off (L 48.5
dB/oct at 41.7 Hz, R 51.2 at 28.1 Hz, C 33.2 at 39.3 Hz); the mean spectrum falls about 40 dB
between 100 and 30 Hz; LFE is almost silent (219 loud frames of 13,597, 0% of the mix plateau).
The decline is not an evidence decision. It is T4 feeding T8: a plateau at the band edge sets
a tracking reference in the dialogue band, and the judged band collapses. Expected after the fix:
a judged band reaching down to about 35 Hz, and a correction the evidence may or may not license
there. Either outcome is legitimate; the current one is not.

**Black Bag is a probable wrong decline.** Its `flatten` candidate passes every substantive
clause and fails only F3's band mismatch. Whether a pruned or refitted cascade is acceptable is
F3's check; the mix's level-invariance boundary sits at 50 Hz with 5.6 dB of the correction
below it, so the answer may still be a small or partial correction.

**Shape coverage.** Positive-control candidates (bass-rich, full LFE): 28 Years Later, Send
Help, Obsession, Caught Stealing, Bugonia. Sparse, dialogue-led: Black Bag, Dossier 137, Alto
Knights. Nearest to a music film: Ballad of Wallis Island (not continuous bass). Layout: 5.1 and
7.1 beds only. **Still missing:** paired releases, an old or upmixed mix, a concert film,
a heavily compressed mix, a noise-dominated documentary, 2.0, and long/short pairs — so the
"Definition of enough" below cannot yet be met (no natural-droop variant, no paired release).

**Reproducing it.** `tools/extract.py "<title> - audio 1/multichannel.wav" --out data --name
<Title>` accepts the worklist's WAV directly (layout survives in the WAV header), then
`tools/design_beq.py data/<Title>.npz`. About 100-175 s a title at HEAD.


## Standing limits

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


## Earlier source history

`AUTOMATED_DESIGN.md`, `PERFORMANCE.md` and `DESIGN_EVIDENCE.md` were retired in
September 2026 after their current design account moved into AGENTS.md. Their original
derivations remain in the sibling beqanalyser repository's git history, not this extracted
repository: those files were outside `beqanalyser/design/` and were not carried over.
Use `git log --follow -- AUTOMATED_DESIGN.md` there before the retirement commit.
