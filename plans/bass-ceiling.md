# A bass ceiling (TODO 39)

Bass EQ restores the low end that a mix's filtering removed, and that low end ends at or below
about 60 Hz. The designer had no such limit. The judged band's top followed the deficit's first
settled end (`pipeline._judged_top_hz`), and was at least `min_judge_octaves` above the tracking
floor. On a mix whose floor sits high, that top reached the midbass, and `flatten` filled
everything under it.

Wait Until Dark (1967) shows it. Its band was judged flat to 192 Hz, and its cascade lifted 110 Hz
by 7.4 dB and 250 Hz by 2 dB. It passed because the over-lift bar's slack is half the input's
roughness: 31.5 dB of roughness allowed 15.7 dB of lift.

## The premise, checked against the catalogue (31 October 2026)

This is a check of the premise, not a calibration (AGENTS.md: never calibrate against the
catalogue). The measure is where each cascade's own lift last reaches 3 dB.

| Lift of 3 dB or more reaches | Catalogue (15,586 entries) | beqforge v8 library (1,033 accepted) |
| --- | --- | --- |
| median | 28 Hz | 31 Hz |
| 90th / 99th percentile | 41 / 58 Hz | 65 / 139 Hz |
| above 60 Hz | 114 (0.7%) | 128 (12.4%) |
| above 80 Hz | 11 (0.1%) | 74 (7.2%) |
| above 100 Hz | 2 | 45 |

- **Above 80 Hz:** ten of the catalogue's 11 entries are mobe1969's. Review judged them flatten-like
  designs with no upper-bass cap, not corrections to copy: The Thing, Force 10 from Navarone, The
  Monster Squad, Cinderella, and Sinners and Saints.
- **60-80 Hz:** this is about 0.9% of each author's entries.
- **Age:** about two thirds of the gap is the library's age mix. Before 1980, 49-63% of the
  library's designs lift above 60 Hz; from 2000 it is 2.5-5%. Reweighted to the catalogue's age
  mix, the library still lifts above 60 Hz on 4.5% of designs against 0.7%, and above 80 Hz on
  1.7% against 0.1%.
- **Recent films:** in the 2020s, the catalogue's exceptions are a shelf's skirt running a little
  past 60 Hz. The library's are wide shelves into the midbass, as on Petite Maman and In Bed with
  Victoria.

## The change (branch `experiment-bass-ceiling`)

`AcceptParams.bass_ceiling_hz = 60.0` (`None` turns it off):

- **Targets.** Every priced target, of every strategy, tapers to nothing by the ceiling, from 48 to
  60 Hz over `flatten_taper_ratio` (`priced_by_evidence`). A target note records when it binds.
- **Judged band.** The ceiling caps the deficit's end, and with it the tilted goal's pivot. It
  does not cap the one-octave span. A slope read over less than an octave is arbitrary
  (`min_judge_octaves`), so a title whose floor is above 30 Hz is judged up to twice its floor,
  above the ceiling, where nothing is asked for. A title whose floor is above 60 Hz has nothing
  left to correct.
- **Over-lift bar.** Above the ceiling, up to the top of the design grid, the bar bounds the
  cascade's own lift to `level_tolerance_db` (3 dB) over the material, with no roughness slack.
  `overlift_allowance` hands the same bound to the fitter. A failure there names the ceiling.
- **Mix-texture blocker.** It keeps its uncapped band (`_judged_top_hz(..., ceiling=False)`), so
  the ceiling changes no blocker decision.

## Outcome (31 October 2026)

**Probe, 11 baseline titles.** No verdict or winner moved. The targets of Ballad of Wallis Island,
Black Bag and Safe House were trimmed by up to 1.75 dB around 56 Hz. Real runs of those three
accept the same strategy, with corrected curves within 0.2, 1.5 and 0.7 dB of the baseline's:

- Ballad of Wallis Island and Black Bag need fewer sections (2 instead of 3; 2 instead of 4).
- Black Bag loses a 1.4 dB cut at 70 Hz and a dip at 15 Hz.
- Safe House has no baseline record in `data/`, so it was compared with a run of the unchanged code.

**Synthetic protocol, seeds 101 and 947.** No false acceptance or abstention moved. On each seed
one case, `varying_filtered`, changed winner:

| Seed | Winner | Recovery error (dB rms) |
| --- | --- | --- |
| 101 | flatten to counterfactual/25dB | 18.2 to 25.8 |
| 947 | parametric to flatten | 13.6 to 4.8 |

**Negative corpus, seeds 1-9, against the same corpus run on unchanged code.** The committed
`negative_corpus.json` dates from 27 September and predates later changes.

