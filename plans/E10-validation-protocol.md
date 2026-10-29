# E10: a fresh validation protocol for the content goal (v6)

**Protocol written 22 October 2026; its instrument is built (`beqforge/e10.py`, `tools/e10_run.py`, `tools/e10_cases.py`) and the title partition frozen (`plans/e10-titles-v1.json`). The first development run revised the instrument to v2, the tilted goal's pivot was settled in v3, v4 fixed the accuracy bound, the cancellation recipe and the decision rule's first clause, v5 replaced the pumping floor, and v6 allowed a restoration's skirt (all below)** (TODO row 3). This is the
predeclaration E10 asks for: what a held-out evaluation contains, how it is scored and what a
change must show on it, fixed before any held-out case is generated. Rows 2 and 26 (the texture
yardstick and its retune), the library review's research items 1b and 5, steep-filter scoring
(row 5) and the steep-filter default (row 6) all wait on it.

## Why a new protocol

Two instruments exist and both are spent as held-out evidence:

* `evidence_validation.json` (`tools/validate_evidence.py`, seeds 101 and 947) labels its negatives
  by provenance, from when the question was "was a mastering filter applied?". Under the content
  principle (`beqforge/AGENTS.md`, "Whether to boost is a question of content, not of cause")
  `natural_bass_light` is real attenuated programme, and lifting it towards a flat goal is the
  dials working; it is already read as reported, not counted.
* The negative corpus (`tools/negative_corpus.py`, seeds 1-9, 63 cases) has informed every
  decision since E2: the texture yardstick's degree and band (row 2), every library-review fix
  (row 29). Its intervals no longer describe held-out performance, and its per-shape counts are
  weak by construction: 0 of 9 bounds a rate only below 33.6%, 0 of 45 below 7.9%.

Both stay exactly as they are and keep running as regression checks. Their counts are reported
beside every E10 result, so the history stays comparable.

## What is being judged

