# Say which titles a change is likely to move (TODO 34)

Proposal, not built. 23 October 2026; revised 24 October 2026.

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
is allowed. There are already 1,335 records in `/media/beq/work/records/`, each stamped with its
revision. Version 5 covers the whole library, and the version 6 full redesign now starting will
cover it again. That pair gives the ground truth without any extra work: score every v5 record
against the 5-to-6 delta (rows 1, 28 and 31's O2 at the knee, declared after the fact) and
compare the ranking with which titles' answers actually changed. If the will-move and likely
tiers don't hold nearly every title that moved, the scheme isn't ready, whatever the
regression check says.

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
  version M", or an equivalent. This is the only contract change, and `designer-interface.md`
  is theirs to agree. The search itself can be a CLI over their records directory or a server
  endpoint taking a record; they choose which.

## Open questions

* **Feature granularity.** A coarse catalogue makes every change reach a lot of titles. A fine
  one makes the ownership map expensive to maintain. Start at the level of the table above,
  and split a feature only when the validation shows it over-including.
* **Shared code.** A change to code that several features share (the correction curve, the
  grid, `beq_common`'s filter arithmetic) touches all of them. The behaviour degree keeps the
  ranking honest when that happens, but the list will be long for such changes.
* **Settings.** A change to the server settings digest (`design_settings`) is outside this
  scheme and stays a full redesign.