| Measure | Unchanged code | Ceiling |
| --- | --- | --- |
| gated negatives, false acceptances | 0/45 | 0/45 |
| natural_droop, false acceptances | 5/9 | 4/9 (natural_droop/7 now abstains) |
| filtered, true positives | 7/9 | 6/9 |

The lost true positive is filtered/1 (LR4 at 24.9 Hz), which now abstains. Its accepted design
recovered the injected filter with a 15.6 dB rms error.

**Paired library sample.** 80 titles were each designed twice at default settings, on the
unchanged code and on the ceiling, with records in the session scratchpad. The sample was 60
titles that lift 3 dB above 60 Hz in version 8, chosen at random plus the cases named in review,
and 20 controls.

- **Lifters, 57 of 60 still accept.** None lifts 3 dB above 58.7 Hz (before: 60-400 Hz).
  - Lift at 80 Hz: up to 2.9 dB, against up to 14.8 dB before.
  - Wait Until Dark: 7.1 to -1.2 dB at 80 Hz, 7.7 to -0.9 dB at 100 Hz.
  - The Parent Trap: 6.2 to 0.7 dB at 80 Hz.
  - The Birds: 12 to 0.3 dB at 80 Hz.
  - Lift below 40 Hz is mostly unchanged.
- **Lifters, 3 now decline:**
  - The Manchurian Candidate (floor 50 Hz). Its version 8 design lifted 9 dB at 80 Hz. The capped
    fit's skirt still lifts 3.7 dB at 400 Hz.
  - Solaris. Its version 8 design lifted 15 dB at 80 Hz.
  - The Red Shoes. Its version 8 design lifted 10.6 dB at 80 Hz.

  Solaris and The Red Shoes now fail wobble: over the narrower band the material's roughness
  halves, and the capped shelf's step at 50-60 Hz no longer hides in it. All three were flatten
  designs filling a mix whose plateau sits above 60 Hz.
- **Controls, 20 of 20 still accept,** with curves essentially unchanged. Two changed winner, as
  row 32 already shows they can:
  - Terminator 2: parametric to flatten.
  - Predator: flatten to counterfactual.
- **Steep drops follow the mix, not the ceiling.** The median drop in lift from 40 to 60 Hz rises
  from 2.1 to 5.2 dB, and 8 designs drop by 15 dB or more (before: 1). These follow the mix's own
  rise to a plateau at or just above 60 Hz: Wait Until Dark's plateau is 62-90 Hz. The corrected
  curves pass the cliff clause.

**Not addressed.** The ceiling removes the midbass lift, not the lift below 60 Hz. Wait Until Dark
still lifts 21-28 dB at 20-40 Hz, which review heard as constant rumble. That is row 33's question
(is the tracking boundary noise or content), not this one.

**Declined titles.** A further random sample of library titles version 8 declined was designed
the same way: 10 that declined before any fit, and 12 that declined after fitting.
- **Declined before any fit:** all 10 still decline.
- **Declined after fitting:** 3 of 12 now design: 22 Jump Street, After Hours and Desperately
  Seeking Susan. Their judged bands end at 36-43 Hz, below the ceiling, and their targets are
  unchanged. They are fit re-rolls (row 32): the fitter's new bound above 60 Hz moves which
  near-equal fit it lands on. The new designs lift at most 1.9 dB above 60 Hz.

## Adopted (31 October 2026, design version 9, released in 0.3.2)

Adopted as design version 9.
- **Impact.** `beqforge/impact.toml` declares `targets.shared` and `judge.overlift` as behaviour,
  measured together over the paired samples by `impact.MOVED`:

  | Outcome class | Moved / measured |
  | --- | --- |
  | no_fit | 0 / 10 |
  | declined_after_fit | 3 / 12 |
  | designed_with_failures | 11 / 15 |
  | designed_all_passed | 54 / 65 |

  `judge.assess` is declared unchanged: only its wording changed. Because the sample was chosen
  for what the ceiling reaches, these counts scored the whole library `likely`. Since 1 November
  2026 they are split by whether a record reaches above 60 Hz: 61 of 66 above, 4 of 14 designs
  and 3 of 9 declines below. On the v8 library that is 365 `likely` and 684 `possible`, where it
  was 1,033 `likely`
  ([redesign scope](redesign-scope.md#scoring-a-change-by-what-it-reaches-1-november-2026)).
- **Golden answers:** regenerated.
- **Tests:** the two that expected the old over-lift wording now also accept the ceiling's.
  New tests cover the bar above the ceiling, the target taper and the judged top.
- **Baselines:** `negative_corpus.json` is replaced by the ceiling's run, and the baseline
  records in `data/` are refreshed.
