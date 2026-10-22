# E10: a fresh validation protocol for the content goal (v1)

**Protocol written 22 October 2026; nothing in it is built or run yet** (TODO row 3). This is the
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
| **Overshoot** | The corrected programme rises more than the goal tolerance above the goal anywhere in the truth band. | safety |
| **Missed recovery** | On a case with attenuated programme, abstaining, or a corrected programme still below the goal by more than the goal tolerance over more than a third of an octave of the truth band. | accuracy |
| **Device failure** | The published response departs from the cascade's designed response by more than `max_drift_db`. | accuracy |

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

Extending `harness.corpus_case`. Each family is a recipe drawing every parameter from its seed;
the recipe states its truth band and whether each goal makes it a positive or a negative.

| Family | Construction | Negative or positive |
| --- | --- | --- |
| `broadband` | As the corpus's: flat programme, no filter. | negative (within the goal) |
| `sparse_dialogue` | Programme events rare and quiet, mid-band only. | negative |
| `stationary_noise` | Coloured noise only, no programme. | negative |
| `coloured_floor` | Programme high-passed at 15-40 Hz, order 8-16, then a floor whose spectrum is pink, brown or codec-shaped (a lossy encoder's low-band noise, from a recipe), 30-60 dB below the programme. | positive above the corner, noise-lift exposure below |
| `nonstationary_floor` | As `coloured_floor`, the floor level varying by scene (rising with programme level, as a compressor's pumping would). | positive, noise-lift exposure |
| `correlated_noise` | The same noise in every channel (a mastering hiss or hum bed), so it tracks across channels like programme. | negative below the programme's own corner |
| `finite_stopband` | Programme high-passed with a stopband floor of -40 or -60 dB (a filter, not a cut-off), no added noise. | positive down to where the stopband meets the floor |
| `partial_channels` | The high-pass on the LFE only, or on the mains only. | positive; the restored channel must carry it |
| `cancellation` | Mains and LFE partly out of phase below 60 Hz. | negative for the cancelled band (nothing to restore) |
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

Nothing above is built. In order:

1. `harness` recipes for the new synthetic families, each with its truth band, goal table and
   stored programme and noise arrays; the existing shapes unchanged.
2. A scorer for the failure classes on the published response, with corrected noise computed
   from the stored noise (row 5's scoring work).
3. `tools/e10_cases.py`: the development/held-out title lists and the real-texture recipes,
   writing each case's recipe (seed, transform, parameters), never its audio.
4. `tools/e10_run.py`: run a partition at the three goals, write one JSON per run with the
   protocol version, commit and legacy counts.
5. A first development run at HEAD, to check the instrument, recorded here. The held-out half is
   not run until the first change E10 gates is frozen.
