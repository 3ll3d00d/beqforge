# E10: a fresh validation protocol for the content goal (v3)

**Protocol written 22 October 2026; its instrument is built (`beqforge/e10.py`, `tools/e10_run.py`, `tools/e10_cases.py`) and the title partition frozen (`plans/e10-titles-v1.json`). The first development run revised the instrument to v2, and the tilted goal's pivot was settled in v3 (below)** (TODO row 3). This is the
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
| **Noise lift** | The corrected noise spectrum rises more than 3 dB above the uncorrected noise anywhere programme sits below the noise in the truth (the truth arrays say where). | safety |
| **Unnecessary intervention** | Any selected filter on a case whose truth is already within the goal and its tolerance across the truth band. | safety |
| **Overshoot** | The corrected programme rises more than the goal tolerance above the goal, or above the uncorrected programme where that already stood over the goal, anywhere in the truth band. | safety |
| **Missed recovery** | On a case with attenuated programme, abstaining, or a corrected programme still below the goal by more than the goal tolerance over more than a third of an octave of the truth band. | accuracy |
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
| `nonstationary_floor` | As `coloured_floor`, the floor level varying by scene (rising with programme level, as a compressor's pumping would). | positive, noise-lift exposure |
| `correlated_noise` | The same noise in every channel (a mastering hiss or hum bed), so it tracks across channels like programme. | negative below the programme's own corner |
| `finite_stopband` | Programme high-passed with a stopband floor of -40 or -60 dB (a filter, not a cut-off), no added noise. | positive down to where the stopband meets the floor |
| `partial_channels` | The high-pass on the LFE only, or on the mains only. | positive; the restored channel must carry it |
| `cancellation` | Mains and LFE partly out of phase below 60 Hz. | the mix's low band reduced by cancellation: under the content principle still programme, so computed like a droop |
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
   not increase, pooled or in any family, and their pooled upper bounds stay at or below 5%.
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