The designer's job under the content goal: lift real programme that the material shows was
attenuated, towards the requested goal, and lift nothing that is not programme. So the protocol
scores outcomes against what each case's construction makes true, never against a detector or a
residual. Every score is taken on the **published device response** (`publication_filters` at the
case's realisation), as `harness.score_evidence_case` already does.

### Failure classes

Each scored case lands in one or more of these. They are tallied separately and never summed.

| Class | Definition (on the published response, in the case's truth band) | Kind |
| --- | --- | --- |
| **Noise lift** | The corrected noise spectrum rises more than 3 dB above the uncorrected noise anywhere programme sits below the noise in the truth (the truth arrays say where), more than half an octave under the truth band's bottom (v6; the whole noise-only region when there is no truth band). | safety |
| **Unnecessary intervention** | Any selected filter on a case whose truth is already within the goal and its tolerance across the truth band. | safety |
| **Overshoot** | The corrected programme rises more than the accuracy bound (1.5 dB, at every goal; v4) above the goal, or above the uncorrected programme where that already stood over the goal, anywhere in the truth band. | safety |
| **Missed recovery** | On a case with attenuated programme, abstaining, or a corrected programme still below the goal by more than the accuracy bound over more than a third of an octave of the truth band. | accuracy |
| **Device failure** | The published cascade cannot be realised (infinite drift: unstable once quantised). A finite drift is already inside every curve the other classes read, and `max_drift_db` is the fitter's preference, not a gate (`AcceptParams`). | accuracy |

"Truth band" is declared per recipe (below), not the scorer's fixed 60 Hz top: the band where
the recipe put programme and where restoring it is right. "Noise" means the case's own additive
noise, measured from its stored noise arrays through the published response, not the white-floor
formula the current scorer uses (row 5).

Missed recovery is also reported as a continuous shortfall: the median and worst gap between the
corrected programme and the goal over the truth band, in dB.

## Goals

Every case is run at three goal settings, predeclared:

| Goal | `--goal-tilt` | `--goal-tolerance` |
| --- | --- | --- |
| flat (the default) | 0 | 1.5 |
| gentle rolloff | -1.5 dB/oct | 1.5 |
| tight | 0 | 0.75 |

A goal's tolerance is the pipeline's act threshold (`AcceptParams.goal_tolerance_db`): it
decides whether a case needs a correction and whether a selection was unnecessary, never how
close a correction must land. Overshoot and missed recovery use one accuracy bound, 1.5 dB, at
every goal (v4). So the tight goal tests when the designer acts, not how precisely.

What the goals license, which is the "goal/corpus follow-up" TODO row 17 sends here:

* **Every goal licenses lifting tracked programme towards it, and none licenses lifting
  anything else.** A natural droop (programme recorded rolled off) is a positive under every
  goal: its low end is real programme. Its truth band is where the source has programme above
  the noise.
* **A case must abstain, under every goal**, when: it is an excerpt (`coverage="excerpt"`); its
  sub band holds no programme (noise only, or a dialogue-led mix whose only plateau is above the
  sub band); or the truth already sits within the goal's tolerance.
* **A case whose answer depends on the goal** is scored under each goal separately. A mix
  already falling 1.5 dB/oct needs nothing under the gentle goal but is a positive under the flat
  one. The recipe states its truth slope, so this is computed, not judged.

## Case families

Two sources of cases, each with a development part and a held-out part.

### Synthetic families

Built beside `harness.corpus_case`, which stays untouched, in `beqforge/e10.py`. Each family is a
recipe drawing every parameter from its seed. Whether a case needs a correction is not
labelled: the scorer computes it per goal from the stored arrays (see "Scoring" below), so the
last column is what the recipe is built to provoke, not a label.

| Family | Construction | Built to provoke |
| --- | --- | --- |
| `broadband` | As the corpus's: flat programme, no filter. | negative (within the goal) |
| `sparse_dialogue` | Programme events rare and quiet, mid-band only. | negative |
| `stationary_noise` | Coloured noise only, no programme. | negative |
| `coloured_floor` | Programme high-passed at 15-40 Hz, order 8-16, then a floor whose spectrum is pink, brown or codec-shaped (a lossy encoder's low-band noise, from a recipe), 30-60 dB below the programme. | positive above the corner, noise-lift exposure below |
| `tracking_floor` | As `coloured_floor`, the floor rising with the programme's 1 s level above its median, by at most 2-6 dB (drawn), as a codec's noise follows the signal (v5). | positive, noise-lift exposure |
| `breathing_floor` | As `coloured_floor`, the floor pulled down by 2-6 dB (drawn) under loud passages and released over about a second, as a compressor's gain reduction does (v5). | positive, noise-lift exposure |
| `event_locked_floor` | v4's `nonstationary_floor`: the floor scaled by `0.25 + level / mean`, about 37 dB of swing, rising only inside events. **Reported, not counted** (`e10.REPORTED`): it is event-locked content (v5). | reported |
| `correlated_noise` | The same noise in every channel (a mastering hiss or hum bed), so it tracks across channels like programme. | negative below the programme's own corner |
| `finite_stopband` | Programme high-passed with a stopband floor of -40 or -60 dB (a filter, not a cut-off), no added noise. | positive down to where the stopband meets the floor |
| `partial_channels` | The high-pass on the LFE only, or on the mains only. | positive; the restored channel must carry it |
| `cancellation` | The mains carry the LFE's low band (a zero-phase fourth-order low-pass at 60 Hz) inverted, cancelling 30-80% of it in phase (v4). | the mix's low band reduced by cancellation: under the content principle still programme, so computed like a droop |
| `natural_droop` | Programme synthesised with a rolled-off spectrum, no filter. | positive under flat, per-goal otherwise |
| `continuous_bass` | Bass that never goes quiet (a concert film), filtered or not. | both, by seed parity |
| `filtered` | As the corpus's: a 2-4 order Butterworth or Linkwitz-Riley at 15-40 Hz. | positive |

### Real-texture families

Real programme above the sub band, with a known change in it, so the truth is differential:
what the recipe did, scored against the same title's own as-is result, whose unknown mastering
cancels. Drawn from beqdesigner's extracted library (`/media/beq/work/<title> - audio 1/`, about
1,290 titles, read as `.npz`).

| Family | Construction | Negative or positive |
| --- | --- | --- |
| `injected_rolloff` | A Butterworth or Linkwitz-Riley high-pass, order 2-16, 15-40 Hz, on every channel or on a subset. | positive for the additional change |
| `noise_replaced` | Below a corner drawn from 25-50 Hz, the programme removed (a 16th-order high-pass) and a floor at a stated spectrum and level added. | negative below the corner: anything lifted there is noise |
| `excerpt` | 20% and 50% of the programme, marked `coverage="excerpt"`. | must abstain |

These are the "negatives built from real programme texture" row 26 asks for. `noise_replaced`
is the first real-texture negative the repo has had.

### Partitions

Variants of one title are not independent, so titles are partitioned, not variants.

* **Synthetic development seeds**: 1-999. The corpus's seeds 1-9 sit here, so they stay
  development.
* **Synthetic held-out seeds**: 100001-100999. Never run before a change is frozen.
* **Real development titles**: every title already used in development, listed at freeze time
  by `tools/e10_cases.py` (to build): the baseline set (`plans/done-baseline-evidence.md`), the
  injected variants under `data/variants`, every title named in `plans/`, `TODO.md`, or
  beqdesigner's triage ledger (`/media/beq/triage/ledger.jsonl`), and every title a record in
  `/media/beq/work/records` was reviewed from.
* **Real held-out titles**: a seeded draw (seed 10) of 60 titles from the rest of the library,
  committed as a list of names at freeze time. Each contributes one `injected_rolloff`, one
  `noise_replaced` and one `excerpt` case.

### Sample sizes

From the interval wanted, using the corpus's two-sided 95% Clopper-Pearson bound:

| Quantity | Bound wanted at zero failures | Cases |
| --- | --- | --- |
| Noise lift, pooled over the negative and noise-exposed families | 5% | 72 or more (0 of 72 bounds below 5.0%) |
| Unnecessary intervention, pooled over the negatives | 5% | 72 or more |
| Any one family | 10% | 36 (0 of 36 bounds below 9.7%) |

So the held-out synthetic set is 36 seeds per family (432 cases, at three goals), and the real
held-out set is 60 titles (180 cases). Positives get the same 36 seeds; their recovery is reported
as a median with a bootstrap 95% interval over cases.

At the corpus's 15-20 minutes for 63 cases, the synthetic held-out half is roughly two hours at
one goal and six at three; the real half, at real-title speeds (40-80 s), about three hours a
goal. A held-out run is therefore a deliberate event, not a regression check.

## Scoring

As built (`e10.truth`, `e10.score`), on a log axis from 5 to 160 Hz, each spectrum the mix-weighted
Welch mean smoothed over a sixth of an octave:

* The **goal** is the observed programme's median level over 80-160 Hz (where every recipe leaves
  it alone) plus the goal's house curve (`verify.house_curve_db`) pivoting where the content's
  deficit ends (`e10.deficit_top_hz`): reading up from the bottom of the truth band, the first
  bin where the scored programme is back within 0.5 dB of its level, or the band's bottom when
  nothing is missing there. A tilted goal is about the recovery, not the track (v3; see "The
  tilted goal's pivot"). With no programme there (noise only), there is no goal and nothing
  needs correcting.
* The **programme** scored is the observed programme's spectrum less its source's (the
  programme before the recipe shaped it, `E10Case.source`), from the same realisation,
  normalised to zero on the reference and placed at the goal's level. So it is the recipe's
  change alone: an unchanged case sits exactly on the flat goal, and a natural droop or a
  cancellation is measured against the programme before it. (v2; see "First development run".)
* The **truth band** runs down from 80 Hz, contiguously, while the observed programme stands more
  than 3 dB above the case's own noise. **Noise-only bins** are those below 80 Hz where the noise
  is louder than the programme.
* A case **needs a correction** at a goal when the programme sits more than that goal's tolerance
  under it over a third of an octave or more of the truth band.
* Each class is then counted over the cases exposed to it: noise lift over cases with noise-only
  bins, unnecessary intervention over cases that need nothing, overshoot over all, missed
  recovery over those that need a correction, device failure over the selected.
* Each row keeps the selected filters and their drift, so a revised instrument can rescore a
  run without designing it again.

**Smoke check (22 October 2026, HEAD `b309000`).** `filtered/1` at the flat goal: the pipeline
corrects to within 1.4 dB of the goal from 12 to 80 Hz, rises 2.9 dB over it near 10 Hz (an
overshoot by this definition, which allows none of the judge's roughness allowance) and stops near
7 Hz, where the programme still stands 20 dB over the case's 1e-5 white noise, so recovery is
missed below it. With noise that low the truth band reaches the 5 Hz floor on most filtered cases,
so missed recovery will be common and the shortfall the more telling figure; the noisier families
(`coloured_floor`, `nonstationary_floor`) are where the truth band stops short of the floor.
`stationary_noise/1` abstains.

## Decision rule

A change E10 gates (a retune, a new rule, a default change) is adopted when, on the held-out
half, against the commit before it, run at the same seeds and titles:

1. **No safety class gets worse.** Noise-lift, unnecessary-intervention and overshoot counts do
   not increase, pooled or in any family. Each run reports the pooled upper bounds against a 5%
   target; the target is not a gate until the known failures are fixed (v4: at the version 8
   build the pumping floor alone gives 4 of 15 noise lifts, so no change, row 33's fix
   included, could pass a 5% gate).
2. **It improves what it was for.** Missed recovery (count, and the median shortfall over the
   positives it targets) improves, with the bootstrap interval of the paired shortfall change
   excluding zero. A change for speed or wording is not gated here.
3. **Nothing else moves unexplained.** Every changed outcome is listed, with its corrected curve
   looked at, as the regression procedure already requires.

Each run states the protocol version, the commit and the legacy counts (protocol seeds 101/947,
corpus seeds 1-9) beside its own.

## Rotation

Once a held-out result informs a change (a threshold moved because of it, a rule rewritten after
seeing a failure), those seeds and titles become development. The next held-out set is the next
seed block (100001 + 1000k) and a fresh draw of titles excluding everything used before; the
protocol version increments. Results from different versions are not pooled.

## What building it takes

1. **Built:** the synthetic families (`beqforge/e10.py`, `e10_case`), each storing the recorded
   programme, the observed programme and the noise per channel; the corpus's shapes unchanged.
2. **Built:** the scorer (`e10.truth`, `e10.score`, `e10.summarise`), on the published response,
   with noise taken from the stored noise arrays rather than a white-floor formula: row 5's
   coloured-floor scoring, for the synthetic families.
3. **Built:** `tools/e10_cases.py`. `freeze` wrote `plans/e10-titles-v1.json` (names only): of
   1,287 library titles with a multichannel extraction, 332 are development (named in `plans/`,
   `TODO.md`, the triage ledger, findings or status, or the baseline set, matched on the name
   without its year) and 60 are held out, drawn with seed 10 from the 955 others. `run` designs
   each title as it is and with each recipe, all drawn from the title's place in the list, and
   scores a recipe against the as-is design: `injected_rolloff` by what the design adds against
   the filter's inverse, where the as-is run tracked programme and the filter leaves it within
   40 dB; `noise_replaced` by any boost over 3 dB half an octave under its corner; each excerpt
   (20% and 50%) by whether anything is selected. A title costs five designs a goal.
4. **Built:** `tools/e10_run.py` runs a partition at the goals asked for, one process per case
   with the analysis shared across goals, and writes the protocol version, build, rows and
   summary. `--partition held-out` takes its own seed block and refuses an uncommitted tree.
   Legacy counts are not embedded; a run's write-up states them.
5. **Run:** the first development run, below. It revised the instrument (v2), and the pivot was
   then settled (v3). The held-out half is not run until the first change E10 gates is frozen.

## First development run (22 October 2026)

Seeds 1-3, every family, three goals (36 cases, 108 rows), on the design version 6 stack
(`9795921`). Scratch evidence, not committed; this records what it showed.

**v1's instrument was wrong in three ways, all fixed in v2 before any held-out run:**

1. *It read the deficit from the observed spectrum alone.* A single realisation's sixth-octave
   estimate scatters by 2.5-3.5 dB at the bottom of an unchanged case, so `broadband/2` and
   `sparse_dialogue/1,3`, which nothing touched, "needed correction" at the flat goal (missed
   22/27, median shortfall 0.64 dB). v2 scores the observed spectrum less its source's from the
   same realisation (`E10Case.source`, the programme before the recipe shaped it), so the change
   alone is scored: every unchanged case sits exactly on its goal, and a natural droop or a
   cancellation is measured against the programme before it.
2. *Overshoot read one curve.* Against the source alone, filling a chance dip in the actual
   programme reads as overshoot; against the observed spectrum alone, restoring a chance peak the
   recipe cut does. v2 counts an overshoot only where both readings rise more than the tolerance
   over the goal (or over where the programme already stood above it). `filtered/1` at the flat
   goal, which rose 0.3 dB over at 28 Hz from a 1.1 dB chance dip filled, is no longer one.
3. *Device failure counted drift over `max_drift_db`,* which the pipeline retired as a gate on
   purpose: the drift is already in the published response every class reads. v1 flagged
   `filtered/1` (3.4 dB) and `natural_droop/2` (4.1 dB), both realised curves fine. v2 counts
   only an unrealisable cascade.

Each row now keeps its selected filters and drift, and `tools/e10_run.py --rescore` scores a run
again under a revised instrument; the run below was designed once and rescored.

**Results under v2** (k/n over the exposed cases; development, so no claim beyond this set):

| Goal | Noise lift | Unnecessary | Overshoot | Missed | Device | Median shortfall |
|---|---|---|---|---|---|---|
| flat | 4/15 | 0/12 | 4/36 | 18/24 | 0/14 | 0.03 dB |
| gentle | 3/15 | 1/15 | 7/36 | 18/21 | 0/11 | 0.0 dB |
| tight | 4/15 | 0/12 | 7/36 | 19/24 | 0/14 | 0.03 dB |

* **The negatives hold.** `broadband`, `sparse_dialogue` and `stationary_noise` abstain at every
  goal; unnecessary intervention is one row (`nonstationary_floor/1`, gentle).
* **A pumping floor is lifted.** `nonstationary_floor` lifts the floor below the programme's
  corner by 27-33 dB on all three seeds at every goal, where `coloured_floor` (the same floors,
  stationary) abstains. A floor that rises with the programme tracks like programme, so the
  evidence model reads it as programme. This is the protocol's first safety finding against the
  pipeline (TODO 33). `natural_droop/1` lifts 12.9 dB at 5-5.8 Hz, under the white floor.
* **Cancellation overshoots by 2-3 dB** on all three seeds (flat or tight): the recipe's
  inverted fourth-order low band adds back near its 60 Hz corner, leaving a +2-3 dB bump at
  40-56 Hz in the mix, and the designer levels the band below to it. Under the content principle
  the bump is programme, so this is a fair reading of the recipe; but the recipe also reaches
  the 80-160 Hz reference the goal is measured from, so whether to move its corner down is a
  recipe question for the next revision.
* **Missed recovery is mostly abstention.** Ten positives abstain at the flat goal: all of
  `coloured_floor` and `correlated_noise`, `continuous_bass/1,3`, `finite_stopband/3`,
  `filtered/2`. Where a design is selected, the median shortfall is about 0 dB except
  `natural_droop/1` (5.2) and `/3` (2.0); the misses sit at the bottom of the truth band, which
  reaches 5 Hz only because the synthetic white floor is 1e-5.
* **The gentle goal's overshoots are an open instrument question.** E10 pivots the tilted goal
  at 80 Hz; the designer pivots it at the top of its judged band (`verify.house_curve_db`, via
  `Correction.requested_db`), which varies by case. With the judged top at 40 Hz the two goals
  differ by 1.5 dB everywhere below it, and the gentle-goal overshoots on `finite_stopband/1,2`,
  `partial_channels/3`, `natural_droop/2` and `filtered/1` appear only there. Whether the goal is
  "a tilt below 80 Hz" or "a tilt below where the content's deficit begins" is the user's dial's
  meaning, and the protocol must state it before a held-out run.

Legacy counts at the same build: TODO 28's protocol seeds 101/947 and corpus seeds 1-9
(`plans/library-review-improvements.md`, row 28's outcome).

## The tilted goal's pivot (v3, 22 October 2026)

Settled by the user: **a gentle rolloff is about the content's recovery, not the entire
track.** The goal tilts below where the deficit begins and leaves the programme above it as it
is. That is the designer's reading already (it pivots at its judged band's top), so the
instrument changed, not the pipeline. v3 reads the pivot from the case's own change, never from
the design (`e10.deficit_top_hz`, threshold 0.5 dB as `filters.correction_band_hz`'s). Pivots on
seeds 1-3 run from 16.6 Hz (`nonstationary_floor/1`) to 80 Hz where the deficit reaches the
reference (`filtered/3`, `natural_droop/3`); an unchanged case pivots at its band's bottom, so
its goal is flat.

The development run rescored under v3 (flat and tight unchanged, since a zero tilt has no
pivot):

| Goal | Noise lift | Unnecessary | Overshoot | Missed | Device | Median shortfall |
|---|---|---|---|---|---|---|
| gentle, v2 | 3/15 | 1/15 | 7/36 | 18/21 | 0/11 | 0.0 dB |
| gentle, v3 | 3/15 | 0/12 | 1/36 | 21/24 | 0/11 | 0.28 dB |

* Six of the seven gentle overshoots were the pivot mismatch and are gone: `finite_stopband/1`,
  `partial_channels/3`, `natural_droop/2`, `filtered/1`, `cancellation/3` and
  `nonstationary_floor/1`. `finite_stopband/2` (pivot 32.6 Hz) still overshoots.
* A higher goal below the pivot asks for more: `cancellation/1,2` and `nonstationary_floor/1`
  now need a correction at the gentle goal. The two cancellations abstain (missed);
  `nonstationary_floor/1`'s selection, unnecessary under v2, now meets a real deficit, though
  its 27-33 dB lift of the pumping floor below it is still noise lift (row 33).
  `natural_droop/2` turns from an overshoot into a miss (median shortfall 0.84 dB), and the
  gentle goal's median shortfall rises from 0.0 to 0.28 dB.

## Version 8 baseline and v4 (28 October 2026)

The development run again, seeds 1-3, every family, three goals, at design version 8
(`d8e507a`, the fit kernel), since version 8 re-rolls the fit (TODO 23). Scratch evidence, not
committed. Under v3 it gave, against version 6's run above:

| Goal | Noise lift | Unnecessary | Overshoot | Missed | Device | Median shortfall |
|---|---|---|---|---|---|---|
| flat, v6 | 4/15 | 0/12 | 4/36 | 18/24 | 0/14 | 0.03 dB |
| flat, v8 | 4/15 | 0/12 | 8/36 | 19/24 | 0/14 | 0.01 dB |
| gentle, v8 | 5/15 | 0/12 | 1/36 | 21/24 | 0/13 | 0.49 dB |
| tight, v8 | 4/15 | 0/12 | 11/36 | 19/24 | 0/14 | 0.01 dB |

The extra flat overshoots are mostly hairlines: `filtered/1` +0.05 dB over one bin,
`cancellation/3` +0.03, `filtered/3` +0.26 at 6 Hz, `natural_droop/2` +0.31 at 54 Hz. The
gentle goal's fifth noise lift is `correlated_noise/2` (parametric, 9.4 dB). The two questions
v3 left open before a held-out run, and two the run raised, were settled by the user:

1. **The cancellation recipe (settled: cancel in phase).** The recipe passed the LFE's low band
   through a causal fourth-order Butterworth, whose phase turns through -180 degrees near its
   60 Hz corner, so the inverted copy added there. The mix's change was 1 - d·H(f): a deficit
   only below about 28 Hz (-6 to -8 dB at 8 Hz) and +3 to +3.8 dB at 40-71 Hz. It barely reached
   the reference (+0.8 to 1.0 dB at 80 Hz, nothing above 100 Hz, the median unmoved), so moving
   the corner to 40 Hz would only have moved the bump. The designer levelled the band below up
   to it (`cancellation/2` +1.56 dB over at 7 Hz). v4 cancels through a zero-phase low-pass, so
   the change is 1 - d·|H|², a plain deficit with no bump. Under v4, `cancellation/1` designs
   and scores clean, `/2` abstains (missed) and `/3` falls short by a median of 1.3 dB.
2. **`finite_stopband/2`'s gentle overshoot (settled: the designer, not the instrument).** It is
   +0.65 dB over at 16.6 Hz. E10 pivots at 32.6 Hz; the designer's anchor, read from the observed
   spectrum (whose chance shape stands +0.4 dB at 30-36 Hz), is 29.0 Hz. That difference accounts
   for 0.25 dB of the excess (1.5 × log2(32.6/29.0)). The rest is the design's own: at 16.6 Hz it
   stands 1.9 dB over the designer's own goal, which its judge accepts. A residual pivot
   difference of this size is one realisation's scatter, which the designer cannot avoid without
   seeing the source, so the instrument stays as it is.
3. **The tight goal (settled: the tolerance is the act threshold).** In the pipeline the goal
   tolerance only decides whether a low end needs anything (`_worth_correcting`,
   `_lifts_beyond_goal`), so the tight goal's designs were the flat goal's filter for filter on
   every case, and v3's scoring against 0.75 dB counted the fit's ordinary 0.3-1 dB ripple as 11
   overshoots. v4 scores overshoot and missed recovery against `e10.ACCURACY_DB` (1.5 dB) at every
   goal, in both halves (`tools/e10_cases.py` too). Whether the designer should honour a tighter
   tolerance in its fit is a separate decision change, not an instrument question.
4. **The decision rule's 5% bound (settled: no worse than before).** See the decision rule above.
   Overshoot still counts any bin over the line; the user kept that as declared.

**Under v4** (cancellation designed again, every other family rescored from the run's filters):

| Goal | Noise lift | Unnecessary | Overshoot | Missed | Device | Median shortfall |
|---|---|---|---|---|---|---|
| flat | 4/15 | 0/12 | 5/36 | 21/24 | 0/13 | 0.21 dB |
| gentle | 5/15 | 0/12 | 1/36 | 21/24 | 0/14 | 0.69 dB |
| tight | 4/15 | 0/12 | 5/36 | 21/24 | 0/13 | 0.21 dB |

* Tight now scores as flat does: same designs, and on these seeds the stricter act threshold
  changes no case's need for a correction.
* The flat overshoots left are `nonstationary_floor/1,3` (row 33) and the hairlines on
  `filtered/1,3` and `natural_droop/2`.
* Missed recovery is close to saturated (21 of 24): most misses are a design that stops above a
  truth band reaching 5 Hz under the synthetic 1e-5 white floor, with a median shortfall of 0 dB
  (as the first run found). The shortfall is the more telling figure for gating recovery.

Nothing now stands between E10 and freezing its first gated change. Row 33 (the pumping floor)
is the candidate.

## The pumping floor (v5, 28 October 2026)

TODO 33 recorded `nonstationary_floor` lifted 27-33 dB on every seed and goal. Measured below
half its corner on seeds 1-3, against the positives that leak programme there (scratch
evidence):

| Below half the corner | Floor swing (p5 to p99) | Contrast | Boost ceiling | Partial coherence |
|---|---|---|---|---|
| `nonstationary_floor` 1-3 (scored as noise) | 36-39 dB | 32-36 dB | 29-32 dB | -0.21 to 0.01 |
| `finite_stopband/1,2`, `filtered/1` (scored as programme) | | 30-40 dB | 28-34 dB | -0.05 to 0.02 |
| `coloured_floor` 1-3 (stationary) | 0 | -2 to 2 dB | 0-0.4 dB | about 0 |

The recipe's `0.25 + level / mean` made the floor rise about 37 dB inside every event and nowhere
else. That is not a compressor's pumping (a few dB, and under gain reduction the floor falls while
loud passages play); it is noise that exists only inside programme events. Every measure the
evidence model has reads it as the leaked programme it resembles, and under the content principle
it is content. No rule could refuse it without refusing `finite_stopband`'s and `filtered`'s
legitimate lifts. Settled by the user: v5 replaces it with the pumping floors a mix can carry,
`tracking_floor` and `breathing_floor` (2-6 dB, drawn), counted as noise, and keeps it as
`event_locked_floor`, reported and kept out of every pooled tally (`e10.REPORTED`), as the frozen
protocol's `natural_bass_light` is. `tracking_floor` takes `nonstationary_floor`'s place in
`FAMILIES`, so no other family's draws move; the two new families are appended.

A first experiment on the old recipe's own floors, flat goal, confirmed the depth decides it:
modulated at most +6 dB with the programme, seeds 1-3 got 8.1 dB (parametric), nothing and
3.06 dB; breathing by up to 6 dB, all three abstain.

**v5's floors, seeds 1-3, at design version 8** (flat; tight is identical, gentle selects nothing):

| Case | Selected | Noise lift | Beyond 1/3 octave under the truth band |
|---|---|---|---|
| `tracking_floor/1` (3.7 dB) | parametric | 13.9 dB | 4.0 dB |
| `tracking_floor/2,3` | abstains | | |
| `breathing_floor/1` | abstains | | |
| `breathing_floor/2` (5.0 dB) | parametric | 10.8 dB | 9.9 dB |
| `breathing_floor/3` (3.1 dB) | parametric | 13.0 dB | 2.9 dB |
| `event_locked_floor/1-3` (reported) | flatten (flatten, counterfactual at gentle) | 17.9-33.6 dB | 17.9-30.5 dB |

None of the realistic lifts reads noise as programme. At the bottom of the truth band the
programme needs 32-51 dB and the design gives 11-16: these are partial restorations of the
programme above the floor. They split two ways:

* **The skirt of a restoration the target asks for.** On `tracking_floor/1` and
  `breathing_floor/3` the design follows its evidence-priced target within about 1 dB; the lift
  peaks within a third of an octave under the truth band's edge, where a 15-17 dB restoration
  must roll off, and is 3-4 dB further down. v4's `natural_droop/1` (12.9 dB, 0 beyond a third of
  an octave) and `correlated_noise/2` (9.4 dB, 1.7) are the same. The real-texture half already
  allows for this: `noise_replaced` counts a boost only half an octave under its corner. Whether
  the synthetic half should allow the same transition is an open instrument question.
* **A fit over its own target below the floor.** On `breathing_floor/2` the target is held at
  3.4-8.6 dB over 5-8 Hz (tracking floor 6.7 Hz); the design, a single shelf (17 Hz, +9 dB,
  Q 2.94), gives 9.8-11.4 dB there, up to 6.4 dB over the evidence-priced target, with a -6 dB
  ripple dip at 25 Hz, and the judge passes it. This is the pipeline finding TODO 33 now tracks.

## The skirt and the cases it leaves (v6, 28 October 2026)

Settled by the user: noise lift counts only more than half an octave under the truth band's
bottom (`e10.TRANSITION_OCTAVES`), the allowance the real-texture half's `noise_replaced`
already makes; a case with no truth band counts every noise-only bin. Rows keep the whole
region's maximum as `noise_lift_skirt_db`.

The floor families on development seeds 1-12, three goals, design version 8 (scratch evidence):

| Family (flat) | Noise lift | Overshoot | Missed | Median shortfall |
|---|---|---|---|---|
| `coloured_floor` | 0/12 | 0/12 | 10/12 | 0.14 dB |
| `tracking_floor` | 1/11 | 0/12 | 11/12 | 0.42 dB |
| `breathing_floor` | 1/12 | 3/12 | 8/11 | 0.08 dB |
| `event_locked_floor` (reported) | 12/12 | 8/12 | 4/12 | 0.0 dB |

The realistic floors' counted lifts are four of 72 rows: `tracking_floor/1` flat (4.0 dB),
`breathing_floor/2` flat (9.5), `breathing_floor/5` gentle (7.7) and `/9` gentle (3.3). The two
large ones share a mechanism, and it is not the floor: **the judge passes the candidate that
fits worst.**

* `breathing_floor/2`, flat: four three-section candidates fit their targets within 1.1-2.1 dB
  worst-case and stand 0.3-1.7 dB over the evidence ceiling, and each fails the cliff check (84-124
  dB/oct near 10 Hz). `parametric`'s single shelf (17 Hz, +9 dB, Q 2.94) misses its target by
  6.4 dB and stands 5.5 dB over the evidence ceiling across 0.76 octave; it is too smooth to make a
  cliff, so it passes and is selected.
* `breathing_floor/5`, gentle: `parametric` (three sections, 1.5 dB fit error, 1.9 dB excess)
  passes, and so do three single-section candidates 8.7-8.8 dB off target and 9.0 dB over the
  ceiling at an unsupported bin; selection takes `counterfactual/35dB`, one of them.

Nothing refuses a design for exceeding its evidence: the over-lift bar is measured from the goal
(`accept.overlift_bar_db`: the higher of the goal and the material, plus the level tolerance),
so below a floor 30-50 dB under the goal it allows that much, and `evidence_excess` is reported
only. That is TODO 33's candidate change.

## Bounding lift by the evidence: three experiments, none adopted (29 October 2026)

TODO 33's candidate change was to hold the design to the evidence-priced target. Three forms of
it were built in a worktree (branch `experiment-evidence-bound`, uncommitted) and measured on
development seeds 1-12 at design version 8 and on the refit probe's 54 titles and variants. The
decision was set in advance: adopt only a strong positive on balance.

* **A, the fitter's one-sided bound at the licence plus 1.5 dB** (as library fix 4 bounds the
  over-lift bar). It cleared the counted noise lifts, but moved 51 of the refit probe's 54 titles,
  with large fit-error regressions. It also sent `parametric` through `_fit_all`, which lost
  `natural_droop/1`'s design. Its first run was invalid: the licence reads 0 dB outside the
  envelope range (below 4.88 Hz), which bounded lift to 1.5 dB beside a 35 dB target, so only
  measured, unexcluded bins were bounded from then on.
* **B, a judge check refusing a design more than 1.5 dB over the licence anywhere.** Noise lift
  fell to 0 of 42 counted rows at every goal, but missed rose by 3 at every goal, because clean
  `parametric` designs 2.2-2.6 dB over were refused. 20 of 54 refit titles moved, all variants.
* **C, as B but only over an excess at least half an octave wide.** Across v8-accepted E10
  designs, the peak excess does not separate noise lift from clean designs. Its width does:
  the noise lifts are 0.76 octave or wider, the clean designs 0.35 or narrower. On the
  development seeds, C took noise lift from 2 of 42 rows to 0 at every goal. Missed went
  46 → 47 (flat), 49 → 48 (gentle) and 47 → 48 (tight): `tracking_floor/1` now declines.
  Median shortfall improved. Overshoot was unchanged at flat (6) and tight (6) but rose 1 → 2 at
  gentle: `breathing_floor/5` falls back to a three-shelf high-Q cascade with 5.9 dB of
  publication drift, and that cascade makes a 3 dB bump 0.16 octave wide. That breaks the
  decision rule's first condition. The refit probe moved 11 of 54, all variants and no real
  title.

**The library decided it.** Every v8 record stores each candidate's `evidence_excess`, so C's
check can be applied to beqdesigner's 1,069 version 8 records without a rerun:

| Excess over | at least 0.5 octave wide | 0.75 octave | 1 octave |
|---|---|---|---|
| 1.5 dB (C) | 96 refused / 14 newly decline | 53 / 7 | 21 / 2 |
| 2 dB | 68 / 10 | 38 / 5 | 19 / 1 |
| 3 dB | 34 / 5 | 16 / 2 | 9 / 0 |
| 4 dB | 17 / 3 | 8 / 2 | 3 / 0 |

C would refuse the accepted design for 96 of 1,033 designed titles (9%). 82 of them would fall
back to another passing candidate, mostly from flatten to `counterfactual/25dB`, and 14 would
decline. A narrower check changes fewer titles, but it also misses E10's own cases
(`tracking_floor/1` is 1.8 dB over). None of the 11 probe titles is affected.

Twelve of the 96 corrected curves were inspected: the eight largest excesses and four from the
typical 1.5-3 dB range.

* **The large excesses lift below a diagnosed tracking floor, mostly on older titles.** Whether
  what lies below is noise is not established (see below). Wait Until Dark (1967) lifts everything below its 22 Hz noise floor by 25-30 dB, to about the
  programme's level. White Heat (1949) lifts about 30 dB below its 40 Hz floor. The King and I
  (1956) lifts its noise and a 9.7 Hz tone by 10 dB, and How to Marry a Millionaire (1953) its
  floor and hum by 5 dB. Each fallback lifts less there. But in the two worst cases the licence itself
  allows 20-25 dB below the noise floor, and the design stays inside it almost everywhere. C
  refuses them only for a 5-6 dB excess at the 4.9 Hz edge, so a design that respected that
  edge would pass with the whole noise lift. Flatten's target note names the mechanism:
  "noise floor binds … held flat", so the target holds the restoration's full lift flat into
  the noise.
* **The typical excesses are a smooth fit against a ragged licence, on content that tracks
  the programme.** The Little Mermaid, Underground, To Die For and Jackie Brown all have no
  diagnosed noise floor, and their fallbacks are no better: To Die For's gives up about 10 dB of
  restoration. Any Given Sunday (1999) is refused over a dip in the licence at 10-11 Hz and has
  no fallback. A Few Good Men is refused over the same dip, and its fallback lifts about as much
  there. The Parent Trap (1961) would decline over a 6 dB excess at 5-8 Hz, just above its
  7.2 Hz floor.

So excess over the licence is the wrong thing to refuse on. Most of what it catches is harmless
mismatch between fit and licence. The library's large lifts below a diagnosed tracking floor sit
inside a licence that permits them, and it catches those only by accident. None of A, B
or C is adopted; the code stays on its branch. The scratch evidence is `library_gate.json`,
`gated_titles.json` and `gated_*.png`.

**How common lift below a noise floor is in the library.** For each v8 record, the accepted
design's median lift was measured from 4.88 Hz to half an octave under the diagnosed
`noise_floor_hz`, the same allowance E10 makes. That was compared with its median lift over the
octave above the floor (scratch `nf_count.json`). 379 of the 1,033 designed titles have a
diagnosed noise floor. 304 of them have measured bins under it.

| Median lift below the floor over | Titles | of which another passing candidate stays under it |
|---|---|---|
| 3 dB | 247 | 86 |
| 10 dB | 151 | 74 |
| 20 dB | 34 | 25 |

141 of the 151 over 10 dB are flatten. Its lift below the floor is about what it is above, which
is the "held flat" target at work. This is not confined to old titles with high floors. The
largest are modern films with floors at 7-12 Hz: Moana (2016) lifts 37 dB under an 8.4 Hz
floor, and Silver Linings Playbook (2012) and Creed III (2023) lift 33 dB. They sit alongside
White Heat, Wait Until Dark and Marnie, whose floors are at 22-40 Hz.

**These are not counts of noise lift.** `noise_floor_hz` is a legacy name for the mix tracking
boundary (`diagnose.Diagnosis`): the first band, searching down from the plateau, whose
envelope fails to track the passband's. A band can fail that without being noise: deep-bass
effects that move independently of the plateau, or content too sparse to correlate. A single
failing band ends the search, even if what lies below tracks again. A band can also pass
without being content, since event-locked leakage tracks. The contrast licence often disagrees
with the boundary: on Wait Until Dark it allows 20 dB below it. So lifting below the boundary is
noise lift only where the boundary is right and what lies under it is noise, and nothing yet
shows how often that holds. No rule on lift below the floor is worth designing until the floor
detection is validated as a noise detector, on truth (E10's synthetic families know where
their noise is) and on real titles, against an independent test of noise. That is TODO 33's next
step.

## Is the tracking boundary a noise detector? (29 October 2026)

**On E10's truth.** `diagnose`'s `noise_floor_hz` was scored against each development case's
truth arrays (seeds 1-12, all 14 families; scratch `floor_truth.json`). The truth boundary is the
bottom of the truth band, where the programme stops standing 3 dB over the noise.

| Family | Floor found | Median position against the truth | Range |
|---|---|---|---|
| `coloured_floor` | 12/12 | 0.30 octave low | 0.06-0.62 |
| `tracking_floor` | 12/12 | 0.42 octave low | 0.07-1.12 |
| `correlated_noise` | 12/12 | 0.25 octave low | 0.01-0.62 |
| `breathing_floor` | 12/12 | 0.24 octave low | 0.02-0.50 |
| `finite_stopband`, noise-exposed | 3/6 | 0.83 octave low | 0.67-1.06 |

On every noise-exposed case where it finds a floor, the boundary sits below the truth, never above
it. So it treats the band just above it, which is noise, as tracking content, and a restoration held
flat from there lifts that noise. Half of `finite_stopband`'s exposed cases (−60 dB leakage onto
noise) find no floor at all. The opposite error appears on `partial_channels`, a high-pass on the
LFE alone with content in the mix down to 5 Hz. Three of its 12 cases get floors at 14.9, 17.0 and
27.2 Hz, so a design held flat from there withholds a restoration the content supports. The other
false floors sit at 4-6 Hz, at the bottom edge of the analysis band. `event_locked_floor` finds a
floor once in 12, as the content principle intends.

**An independent test, calibrated on E10.** Two statistics are measured per sixth-octave band
below the plateau, from the mono mix in 4.1 s frames (scratch `noisestat.py`):
* **r, loudness scaling:** the band's level rise from the 40-80th to the 95-100th percentile of
  plateau loudness, as a fraction of the plateau's own rise. Content scales (about 1); additive
  stationary noise does not (about 0).
* **q, steadiness:** the band's mean frame power over its 10th-percentile frame power, in dB.

On the development cases' truth (bands where the noise is 3 dB over the programme, or the
programme 3 dB over the noise), noise bands have median r 0.02 and q 4.5 dB (90% under 6.1).
Content bands have median r 0.93 and q 41 dB (90% over 6.2). Calling a band noise when r < 0.55
and q < 9.5 dB catches 671 of 775 noise bands, and all of them outside `stationary_noise`, whose
cases have no programme and whose plateau is noise too. It calls 94 of 3,073 content bands
noise, 76 of them in `continuous_bass`, a steady drone that no statistic of this kind can tell
from noise. Event-locked noise reads r 0.84 and q 25 dB, content by the principle.

