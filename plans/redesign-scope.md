# Say which titles a change is likely to move (TODO 34)

Proposal 23 October 2026, revised 24 October; built 25 October 2026 as contract 1.6's `POST /impact` (see [Outcome](#outcome)).

## The problem

`DESIGN_VERSION` (contract 1.4) is one number per build. beqdesigner's out-of-date filter
flags every title designed at a lower version, so each bump redesigns the whole library
(about 1,100 titles, 40-80 s each per designer). Most fixes are targeted. O2 at the knee
(TODO 31) moved 3 of the 14 low-plateau titles measured and none of the 11 baseline titles.
As a version bump on its own, it would still have asked for every title to be redesigned.

The first draft of this proposal gave each version one hand-written predicate over a run
record. That is too coarse. It says nothing about how likely a title is to move, it can't be
built from the code change itself, and a fix that can't be narrowed falls back to "redesign
everything" anyway. What's wanted is a ranked list of the designs most likely to be affected.
The author reads the list and decides whether to redesign, and which titles.

## The model as features

1. **The pipeline is a fixed set of named features.** A feature is one decision or one
   computed quantity that an answer can depend on. Each has an id, the code that implements it
   (modules or functions) and a *reliance* reader over a run record. The reader says how much
   this design's answer depends on the feature, from 0 to 1. Where the feature compares a value
   against a threshold, it also gives the *margin*: how far the recorded value sat from the
   threshold, in the threshold's own units. Roughly 25 features cover the pipeline as it stands:

   | Stage | Features (examples) | Reliance read from |
   | --- | --- | --- |
   | analysis | reference plateau and O2, noise floor, filter floor, filtered detection, tracking, loud events, positive-correction support | `diagnosis` (plateau, floors, `is_filtered`), `evidence_notes` (blockers) |
   | targets | `flatten`, `counterfactual`, `parametric`, evidence pricing | which candidates exist; `unpriced_target_db` against `target_db`; `evidence_excess` |
   | fit | optimiser input (row 28), realisation and publication | every fitted candidate; `fit_error_db`, `target_fit` |
   | judge | one feature per check: cliff, tilt, level, goal, wobble, roughness, turnover, drift, extent, recovered fraction, DC margin, device error, section contribution | each candidate's `verdict`, which records every measured figure beside its pass or fail |
   | selection | winner choice, confidence, headroom | `accepted`, `confidence`, `headroom` |

   A design relies on a feature when that feature decided or shaped its answer. For a decline,
   that is the blocker that fired or the failing check of every candidate. For an accepted
   design, it is the strategy that won, every check that winner passed (with its margin), and
   every check that failed a candidate ranked above the winner.

2. **Every change says which features it touches, and by how much.** A file in the repository,
   `beqforge/impact.toml`, takes one entry per answer-changing commit. Each entry names a
   change id and, for each feature it touches, the kind of change:
   * **threshold**: the old and new values (for example cliff tolerance 2.0 to 2.5 dB/oct).
     A record whose margin lies between the two will change its verdict for certain. A record
     just outside them is likely to.
   * **behaviour**: the code changed how the feature computes. The *degree* is the share of
     reliant cases that moved in the regression check, and how far they moved. It is measured,
     not guessed: the probe, the protocol and the corpus already run every case through before
     and after.
   * **all**: the feature reaches every design that uses it, for example the fit's input
     (row 28). Even this narrows the list: a title declined in analysis never reached the fit.

   The delta between two commits is the set of entries in `impact.toml` at the later commit
   that aren't in it at the earlier one (`git show A:beqforge/impact.toml`). This uses no
   commit hashes, so the file can name its own change, and it works across any range,
   including one spanning several releases.

