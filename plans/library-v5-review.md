# Review of the design version 5 library redesign (TODO 31)

beqdesigner redesigned 1,083 library titles on 0.2.9 (design version 5; pipeline job `ef4265fa`,
22-23 October 2026, settings `9cf04c30b0f0`). About 1,000 designed and 69 declined. Of 18 titles
version 4 designed that now decline, about half look right (mono-era and dialogue-led mixes). The
rest, and other declines that look like beqforge's, are in its handoff,
`/media/beq/triage/handoff-v5.md`, with each title's queue id, v5 run record
(`/media/beq/work/records/`) and earlier design run. Ledger: `/media/beq/triage/ledger.jsonl`,
stage `D`.

The handoff's four groups:

1. **O2 refuses a passband whose knee lands just under 10 Hz** (A Quiet Place: Day One, Elysium,
   Pan). Fixed below.
2. **A candidate rejected for missing one check by a fraction.** Cliff by under 3 dB/oct
   (Heartburn, Back to the Future, Guardians of the Galaxy, The Commitments), tilt (Guardians,
   The Exorcist, Alien Resurrection, Philadelphia), level (Ray), F9 residual just below the
   content edge (Drive, Amy). Open. The library has no known negatives, so it can show a wrong
   decline but not price a wider tolerance; any retune goes through the protocol and E10.
3. **Every candidate corrected only down to above the content edge** (Return to Seoul, Spirited
   Away, The Jungle Book, Bugonia). Open, per title.
4. **Known:** steep filter (rows 5 and 6; `judge_from_content_edge` is a server flag, not on the
   wire), F5 (Eastern Promises, Fame, Home Alone) and the texture boundary (row 26).

## O2 at the knee (design version 6, 23 October 2026)

O2 (0.2.9) refused any mix plateau starting less than `min_judge_octaves` above the judging floor
(10 Hz), so as not to restore towards rumble at the very bottom of the spectrum. Three titles
with catalogue BEQs restoring the band beneath now declined on it.

Measured on the v5 material, the analysis on HEAD, with the low end's deepest shortfall and the
passband's ripple (the texture blocker's two figures) computed regardless:

| Title | plateau (Hz) | shortfall (dB) | ripple (dB) | handoff |
| --- | --- | --- | --- | --- |
| A Quiet Place: Day One | 9.9-44.2 | 15.9 | 3.4 | wrong decline |
| Elysium | 9.3-54.8 | 6.8 | 5.1 | wrong decline |
| Pan | 10.0-43.8 | 7.0 | 3.1 | wrong decline |
| The Traitor | 6.5-15.0 | 8.6 | 5.9 | right |
| We Own the Night | 7.3-10.4 | 8.5 | 6.8 | right |
| Synecdoche, New York | 8.3-11.9 | 24.9 | 12.5 | right |
| Evil Does Not Exist | 8.7-13.1 | 8.5 | 6.9 | right (also no positive correction) |
| Battle: Los Angeles | 7.5-72.1 | 1.3 | 4.8 | right |
| The Assassination of Jesse James | 7.6-10.9 | 5.3 | 14.2 | right |
| Don't Bother to Knock | 4.0-10.9 | 10.9 | 11.3 | right |
| Sunset Boulevard | 5.2-13.5 | 13.6 | 16.4 | right (also loud events) |
| Ace in the Hole | 4.0-10.8 | 9.4 | 14.7 | right (also loud events) |
| The Favourite | 6.5-8.9 | 0.0 | 16.6 | right |

So dropping O2 for the texture test alone would let three right declines through. What separates
the three is extent: their plateaus run on to 44-55 Hz, while every rumble plateau ends by 15 Hz.
The rule now: a plateau starting under the line is still the reference when it reaches another
`min_judge_octaves` above it (20 Hz) **and** the shortfall beneath exceeds the passband's ripple.
Otherwise O2 refuses as before, in the same words, so Battle: Los Angeles and the golden's
unfiltered case keep their reason. No new constant.

Regression, against HEAD `e0b1cd4`:

* Probe: 11 of 11 unchanged at `--tol 0` (every baseline plateau starts at 12 Hz or above).
* Protocol seeds 101 and 947: output byte-identical before and after.
* Negative corpus: gate pass, 0/45 gated false acceptances (upper bound 0.079), `filtered` 7/9,
  `natural_droop` 5/9. Four cases differ from the committed `negative_corpus.json` (27 September)
  in which strategy is selected; rerun on HEAD they are identical to this run, so that is earlier
  drift, not this change. The committed file was not refreshed.
* Golden: unchanged.
* The 13 titles above, analysis on the new code: only the three wrong declines lose their
  blocker; every other title keeps the same blockers and wording.
* Real runs of the three, as the library route sends them (contract 1.5, LR4 80 Hz "Before",
  WCS): all design, with `flatten` accepted. A Quiet Place: Day One gets a low shelf at 7.85 Hz,
  +17.9 dB; Elysium 7.32 Hz, +7.6 dB; Pan 9.23 Hz, +5.4 dB with a +1.2 dB peak at 14.8 Hz.
  Corrected curves (peak, relative to 25 Hz) sit within about ±5 dB of the passband from 4 Hz
  up, against 12-15 dB (A Quiet Place), 4-6 dB (Elysium) and 3-6 dB (Pan) short before. The
  catalogue's BEQs for these titles are a comparison, never the calibration.

It changes answers, so it shares the unreleased design version 6 (rows 1 and 28).