**On the library.** The test was run on the `mono.wav` of the 300 designed titles that have
measured bins under their boundary, plus 40 titles without one as controls (scratch
`library_noise.json`, `library_noise_summary.json`). It was read over the bins half an octave or
more under the boundary.

| Under the boundary | Titles | Median year | Median q | Steady like E10's noise (q < 9.5) |
|---|---|---|---|---|
| Scales with the programme (r ≥ 0.8) | 83 | 2011 | 42.5 dB | 0 |
| Partly (0.55 ≤ r < 0.8) | 68 | 2011 | 40.4 dB | 0 |
| Does not scale (r < 0.55) | 149 | 2000 | 27.1 dB | 10 |

* **About half the boundaries (151 of 300) sit on content.** What lies under them rises with
  the programme and is far from steady. That holds for the largest lifts in the earlier count:
  Moana (r 1.2, q 54), Creed III (1.09, 50), Juror #2 (0.87, 46). Those designs restore content,
  not noise. This is the `partial_channels` error, at library scale.
* **Only 10 titles look like E10's noise**, with what is under the boundary neither scaling nor
  steady: Mary Poppins, Night Moves, On the Waterfront, The Exorcist and others. Where both
  statistics find the noise, the median boundary is 0.12 octave above it (28 titles; 10-90%:
  0.47 octave below to 1.12 above).