3. **The regression check enforces the declaration.** It checks from two directions:
   * **From the code:** every function a commit changes, found from the diff hunks and their
     enclosing definitions, belongs to some feature. A changed function whose feature isn't
     declared fails the check. A function that no feature owns fails too, so the ownership
     map can't fall out of date.
   * **From the results:** every probe title, protocol case or corpus case whose verdict,
     winner or target moves must rely on a declared feature. A case that moved without
     relying on one means the declaration is incomplete, or a reliance reader is wrong.

   The measured degree is written into the entry as part of the regression check, alongside the
   outcome that already goes into `TODO.md` and `plans/`.

4. **The search ranks the library.** `beqforge impact A..B RECORDS...` reads each record and
   scores it against the delta. For each touched feature, the score is the change's degree,
   weighted by the record's reliance on the feature and, for a threshold, by how close its
   margin is. A record's score is the highest of these. The output is a ranked list:
   * **will move:** a recorded margin lies between a threshold's old and new values;
   * **likely:** high reliance on a feature with a high measured degree, or a margin near
     the threshold;
   * **possible:** some reliance on a touched feature;
   * the remaining titles as a count.

   Each listed title shows which features put it there and why (for example "cliff passed by
   0.4 dB/oct; the tolerance moves by 0.5"). A record that predates the reliance a feature
   needs, or that doesn't hold what its reader reads, is listed as **unknown**, never left out.
   The author picks titles from the list. Nothing is redesigned automatically.

## Validation before relying on it

Comparing beqforge's answers across versions is not calibration against the catalogue, so this
is allowed. The plan was to score the library's v5 records against the 5-to-6 delta and compare
the ranking with what the v6 redesign moved. That doesn't work as planned, for two reasons
found on 24 October 2026:

* **The v5 records are gone.** A record is named after its request's digest and the library
  sends the same request every time, so each v6 record overwrote its v5 one (1,284 of 1,335
  files now hold 0.2.10). Records must not be overwritten by a later design. Since 0.2.11 they are named
  per request and design version and carry the identity themselves (TODO 35).
* **The library's flips mix code and machine.** `design_version` names an algorithm on one
  machine (`designer-interface.md` §3), and before row 28 the fit wasn't reproducible across
  processors. v5 was designed by two builds on two machines, so a v5-to-v6 flip there isn't
  evidence of a code change by itself.

The test is therefore a rerun of both commits on one machine, which yields records for both
sides. The 14 titles that went from designed to declined were rerun this way (see TODO 35):
all of them move, and the change behind every one of them is row 28. For a behaviour change
like row 28's, which re-rolls the fitter's choice among near-equal optima, the declared degree
is what matters: 31 of 1,287 titles flipped between designed and declined in the library (the
14 losses confirmed as row 28, the 17 gains not yet rerun), a share no reliance reader could
have picked out in advance. A change like that is "all" until TODO 32 makes the fit's choice stable. If
the will-move and likely tiers don't hold nearly every title that moved, the scheme isn't
ready, whatever the regression check says.

## What it asks of each side

* **beqforge:** the feature catalogue and its reliance readers; `impact.toml` and its
  enforcement in the regression check; and a `reliance` section in the run record. That section
  holds, for each feature, the value it compared, the threshold and the branch it took.
  Most judge features can be read from today's `verdict`. Analysis features mostly can't: an O2
  plateau that came close to firing is only text in a blocker note, if anything. The section is
  added before the scheme depends on it, as its own design version, so old records stay
  readable as **unknown** where they lack it.
* **beqdesigner:** a title the author chose not to redesign keeps its design but needs to stop
  showing as out of date. That needs a "reviewed at version N" stamp beside "designed at
  version M", or an equivalent. §3 already says a caller "never redesigns on that alone", so
  this is an addition, not a change of meaning; beqdesigner agreed it on 24 October 2026. They
  chose a batched server endpoint over a CLI, because their service has no beqforge in it. It
  takes record paths relative to the shared root, under §7.1's rules for files by reference,
  not the absolute `run_record` paths in commentary (the frozen Windows build writes those as
  UNC paths). The route and its schema are to be drafted for their review before anything is
  built.

## Open questions

* **Feature granularity.** A coarse catalogue makes every change reach a lot of titles. A fine
  one makes the ownership map expensive to maintain. Start at the level of the table above,
  and split a feature only when the validation shows it over-including.
* **Shared code.** A change to code that several features share (the correction curve, the
  grid, `beq_common`'s filter arithmetic) touches all of them. The behaviour degree keeps the
  ranking honest when that happens, but the list will be long for such changes.
* **Settings.** A change to the server settings digest (`design_settings`) is outside this
  scheme and stays a full redesign.

## Outcome

Built 25 October 2026, in the shape above with these decisions:

* **The catalogue** is 37 features in `beqforge/impact.py` (`FEATURES`): 31 that can change an
  answer, across analysis, targets, the fit, the judge's checks, selection, the response and
  adjustments, and 6 that can't (identity, record, cache, reporting, validation, impact). Each
  owns its code as `module:qualname` globs. A test fails if any function, class field or module
  constant under `beqforge/` or `beq_common/` (1,119 today) has no owner, so the map can't fall
  out of date.
* **Changed code is found by its syntax tree, not by diff hunks.** `tools/impact.py check BASE
  [HEAD]` compares each definition's AST with docstrings removed, so a docstring or comment
  edit is not a change. It fails on a changed definition no feature owns, and, when the design
  version moved, on an answer-reaching feature the new version's changes in `impact.toml`
  don't declare. It is regression step 5 in `beqforge/AGENTS.md`. On version 7's commit range
  it names `fit.choice`, plus `fit.input`, `selection` and `judge.verification` for the
  plumbing, declared `unchanged` with how that was shown.
* **Reliance is read per outcome class** for now. Four classes, from what every record holds:
  declined before any fit, declined after it, designed with some candidate failing, designed
  with all passing. A behaviour change's degree is the share of each class that moved.
  Strategy and check features also say which candidate they reached. No reader returns a
  threshold margin yet, so a threshold change makes every reliant record `unknown`: it
  fails safe, and margins are the next step (the `reliance` record section above).
* **Old records are identified by the release that wrote them.** Before 0.2.11 a record didn't
  carry its identity. `impact.toml`'s release table matches its fingerprint's revision: a frozen
  build by commit, anything else by source digest, since an image or wheel has no git. The
  settings digest is recomputed from the record's params repr, parsed as literals, never
  evaluated. 1,284 of the library's 1,354 records are 0.2.10's (728 from the Windows build, 556
  from the image), so the current library can be scored. The other 70 predate design versions
  and are `unknown`. `impact.toml` scores records from version 6 on (`since`).
* **The endpoint** is `POST /impact` on the designer server, on the handler's thread. `/health`
  reports `"impact": true` with a shared root. `CONTRACT_VERSION` is 1.6. 500 library records
  are scored in 15 s over the share. `/health` and `/impact`'s request and response validate
  against beqdesigner's 1.6 schemas.

**Version 7's degree, measured on the library.** v6 records were rerun on one machine at
117575c (version 6) and at 1600ae2 (version 7), from requests identical to the library's.
A record moved if it swapped between designed and declined, changed strategy, or its cascade
moved by more than 1 dB at 5-50 Hz. The v6 rerun reproduced the library's own records on 57 of
58 titles (Blazing Saddles declined here where the library designed it), so machine noise is
small against these shares.

*25 October 2026, after 0.2.12:* `impact.MOVED`'s cascade line is now 20/f dB, capped at 2 dB at
10 Hz and below (1 dB at 20 Hz, 0.5 dB at 40 Hz), not a flat 1 dB: a dB deep in the boost does
not matter, the same dB near the top of the band does. The designed classes were recounted on
beqdesigner's larger redesign sample (library v6 records against their v7 redesigns): designed
with failures 16 of 35 (15 by the flat line), all passing 22 of 60 (15). The 8 that only the new
line counts all moved 0.4-1.0 dB at 26-50 Hz. The two declined classes can only move by being
designed, so the line does not reach them and their counts below stand.

| Class (library count) | Measured | Moved |
| --- | --- | --- |
| declined after the fit (34) | all 34 | 18 (13 of row 35's 14, 5 of the other 20) |
| designed, some candidate failing (349) | 15 at random | 7 |
| designed, all passing (668) | 15 at random | 2 |
| declined before any fit (236) | 8 at random | 0 |

Two signs that the movers are real changes: the declined titles that moved are row 31's group 3
and near misses (Amy, Bugonia, Return to Seoul, The Exorcist, Bill & Ted's Excellent
Adventure), and the designed ones moved 1.2-3.4 dB or changed strategy. Nothing in the record
separated the movers inside a class. Declines that missed one check moved 15 of 26 times,
against 3 of 8 for several. That's too few to justify a finer reader.

**Does it pass this plan's own bar?** For version 7, no. The likely tier (the 34 post-fit
declines) holds 18 of the sample's 27 movers. The rest are in `possible`, at 0.47 and 0.13.
What the scheme does show:

* The 236 analysis declines are `unaffected`, correctly: none of the 8 measured moved, and none
  reaches the fit.
* The ranking holds. Redesigning by score, the first 383 records (likely, then designed with
  failures, 30% of the library) hold about 182 of the roughly 270 expected to move.

A change like row 32, which re-rolls the fit itself, can't be narrowed further by outcome
class. That's the "all" case this plan foresaw. The scheme will pay off on narrower changes
(a threshold with margins, a strategy-specific fix) and as the fit becomes stable.

**Left:**

* threshold margins in the record (the `reliance` section), as their own design version;
* the regression check's second direction, every moved case relying on a declared feature,
  which needs reliance read from the probe's output, not only from records;
* splitting a feature when a validation shows it over-including.

### Agreed with beqdesigner, 25 October 2026

Both users agreed the following, and beqforge built it before 0.2.12:

* **The score is an estimated probability of moving**, measured, so a caller can sum scores
  into expected movers above any cut-off. Changes combine as independent, 1 − ∏(1 − p). A
  `behaviour` or `all` touch declares its `basis`, per outcome class [moved, measured], and its
  score is their ratio. Each `changes` item in the response carries that `basis` and `moved`,
  beqforge's own definition (`impact.MOVED`, counted by `tools/impact.py moved`).
* **A threshold is scored exactly from the record, or not at all.** Every verdict records each
  check's figure against its bar (`Verdict.margins`), and every candidate records each fit
  `_choose_fit` had, with its margins and lift (`Candidate.fit_options`). A threshold scores
  `will_move` when it flips a verdict that decides the answer: the winner's, a fit judged
  before the kept one, or a decline's candidate that failed only that check. It's `unaffected`
  when it flips none. It's `unknown` (`no_figure`) when the record predates margins, or when a
  losing candidate would start passing, since the record can't rank it. The invented "near"
  scores are gone. Margins change no answer: rejudge probe unchanged at `--tol 0` (11 of 11)
  and refit probe unchanged against cd48850 (0 of 54 titles moved).
* **`unknown_reason`** on each unknown result: not_found, unreadable, outside_root,
  not_a_record, unknown_build (the library's 70 pre-design-version records), older_than_data,
  other_settings, newer_version, no_figure.
* **Verification before a cut-off** (beqdesigner's step 4): after 0.2.12 ships, beqdesigner
  redesigns 105 titles that neither side has measured, drawn with a fixed seed and interleaved
  so any prefix is proportional: 35 possible at 0.47, 60 possible at 0.13, and 10 unaffected.
  The list is `/media/beq/triage/impact-step4-sample.json`. The person picks the cut-off for the
  rest of the library from the measured rates, and the counts are folded back into
  `impact.toml`, which changes scores but no design.
