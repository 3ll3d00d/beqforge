# Say which titles a design version can move (TODO 34)

Proposal, not built. 23 October 2026.

## The problem

`DESIGN_VERSION` (contract 1.4) is one number per build. beqdesigner's out-of-date filter
flags every title designed at a lower version, so each bump redesigns the whole library
(about 1,100 titles, 40-80 s each per designer). Most fixes are targeted: O2 at the knee
(TODO 31) moved 3 of the 14 low-plateau titles measured and none of the 11 baseline titles,
yet as a version bump on its own it would have asked for every title to be redesigned. Only a
change like row 28's (the fit's input, which reaches every fitted candidate) really needs
everything.

## Change

1. **Each version declares its scope in code.** Beside `DESIGN_VERSION`, a table from each
   version to the change it made and a predicate over a stored run record: "may this title's
   answer differ from the one this record holds?". `ALL` where it can't be narrowed. For
   example 6 is `ALL` (row 28); O2 at the knee would have been "the mix plateau starts below
   `verify_floor_hz * 2**min_judge_octaves`", read from the record's plateau note.
2. **The predicate must over-include, and the regression check enforces it.** Every title or
   synthetic case whose verdict, winner or target moves in the probe, the protocol or the corpus
   must match the predicate, or the change isn't committed. The probe's `compare` would check
   this directly. A predicate that can only be stated loosely is still useful; one that can't be
   checked defaults to `ALL`.
3. **beqforge evaluates it, not beqdesigner.** `beqforge redesign-scope --since N RECORDS...`
   lists the records whose answer may move between version N and this build, the union of
   every version's scope in between, with each one's reason. A record from before records were
   kept, or one that doesn't hold what a predicate reads, is always listed. A server endpoint
   taking a record can follow if beqdesigner would rather ask the server.
4. **The caller carries the others forward.** beqdesigner redesigns the listed titles and
   re-stamps the rest at the new version without a run. This is the contract change: today a
   design's version means "designed by that build", and it would come to mean "the answer that
   build gives". It needs beqdesigner's agreement (`designer-interface.md` is theirs).

## Open questions

* What a record holds: the plateau, blockers, candidates and their verdicts are there; a
  predicate on something unrecorded needs it recorded first, ahead of the version that uses it.
* Settings: a server settings digest change (`design_settings`) is outside this; it stays a
  full redesign.
* Whether beqdesigner wants the list from a CLI over its records directory or from the server.