* **The other 139 do not scale but are not steady either**, among them Wait Until Dark (r 0.15,
  q 16.7) and How to Marry a Millionaire (0.21-0.25, 12-24). That fits noise that varies over a
  programme (reel changes, rumble, handling) or content that moves independently of the plateau
  (effects in quiet scenes). These statistics cannot tell the two apart, and E10 has no such
  noise to calibrate against.
* None of the 40 controls has a noise boundary by this test.

So the tracking boundary calls content noise on about half the library's floored titles, and
where it is right about noise it sits too low on synthetic truth. It is not fit to gate a rule
on lift below it. What would settle the 139 is a steadiness measured locally, over a few
minutes rather than the whole programme, and a listen to a handful of them.

**Steadiness measured locally.** q was measured again within each 240 s stretch of a title,
the length of an E10 case so that the calibration carries over, and the median taken across
stretches (scratch `library_noise_local.json`). Noise that changes level between reels is steady
within one, so the 139 undecided titles should resolve if that is what they are.

| Under the boundary | Titles | Locally steady (q < 9.5) | 9.5-15 dB | Bursty (≥ 15 dB) |
|---|---|---|---|---|
| Scales with the programme | 83 | 4 | 13 | 66 |
| Partly | 68 | 2 | 9 | 57 |
| Does not scale | 149 | 27 | 37 | 85 |

Only 27 of the 149 become steady noise this way: Mary Poppins, The Exorcist and Pulp Fiction's
lower boundary, among others. 85 stay bursty within minutes (Wait Until Dark 15.5, Marnie 26.3)
while not scaling with the plateau's loudness. That fits either content that moves
independently of the plateau, such as effects in quiet scenes, or transient noise such as splice
thumps and handling on an optical track. Neither statistic can separate those, and E10 has no
transient noise to calibrate against. Where the local test finds a noise boundary (45 titles),
the tracking boundary sits a median 0.05 octave above it, but anywhere from 0.83 below to 1.27
above (10-90%). Four of the 40 controls have a local noise boundary the tracking test did not
report.

The tally for the 300 floored titles is: 151 with content under the boundary, 27 to 33 with
steady noise, 37 borderline, and 85 bursty and unresolved. Listening is the next evidence, and
the candidates are Wait Until Dark, Marnie and GoodFellas (bursty, not scaling) against Mary
Poppins and The Exorcist (steady noise).
