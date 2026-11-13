# Outstanding work

## Status and priority

The sole backlog and plan for outstanding work, reviewed against code and history on
2026-09-30. Order reflects value to the correctness and accuracy of the generated filter:
known inconsistencies first, then independent evidence and recovery, then conditional
improvements, reporting and speed. It is not an ordering by implementation cost. A blocked
item does not prevent starting the next independent open item. **Open** means actionable,
**blocked** names missing evidence or an external dependency, and **parked** means the
evidence does not yet justify a change; each has a reason and a reopening trigger. Historical IDs
are retained so records and code comments remain traceable. Completed items are in
[implemented changes](plans/done-design-and-pipeline.md),
[research decisions](plans/research-design-decisions.md), and
[baseline evidence](plans/done-baseline-evidence.md). The
[R2a implementation record](plans/R2a-server-stage-cache.md) is complete; R2b is complete too.
Later completed records: the [design version](plans/design-version.md) (0.2.7), the
[multi-profile parameter search](plans/parameter-space-optimisation.md) (0.2.5), the
[texture yardstick](plans/texture-yardstick-sub-band.md) (implemented; its validation is row 2),
the [library review fixes](plans/library-review-improvements.md#outcomes) and
[contract 1.5's adjustments](plans/contract-1.5-adjustments.md#outcome) (both 0.2.9, design
version 5). [Run records and the log by default](plans/default-record-and-log-locations.md#outcome)
(row 27) is released in 0.2.10. Rows updated after the 0.2.9 release on 2026-10-22. Row 25 (documentation
citations) is done: the 45 references to the retired `IMPROVEMENT_PLAN.md` now cite the historical
ID alone (AGENTS.md says where each lives), and the stale contract versions are corrected.

| Priority | ID | Status | Value, work and blocker or reason for parking |
| --- | --- | --- | --- |
| 1 | Playback contract | released in 0.2.10 (design version 6) | The sub feed is now built from the request's `bass_management` (one LR4 for "Before"/"After", none for "Off", WCS or numeric headroom gains); `clip_before`/`clip_after` are named in the clipping line, not simulated. Default path unchanged (probe tol 0). On the 11 titles no verdict or winner moves; the clipping figure does, by up to 1.8 dB (Black Bag's gain reduction 1.40 to 3.16 dB). Caller propagation was already done in beqdesigner. See [the outcome](plans/playback-contract.md#outcome). |
| 2 | Texture yardstick band | open (E10 only) | Implemented: the mix's ripple is measured about a cubic over the unchanged band, so the LFE knee is trend. 9 (2009), Beauty and the Beast, Crazy, Stupid, Love and Despicable Me 3 now accept; Carrie stays declined. Probe and protocol unchanged; corpus 0/45 gate pass. Neither width-normalised form separated `broadband/5`. The degree was chosen on corpus and library data, so it needs the fresh E10 validation before it counts as settled; see [the outcome](plans/texture-yardstick-sub-band.md#outcome-17-october-2026). |
| 3 | E10 | instrument v4; ready for its first gated change | The [protocol](plans/E10-validation-protocol.md) is predeclared and its instrument built: synthetic families and scorer (`beqforge/e10.py`, `tools/e10_run.py`), the real-texture half (`tools/e10_cases.py`), the title partition frozen. The [first development run](plans/E10-validation-protocol.md#first-development-run-22-october-2026) corrected the instrument to v2, and v3 [settled the tilted goal's pivot](plans/E10-validation-protocol.md#the-tilted-goals-pivot-v3-22-october-2026). [v4](plans/E10-validation-protocol.md#version-8-baseline-and-v4-28-october-2026) reran the development seeds at design version 8 and settled the rest: the cancellation recipe cancels in phase (its causal low-pass added +3-3.8 dB at 40-71 Hz); `finite_stopband/2`'s gentle overshoot is the designer's (0.25 of its 0.65 dB is pivot scatter); overshoot and missed recovery use a 1.5 dB accuracy bound at every goal, the goal tolerance being the pipeline's act threshold (tight scored 11 overshoots of ordinary fit ripple); and the decision rule gates on no safety count getting worse, with 5% a reported target. Under v4 at version 8, flat: noise lift 4/15, overshoot 5/36, missed 21/24, median shortfall 0.21 dB. v5 replaced the pumping floor (row 33). Row 33's candidate, bounding lift by the evidence, was [measured in three forms and not adopted](plans/E10-validation-protocol.md#bounding-lift-by-the-evidence-three-experiments-none-adopted-29-october-2026). Next: choose another first change for it to gate, then the held-out run. |
| 4 | E1 | open | Add record-only scene-held-out verification: evidence independent of the material that generated the target. A gate needs a separate demonstrated benefit. |
| 5 | Steep-filter scoring | open | Implement coloured/codec-like floors and recipe-specific truth bands under E10; inspect shape failures and published-ceiling excess. Existing titles can supply programme texture. |
| 6 | Steep-filter default | blocked | Recovery improves substantially with `--content-edge`, but changing the default needs E10, the scoring above, listening judgements and more independent real steep titles. Safe House already works with the default; keep the option off meanwhile. |
| 7 | F2 / device behaviour | in progress; first hardware pilot measured | Coefficient quantisation does not establish hardware accuracy. Limit changes need measured internal arithmetic/noise/limit cycles on a named device and a capture setup; the [measurement plan](plans/F2-device-precision-validation.md) specifies Python sweep/capture, optional REW cross-checks, software controls, single-entry/full-catalogue analysis and a standalone cross-platform executable. The `beqforge-device-check` preview includes frozen manifests, capture/recovery, CLI-only miniDSP controls (minidsp-rs 0.1.12, batched through `-f`) with float32 transport attribution, staged qualification/convergence, uncertainty-aware filter checks, entry/unique-cascade frequency distributions and matched-device deltas. First verified pilot on a miniDSP 2x4 HD (USB loopback, 96 kHz): the device plays its float32 coefficients as predicted (worst 0.0074 dB, 2-200 Hz), while float32 coefficients themselves put 18.8 dB of error into a 5 Hz Q 6 peak; see the plan, section 12. First catalogue sample (50 cascades): 49 play as predicted on every bin (worst 0.0082 dB); the 50th was clipped by the device and is to be remeasured (F2a, plan section 13). Next: the `grid` and `boundary` suites on hardware to map where float32 coefficients stop representing low, high-Q filters. No Q-limit change yet. |
| 8 | Validation coverage (former TODO 10) | blocked | Broad real-programme generalisation needs the missing shapes and independently characterised paired releases listed below. Sparse titles exist; their absolute truth and wider sparse coverage remain missing. |
| 9 | Identification | blocked | Generalising `N(f)` and its fit band needs independent, varied source material, especially paired releases. Sensitivity experiments can proceed; programme-only uncertainty cannot identify the cause of a droop. |
| 10 | E4 | parked | No measured failure has been attributed to isolated ceiling holes. Reopen if unevenness or E9 excess is traced to such bins; smoothing may only reduce the raw licence. |
| 11 | F4 follow-up | parked | Both fitter-objective selection spikes lost passes/true positives. Judge several fits only with a demonstrated usable alternative discarded before `_judge`; a smaller residual is insufficient evidence. |
| 12 | F3 follow-up | parked | A fifth section moved no verdict when tried and costs more fitting. Reopen if an evidence-supported target has a demonstrated usable fit beyond four sections and no usable fit within four. |
| 13 | T2 | parked | The steep-variant audit found no swept cap binding a weak winner. Derive caps only when a binding cap demonstrably prevents a better supported result. |
| 15 | Authored features | parked | Manual `--exclude` works; no validated automatic detector exists. Reopen with real labelled features and negatives showing that detection preserves legitimate bass. |
| 16 | Dynamic processing (former TODO 11) | parked | No suspected real case has scoped a useful tripwire. Reopen when compression/limiting demonstrably compromises this correction; non-LTI processing alone does not prove every BEQ is invalid. |
| 17 | Tilted passband reference (goal/corpus follow-up) | parked | No real in-sub-band case needs a sloping reference yet; Dossier's abstention was decided. Reopen with one. Goal-aware labels are decided in [E10's goal table](plans/E10-validation-protocol.md#goals): every goal licenses lifting tracked programme and none anything else. Nearest so far: 13 Going on 30's mix tilts about −7 dB/oct above 50 Hz (bass is coherent across channels, ~200 Hz is not) and finds its plateau only through the one-sided fallback. That reference reads a 36 dB deficit below 25 Hz; each channel's own plateau reads 30-34 dB. A reference built from the channels would be 2-5 dB less generous there (see plans/done-design-and-pipeline.md, 11 October 2026). |
| 18 | Mixed-channel policy | parked | `channel_scope` is currently an unpopulated optional response field, not a computed `mixed` finding awaiting a gate. Reopen with a case where existing per-channel restoration and common pricing produce an unsuitable mix correction. |
| 19 | Fraction dial (former TODO 7) | parked | No user/title has needed partial licensed restoration as a preference; tilt and tolerance already ship. Reopen with a concrete requested outcome, then price and validate it like every target. |
| 20 | Protective corner (former TODO 9) | parked | The corner is already derived from boost cap and implied order, floored by `lowest_frequency_hz`. No case requires an independent override or different fallback alignment; reopen with one. |
| 21 | Device configuration on the wire | parked | The current contract deliberately omits device preference; server flags already configure realisation. Reopen if one server must serve different device formats/rates per request; then agree an upstream extension. Hardware validity remains F2. |
| 22 | Catalogue comparison (former TODO 8) | parked | A disagreement detector has no demonstrated accuracy benefit. Reopen with an independent discrepancy to investigate; authored filters remain comparisons, never calibration targets. |
| 23 | Performance | fit kernel released in 0.3.0 (design version 8); 0.3.1 fixes the designer image run as another user | [The measurement and outcome](plans/fit-kernel.md#outcome). The fit's search now scores each DE generation at once in the linear domain (`beqforge/fit_kernel.py`; numba, numpy fallback, bit-identical). Real runs on the 11 titles: 703 to 283 s wall, 1905 to 373 CPU-s; the `fit` stage 10x, so a title is 28 s and 37 CPU-s. A re-roll: refit probe no worse on balance, no baseline title's winner or verdict changed in real runs, protocol and corpus unchanged where gated. **Left:** the fit re-rolls near the top of the band as freely as at 10 Hz (row 37: weighting the search works, held back behind row 36); measure a library sample for the impact basis and replace it in a later 0.3 release (0.3.0's is mostly injected variants); CI's Windows and macOS executables with numba. **Repeated work removed** (not yet released; no design version bump, no answer changed): seven exact-preserving changes, one commit each, each with probe `--tol 0` unchanged and real-run records identical — the headroom peak in one-second blocks, the sub feed and its unfiltered spectra built once a run, one filtered waveform per measured candidate, a counterfactual cap's restoration reused when its boosts repeat, one flat deficit a channel, and the bootstrap's percentile read off draw counts (bit-identical; the review's prototype differed by 2e-15 dB only through the layout `std` read). Caught Stealing 54.7 to 27.5 s cold and 28.9 to 15.2 s warm in the pipeline, Black Bag 22.1 to 13.9 and 12.3 to 8.1; see [the outcome](plans/designer-latency.md). Follow-up (the mix's flat deficit measured twice a run not five times, the record's chart transfer built once a candidate: Caught Stealing warm 22.3 to 20.6 s wall, Black Bag 14.2 to 12.3, records identical). Still parked: the ~7 s a title outside the pipeline that remains (npz decompression 1.5 s, imports 0.8 s, record 0.6 s, chart curves 4 s; measure on the server path), an own DE loop. GPU offload rejected. Missed-fit search belongs to F3/F4. |
| 24 | Chart peak bias | parked | Deliberate catalogue-compatible per-bin maximum; it affects presentation only. Reopen if a reader needs an alternative percentile view; keep it distinct from the 95th-percentile evidence envelope. |
| 26 | Texture yardstick retune (library review) | blocked on E10 | The cubic (row 2) keeps the 200 Hz band only because the sub-band cap admitted one synthetic negative, `broadband/5`: chance unevenness in noise bursts, at a 2.6 dB boost. With 45 gated cases a single case moves the gate's upper bound from 0.079 to 0.118. Carrie is still declined (0.85x about a cubic, 1.33x with the cap). The reopening trigger (the library review) is met and the first measurement is done ([research item 4](plans/library-review-improvements.md#4-the-texture-retune-row-26)): the trend degree does nothing; ending the band at 80 Hz clears five of the seven review declines but lets five more gated negatives past this rule and costs three filtered cases their passband. Its full corpus run lets in exactly `broadband/5` (a false acceptance at a 2.5 dB boost; gate 0/45 to 1/45, upper bound 0.118, FAIL) and moves nothing else, `filtered` included ([the run](plans/library-review-improvements.md#4-the-texture-retune-row-26)). So the open question is the boost-weighted gate, and E10 (row 3) before adopting any retune. Retune against its declines: the band edge, the trend degree, and whether the gate weights a false acceptance by its boost. The library holds no known negative, so it can expose wrong declines but not measure false acceptances. Any retune still needs the corpus or a fresh E10 set for that, ideally with negatives built from real programme texture (row 5). See [the outcome](plans/texture-yardstick-sub-band.md#outcome-17-october-2026). |
| 28 | Fit sensitivity to arithmetic | released in 0.2.10 (design version 6) | Identification now converges to 1e-12 and the fit gets its target and ceiling quantised to 0.01 dB. The refit probe gives the same filters natively and as an emulated older CPU (0 of 11 titles moved; 28 Years Later's parametric moved before). Protocol false acceptances unchanged; corpus gate pass, `filtered` 7/9 (was 6/9). The 11 titles' corrected curves stay within 1.3 dB, though three swap between near-tied winners ([outcome](plans/library-review-improvements.md#built-a-reproducible-fit-input-22-october-2026-design_version-6)). CI's verdict on the golden: `counterfactual` matches on Linux, Windows and macOS and is back in it; `parametric` matches on the x86 runners that disagreed in 0.2.6, but macOS arm64 publishes the same filters with figures 0.06 dB apart, so it stays out ([verdict](plans/library-review-improvements.md#built-a-reproducible-fit-input-22-october-2026-design_version-6)). Left: find where arm64's parametric fit parts from x86's (needs an arm64 machine: compare the identified target, the quantised fit input and the fitted cascade unrounded) and either close the gap or accept it and say so in the golden's docstring; until then an Apple-silicon caller can see parametric figures a few hundredths of a dB from an x86 one. From design version 8 (row 23's kernel) `counterfactual` on the golden's rolloff title also publishes one step away on arm64 (36.25 Hz against 36.24, figures within tolerance), so the golden skips that case on arm64 too. Ship before the version 5 redesign (row 31) so the library is redesigned once. |
| 29 | Library review improvements | fixes released; research recorded | From beqdesigner's review of all 279 declines in its full-library run ([the proposal](plans/library-review-improvements.md), with evidence, ids and run records per item). Released in 0.2.9 as design version 5 ([outcomes](plans/library-review-improvements.md#outcomes)): fix 1 (the unmeasured floor wording), fix 2 (the fit scored on the published parameters; The Quiet Girl now designs, Bugonia now declines on coverage below 8.1 Hz), fix 3 (mains-hum notches filled), fix 4 (the fit bounded by the over-lift bar; Crazy Heart's flatten passes), O2 (an infrasonic plateau refused as the reference) and O1 (a stepping DC offset reported). Research, measured and not built ([research](plans/library-review-improvements.md#research-after-the-fixes)), now tracked elsewhere: 1b (textured passband) has no contained fix and is a plateau recalibration for E10 (row 3); 4 is row 26; 5 (per-title scene margin, which also covers item 7) is an experiment for the protocol, corpus and E10; 6 (a sub-band reference) rescues one plausible title and is not worth building on this evidence; item 8's machine dependence is row 28. Not followed up: item 3's tilt band. Fix 2 rescued The Quiet Girl, and The Smurfs and Despicable Me 3 already design here, but Blood Simple and Synecdoche, New York haven't been rerun; check them in row 31. |
| 30 | Contract 1.5: design adjustments | released in 0.2.9; one gap parked | beqdesigner can ask for a different design per title: ignore a band, a floor, a boost cap, a tilted goal, a note. `beqforge/adjustments.py` answers each; default answers unchanged (golden; probe `--tol 0`, all 11 titles). See [the outcome](plans/contract-1.5-adjustments.md#outcome). Only gap: a note's text is not written into the run record (the record holds the adjusted params, so the design replays). Reopen if a review needs the note from the record. |
| 31 | Review the version 5 library redesign | open: handoff received 23 October 2026; group 1 released in 0.2.10 (design version 6) | Outcome and evidence: [the v5 review](plans/library-v5-review.md). beqdesigner's v5 rerun (job `ef4265fa`, 1,083 titles, about 1,000 designed and 69 declined; 18 titles v4 designed now decline, about half wrongly) is triaged into four groups in `/media/beq/triage/handoff-v5.md` (queue ids, v5 records and earlier runs per title). 1 (built): O2 refused a plateau starting just under 10 Hz on the knee of a real rolloff (A Quiet Place: Day One, Elysium, Pan); it now keeps such a plateau when it reaches 20 Hz and the shortfall beneath exceeds the passband's ripple, and all three design. Probe, protocol and corpus unchanged. 2: a whole candidate rejected for missing one check by a fraction: cliff by under 3 dB/oct (Heartburn, Back to the Future, Guardians of the Galaxy, The Commitments), tilt (Guardians, The Exorcist, Alien Resurrection, Philadelphia), level (Ray), F9 residual just below the content edge (Drive, Amy). The library has no negatives, so a tolerance it suggests still goes through the protocol and E10, never the catalogue. 3: every candidate corrected only down to above the content edge (Return to Seoul, Spirited Away, The Jungle Book, Bugonia). 4: known, rows 5/6 (steep filter; `judge_from_content_edge` is a server flag, not on the wire), F5 (Eastern Promises, Fame, Home Alone) and row 26. Earlier scope of this row:  0.2.9 reports design version 5, so beqdesigner's out-of-date filter flags every title designed before it. Review the redesign's declines and changed designs from their run records, as the first review was (row 29): confirm the fixes' titles moved as measured, rerun the open cases (row 29's tilt titles, the near-texture watch cases Black Bag, Bugonia and Incredible Hulk), and collect real-title evidence for rows 26 and 29's research. It can show wrong declines but not false acceptances (the library has no known negatives), so a retune it suggests still goes through E10. Do row 28 first if both machines will design. Records are kept by default from 0.2.10 (row 27, done). |
| 32 | Fit optimum selection | part built (design version 10, not released); ties now broken by strategy order; verdict flips left | Found by row 28: reproducible is not stable. Changing the fit's input by a few thousandths of a dB changes winners. **Built (25 October 2026, version 7):** the fitter returns every fit within its 0.5 dB residual bar of its answer, and the pipeline keeps the first the judge passes, fewest sections first; an alternative must lift by more than the goal tolerance to replace the answer ([outcome](plans/library-review-improvements.md#row-32-choosing-among-near-equal-fits-25-october-2026-design_version-7)). **Measured again (2 November 2026):** `refit_probe.py`'s perturbation stacked per worker and read cached proposals made under another offset, so every earlier flip count was indicative only; fixed, and `rejudge` now judges again from kept fits in seconds. On 32 titles (the 11 baseline titles and the 21 variants that had ever moved) at three offsets, version 9 flipped 14 of 93 winners (28 with `--content-edge`), and real titles flip too: 28 Years Later and Send Help move between parametric and flatten, under 0.1 dB apart, because the tie went to the fewest sections and a near-equal fit's section count re-rolls. Searching the outranked fit again from other seeds (A) and per-octave departure (C) changed little and are not adopted. **Built (version 10):** a flatness tie goes to the strategy listed first in `STRATEGIES`: 8 flips (18), every default-mode ranking flip gone. Probe: the two real titles go to flatten, the same answer within 0.6 dB; protocol seed 101 improves one recovery, 947 unchanged; corpus gate unchanged. On the v8 library 80 of 1,069 winners change (70 of 762 all passing, 10 of 271 with a failure). **Left:** verdict flips, a candidate on the edge of a shape check passing under one offset and failing under the next (8 of the 8 left, 11 of 18 with `--content-edge`). Next: a margin around those checks. See [the outcome](plans/library-review-improvements.md#a-stable-tie-break-2-november-2026-design_version-10) and [the finding](plans/library-review-improvements.md#built-a-reproducible-fit-input-22-october-2026-design_version-6). |
| 33 | Noise lift beyond the evidence (found on a pumping floor) | open: the evidence bound was measured and not adopted; next, validate the floor detection | E10's first runs lifted `nonstationary_floor` 27-33 dB, but that recipe swung about 37 dB inside every event: event-locked content, matching real stopband leakage on contrast and coherence, so not a failure under the content principle ([v5](plans/E10-validation-protocol.md#the-pumping-floor-v5-28-october-2026) reports it as `event_locked_floor` and counts realistic 2-6 dB `tracking_floor` and `breathing_floor`). On seeds 1-12 under [v6](plans/E10-validation-protocol.md#the-skirt-and-the-cases-it-leaves-v6-28-october-2026) (noise lift counted beyond half an octave under the truth band), 4 of 72 realistic-floor rows lift noise. The two large ones are the judge passing the candidate that fits worst: on `breathing_floor/2` four three-section fits within 1.1-2.1 dB of target fail the cliff check, and a single shelf 6.4 dB off target and 5.5 dB over the evidence ceiling passes and is selected; on `breathing_floor/5` (gentle) a single section 9.0 dB over the ceiling at an unsupported bin is selected over a passing three-section fit 1.9 dB over. Nothing refuses a design for exceeding its evidence: the over-lift bar is measured from the goal, and `evidence_excess` is reported only. **Bounding lift by the evidence, not adopted (29 October 2026):** the fitter bound at the licence plus 1.5 dB (A), a judge check on any excess over 1.5 dB (B), and that check limited to excesses at least half an octave wide (C) were each built on branch `experiment-evidence-bound`, uncommitted. C cleared E10's counted noise lifts, but applied to the v8 library's stored `evidence_excess` it refuses the accepted design for 96 of 1,033 titles, and 14 of those would decline. Inspection showed that most of these are a smooth fit against a ragged licence on content that tracks the programme (Any Given Sunday, To Die For). The large lifts it catches below a diagnosed floor (Wait Until Dark, White Heat) sit inside a licence that allows 20-25 dB there, and C catches them only by an edge excess. **Lift below the diagnosed floor:** 247 of the 304 designed titles with measured bins under `noise_floor_hz` lift more than 3 dB there, and 151 more than 10 dB. Almost all are flatten, holding its lift flat, among them Moana (37 dB under 8.4 Hz) and White Heat (29 dB under 40 Hz). These are not counts of noise lift. `noise_floor_hz` is the mix tracking boundary, the first band whose envelope fails to track the passband, and failing that is not proof of noise. The contrast licence often disagrees with it (Wait Until Dark: 20 dB licensed below it). **On E10's truth** ([evidence](plans/E10-validation-protocol.md#is-the-tracking-boundary-a-noise-detector-29-october-2026)), the boundary sits 0.24-0.42 octave (median) below the true noise boundary on every floor family, up to 1.12 octave, and never above it: it calls the noise just above it content. It also misses half of `finite_stopband`'s exposed cases, and calls LFE-only content noise at 15-27 Hz on 3 of 12 `partial_channels`. **On the library**, an independent test calibrated on E10 (does the band's level scale with programme loudness, and is it steady) finds content under the boundary on 151 of 300 floored titles, among them Moana, Creed III and Juror #2, the largest lifts below it. Only 10 look like steady noise. The other 139, mostly older, neither scale nor stay steady, which these statistics cannot resolve. So the boundary is not fit to gate a rule, and its content-as-noise error also holds restorations flat that the content supports. Measured within 240 s stretches, only 27 of those 139 become steady noise; 85 stay bursty within minutes without scaling with the plateau, which is either content independent of the plateau or transient noise (splices, handling), and E10 has no transient noise to calibrate against. **Next:** listen to Wait Until Dark, Marnie and GoodFellas (bursty, not scaling) against Mary Poppins and The Exorcist (steady noise). If bursty and non-scaling proves to be noise, add a transient-noise family to E10. Then improve the floor detection itself, before deciding how a restoration should behave below a floor shown to be noise: hold flat, cap at the local target as the counterfactuals do, or return to 0 dB. [Evidence](plans/E10-validation-protocol.md#bounding-lift-by-the-evidence-three-experiments-none-adopted-29-october-2026). Related: rows 32, 36, E4/E9. |
| 34 | Redesign scope | built and released in 0.2.12 (contract 1.6's `POST /impact`); beqdesigner's step 2 live check passed, step 4 verification next | The pipeline is a catalogue of 37 named features (`beqforge/impact.py`), each owning its code and reading from a run record how a design relied on it. Each answer-changing design version declares in `beqforge/impact.toml` which features it changed and how much that moved; `tools/impact.py check` refuses changed code no feature owns and undeclared answer-reaching changes (regression step 5). `POST /impact` scores up to 500 records (15 s over the share), and records from before 0.2.11 are identified by the release that wrote them, so the current library can be scored. Version 7's fit-choice degree was measured on the library on one machine: 18 of 34 post-fit declines moved, 7 of 15 designs with a failing candidate, 2 of 15 with all passing, 0 of 8 analysis declines. Against the library: 34 likely, 1,015 possible, 236 unaffected, 70 unknown (pre-design-version builds). It doesn't meet the plan's bar for this change (likely holds 18 of the sample's 27 movers): a change that re-rolls the fit can't be narrowed by outcome class. The ranking still holds: the top 30% hold about two thirds of the expected movers. Records now carry each verdict's margins and each fit `_choose_fit` had, so a threshold change is scored exactly (`will_move` or `unaffected`), and `unknown` (`no_figure`) only for older records or a losing candidate that would start passing; this changes no answer (rejudge probe 11 of 11 at `--tol 0`, refit probe 0 of 54 moved). Responses carry each change's `basis` and `unknown_reason` (agreed with beqdesigner). `impact.MOVED`'s cascade line is now 20/f dB, capped at 2 dB at 10 Hz and below, not a flat 1 dB. Version 7's designed classes were recounted on beqdesigner's 105-title sample: 16 of 35 with a failing candidate, 22 of 60 all passing. **Version 9's scores (1 November 2026):** the ceiling's basis came from a sample chosen for lifting above 60 Hz, and its two touches were combined as independent although they were one measurement, so every one of the v8 library's 1,033 designs scored `likely`. Each touch can now be confined above a frequency (`above_hz`, `basis_below`). A record is scored by whether its band, target or cascade reaches above 60 Hz, and the largest share among a change's touches stands for the change. That gives 365 `likely` and 684 `possible` (0.29, row 32's re-roll); expected movers fall from 999 to 532. No answer changes (probe 11 of 11 at `--tol 0`). See [the outcome](plans/redesign-scope.md#scoring-a-change-by-what-it-reaches-1-november-2026). **Left:** beqdesigner's step 2 live check and step 4 verification sample (105 titles), and the check's from-the-results direction. See [the outcome](plans/redesign-scope.md#outcome). |
| 35 | Review the version 6 library redesign | open: handoff received 24 October 2026; the 500 and record overwriting fixed in 0.2.11; the 14 new declines traced to row 28, 13 of them designing again on row 32 (version 7, unreleased) | beqdesigner's v6 rerun (job `e6a70f7e`, 1,287 titles): 1,016 designed and 270 declined. A Quiet Place: Day One, Elysium and Pan now design (row 31's O2 fix). 17 titles declined on v5 now design, and 14 designed on v5 now decline. Handoff: `/media/beq/triage/handoff-v6.md`; ledger `/media/beq/triage/ledger.jsonl`, stage `E`. **Fixed:** A Quiet Place Part II got a 500 every time, because `TargetFit.within_tolerance` came back as 1.0000000000000002. Zero-weight bins that miss the tolerance change how numpy pairs up a sum, so the in-tolerance sum could round above the full one. It is now met / (met + missed), which can't exceed 1; this code predates row 28. The figure is reporting only, so no design version: the title's filters are unchanged (low shelf 18.25 Hz +24.6 dB, peak 28.38 Hz −3.5 dB), and its response is now valid. Probe 11 of 11 unchanged at `--tol 0`; suite passes. **The 14 new declines (analysed 24 October 2026):** all 14 were rerun on one machine, at v0.2.9, at `f6dca94` (row 28 alone) and at HEAD, from requests identical to the library's (same digest). All 14 design on 0.2.9 and decline at `f6dca94`; HEAD agrees with `f6dca94`. So row 28 alone is the cause, and processor variance accounts for none of them. In every case the target is identical (0.000 dB apart) and the fit lands on a different cascade: row 28's 0.01 dB quantisation of the fit's input re-rolls the fitter's choice among near-equal optima (row 32). Except for TINA, the new fits are within 1 dB of the old by the fitter's own measure, worst-case error (Kung Fu Panda 4 0.4-0.9 dB worse, You've Got Mail 0.9 dB better), yet a judge check that depends on the error's shape flips: cliff (Platoon, The Manchurian Candidate, You've Got Mail, How to Marry a Millionaire), tilt (On Golden Pond, Christine, Twilight's counterfactual), ripple (Arrival, Kung Fu Panda 4), turnover (Magnolia, Zoolander), extent (Twilight's flatten) or slot (Rocky, Souleymane's Story). In TINA's case the fit itself is worse: 0.2.9's three-section fits drifted 2.1-3.0 dB on publication rounding, against a 3.0 limit, with their lowest sections about 4 quantisation steps from the device's DC limit. The new fits most likely drifted just past it, and the exposure rule fell back to one shelf fitting 4-6 dB off. No threshold should move on this evidence: the declines are as arbitrary as the 0.2.9 acceptances were, and the fix is row 32's, choosing among near-equal fits by what the judge checks rather than by which optimum the arithmetic lands on. **Slot check:** Rocky's and Souleymane's Story's new fits carry sections under 1 dB that the pruner keeps, because dropping them costs 1.02 and 1.12 dB of worst-case error against its 1 dB allowance. Their 0.2.9 two-section fits reached the same error without them. `designer-interface.md` §4 allows a rejection only for a reason internal to the evidence, which a redundant section is not, so the stated reason is wrong whatever the outcome. The outcome itself is doubtful too: both designs are 0.2-2.6 dB sections at 71-353 Hz, mostly above an 80 Hz crossover, not low-end restoration. The library's flip lists are not ground truth for row 34 by themselves (see [the proposal](plans/redesign-scope.md#validation-before-relying-on-it)): its v5 records were overwritten by v6's, because a record was named by its request's audio digest. **Fixed (0.2.11):** a record is now named by digests of the audio and of the rest of the request (coverage, bass management, adjustments, settings) and by the design version, and holds `design_version` and `design_settings` itself. A response's `run_record` (1.6, agreed in principle with beqdesigner) names it relative to the shared root. No answer changes. |
| 36 | Is a design worth publishing at all? | open | The judge checks that a design does what its target asks, never whether the target is worth asking for. Only the target stage refuses a correction within the goal tolerance (1.5 dB), so anything that reaches the judge by another route can pass as a trivial design: row 32's search over near-equal fits accepted a single 0.98 dB shelf on the band-exclusion test until `pipeline._lifts_beyond_goal` gated alternatives. Rocky's and Souleymane's Story's v6 designs (row 35: 0.2-2.6 dB sections at 71-353 Hz, mostly above the crossover) are the real-title form of it. Decide whether the judge should refuse a design whose low-end lift stays within the goal tolerance, and with what reason under `designer-interface.md` §4. A decision change: protocol, corpus and the library's small designs. |
| 37 | A frequency-dependent fit tolerance | variant C works; held back behind row 36, not in 0.3.0 | The fit scores the worst absolute dB error the same at every frequency, so near-equal fits are interchangeable to it wherever their error sits. Version 8's re-roll (row 23) moved 28 Years Later by 1.13 dB at 33 Hz and Obsession by 1.09 dB at 29 Hz. `impact.MOVED` now uses 20/f dB, capped at 2 dB at 10 Hz. Weighting the fit's bars as well as its search failed: the fitter either spent sections on fractions of a dB above 50 Hz (A), or the near-equal window, 2 dB wide at 10 Hz, let single shelves up to 3.6 dB off win on section count (B). **C**, weighting only the search (f/40 Hz, 0.25 to 1), works: over the 31 winners, median worst error at 30-40 Hz falls from 1.11 to 0.63 dB and at 5-10 Hz rises from 1.05 to 1.65. No real winner changes, protocol and corpus gate are unchanged, and corpus recovery goes from 1.37 to 0.85 dB RMS. It is held back because the band-exclusion test now designs a 1 dB nothing where version 8 declined, which is row 36's hole. **Next:** C together with a row 36 rule (refuse the fitter's answer, not only its alternatives, when its lift stays within the goal tolerance), validated as one decision change. Code on branch `experiment-fit-weighting-search`. See [the evidence](plans/fit-weighting.md). |
| 38 | Review the version 8 library redesign | open: handoff received 28 October 2026; nothing new to build, evidence for rows 32 and 36 | beqdesigner redesigned 1,051 titles on 0.3.1 (design version 8). Handoff: `/media/beq/triage/handoff-v8.md`, per-title results in `/media/beq/triage/dv8-redesign-moved.json`. Every decline now has a ledger row against the build that made it (`ledger.jsonl` stage `F` for the 44 at v7 and v8; the 208 still at v6 are stage `E`). The handoff reports no new class of finding: all seven items of beqdesigner's library-run review (its L4) are already in row 29 and, where still open, rows 31 and 35. **Row 32:** one new designed-to-declined flip, 22 Jump Street (`-1428523`), designed on v5-v7. On v8 flatten fails only the cliff check (40.7 dB/oct at 12.9 Hz against the input's 35.5), the same shape as Platoon's v6 flip; records `designer-37ed4387a860f027-7806f696-v7.run.json.gz` and `-v8`. 19 titles declined on v6 now design, including 12 of row 35's 14 flips. **Row 36:** four titles reviewed as genuine declines now design, one design each: The Adventures of Priscilla, Queen of the Desert; The Book Thief; The Manchurian Candidate; and Bugonia (declined before on coverage below 8.1 Hz). Check whether each is worth publishing. The other 43 of the 44 declines are unchanged in reason and failing checks from the stage E review. |
| 39 | A bass ceiling | released in 0.3.2 (design version 9) | Bass EQ restores the low end a mix's filtering removed, and that ends at or below about 60 Hz. The designer has no such limit: the judged band's top follows the deficit's first settled end, at least an octave above the tracking floor, so on a mix whose floor sits high it reaches the midbass and `flatten` fills everything under it. Wait Until Dark was judged to 192 Hz, flat; its cascade lifted 110 Hz by 7.4 dB and 250 Hz by 2 dB, and passed, because the over-lift bar's slack (half the input's 31.5 dB roughness) allowed 15.7 dB. Measured by where each cascade's lift last reaches 3 dB: 12.4% of the version 8 library's accepted designs pass 60 Hz, 7.2% pass 80 Hz and 45 pass 100 Hz, against 0.7%, 0.1% and 2 of the 15,586 catalogue entries. This checks the premise; it is not a calibration. Most of the catalogue's exceptions above 80 Hz are one author's flatten-like designs that review judged wrong. The library's age mix explains about two thirds of the gap: lifting past 60 Hz is 49-63% of pre-1980 designs against 2.5-5% from 2000. Reweighted to the catalogue's age mix it is still 4.5% against 0.7% at 60 Hz, and 1.7% against 0.1% at 80 Hz. Candidate: `AcceptParams.bass_ceiling_hz` (60). It caps the deficit's end in the judged top, but not the one-octave span, which a slope needs. Every priced target is tapered to nothing by the ceiling. Above the ceiling, the over-lift bar bounds the cascade's own lift to the level tolerance, with no roughness slack, and the fitter is given that bound. The mix-texture blocker keeps its uncapped band. Measured: probe moves no verdict or winner; protocol moves no false acceptance; corpus 0/45 gated, natural droop 5/9 to 4/9, filtered 7/9 to 6/9 (the loss had 15.6 dB rms recovery). On 80 paired library titles, 57 of 60 lifters still accept and none lifts 3 dB past 58.7 Hz; 3 decline (The Manchurian Candidate, Solaris, The Red Shoes, all flatten filling a plateau above 60 Hz); 20 of 20 controls unchanged. The lift below 60 Hz is untouched, so Wait Until Dark's rumble is still row 33's. Of 22 sampled library declines, 3 now design, all fit re-rolls below the ceiling (row 32). Adopted: `impact.toml` declares it, the golden answers, corpus and baseline records are refreshed. Left: row 33, for the lift that remains below 60 Hz. Evidence and outcome: [the experiment](plans/bass-ceiling.md). |

## Review evidence

F2 also tracks the [catalogue filter optimisation design and initial implementation](plans/F2-catalogue-filter-optimisation.md):
reproduce a published filter's ideal response more accurately on a named device, using only
that filter. Deliver as the `beqoptimiser` package in the single `beqforge[optimiser]` distribution profile,
used by beqcatalogue to publish device-specific
variants consumed by ezbeq, supporting 48/96 kHz with extensible precision models.
Search only above a configurable maximum error margin (default 0.5 dB); publish a replacement
only when it meets that same margin.
The library/CLI now implements direct-coefficient search and numerical validation;
development examples show some qualifying replacements and correctly withheld partial improvements.
The [static whole-catalogue report](docs/optimiser-report/README.md) now evaluates all 15,323 entries
at both rates: 11,871 entries gain qualifying replacements at one or both rates; failures
retain the originals in the aggregate curves. The library now automatically reuses numerical
results, with a bundled seed covering all filter-bearing entry/rate cases and configurable
disk caching; entry metadata is rebuilt on every call. Catalogue/ezbeq publication integration
remains open.
The [package consolidation](plans/F2-package-consolidation.md) puts all three independent
workflow packages in one versioned distribution with optional dependency profiles and
separate commands; shared arithmetic lives beneath them in `beq_common`.
Next: agree beqcatalogue/ezbeq variant and loading contracts, freeze catalogue evaluation and
verify selected pairs on hardware. Parameter search shipped for beqdesigner's single-filter use
([`optimise_parameters`](plans/parameter-space-optimisation.md), 0.2.5; phase and
listener-derived bounds not considered); for catalogue variants it, and cascade refits, remain follow-ups;
no catalogue-wide or hardware-validated benefit is claimed. This work does not
change the audio-derived pipeline or establish whether an authored BEQ suits its film.

The consolidation at `4b11827` retained most work, but put a reporting issue above evidence
quality, called actionable protocol work parked, and treated confirmation of already-adopted
contract wording as blocked. This review restores the chart-bias follow-up and separates
actionable steep-scoring work from the externally dependent default decision. No pipeline
behaviour, tolerance or baseline record changes here.

Evidence behind the order and the parked decisions:

* [F1 implementation](plans/done-design-and-pipeline.md#implementation-outcomes), commits
  `5054ae4` and `e62be2a`: noise-floored steep acceptances improved **17/18 → 18/18** with
  the option on. The 17/18 figure belongs to the earlier prototype; default-mode 2/18 is
  the earlier comparison, not a fresh measurement in this review.
* [Research outcomes](plans/research-design-decisions.md#measured-outcomes), `352206f`,
  `c34465c` and `4d04e97`: F4 lost true positives; weak steep winners mostly lost better
  candidates at acceptance, not ranking/cap selection; T8's confidence-bound floor cost
  correction without consistently improving stability. These do not justify another
  speculative ranking, cap or floor change.
* [E9 audit](plans/done-design-and-pipeline.md#implementation-outcomes), `6d0989f`:
  accepted steep variants exceeded the ceiling by up to 4.0 dB over 0.58 octave; the corpus's
  filtered/1 reached 5.6 dB over 0.28 octave. Real-title candidates stayed below 0.5 dB.
  Audit this with steep policy; it is not evidence specifically of single-bin holes or
  permission to add a blanket gate.
* The sibling [`designer-interface.md`](../beqdesigner/design/designer-interface.md)
  §§2–4 already adopts clipping cost, bass management, ordinal confidence, non-parametric
  residuals and decline/report rules. It deliberately excludes device preference.
  [`designer.design`](beqforge/designer.py) uses only the supplied crossover;
  [`DesignJob.run`](../beqdesigner/src/main/python/model/batch.py) and the library's
  [`_design`](../beqdesigner/src/main/python/pipeline/library/run.py) omit bass management
  when calling helpers that support it. These are code/contract issues, not missing
  contract evidence.

## Checks and scope

### Playback contract

The contract's bass-management input includes crossover, low-pass position, headroom type
and clipping flags. `designer.design` changes only the crossover, leaving fixed mains/LFE
gains and an always-on mains-plus-bus LR4 model. The supplied headroom model can therefore
differ from the one behind `gain_reduction_db`. Playback also feeds counterfactual summation,
the sub-band blocker and verification, so determine which differences change the filter or
its verdict and which only change clipping reports.

Compare the same channels and cascade against beqdesigner's actual bass-management path,
including WCS versus numeric headroom, LFE presence/channel count and low-pass Off. Resolve
which fields describe linear playback and which describe simulation of clipping before
deciding how to support them. Any unsupported configuration must be described honestly;
supplying a dict is not enough to claim it was modelled. No hardware capture is needed for
these software comparisons. Caller propagation requires a change in beqdesigner, outside
this repo; both its batch job and library call omit the available argument today.

### Fresh validation protocol and steep-filter policy

The legacy corpus is development evidence after repeated tuning, not a held-out estimate.
Version a new protocol without editing old results. This is actionable now; acquiring new
real holdouts is the separate coverage dependency. Predeclare coloured, nonstationary and
correlated noise, finite stopbands, limited programme, sparse/continuous bass, channel
cancellation and partially filtered channels; partition seeds and source titles (variants of
one title are not independent), goal settings, failure classes and sample sizes. Preserve
legacy counts. Resolve the goal/corpus follow-up here: specify which goals license shaping,
which cases must abstain and why; assess restoration accuracy, unsupported/noise gain and
selection quality as well as counts.
Choose sample sizes from the desired interval bound: 0/45 development negatives is not
evidence of a zero population rate, and nine cases per shape provide weak bounds.
Once holdouts inform tuning, reserve a new holdout.

The first `--content-edge` experiment accepted 17/18 noise-floored steep injections against
2/18 with the default; F1 subsequently brought the opt-in to 18/18 (review evidence above).
These are development results, not independent safety estimates. The option
can lift noise where loud events clear a floor that dominates the average. Listen to the
Hulk BW16 @ 30 Hz, −80 dB variant (+16.8 dB noise lift), and the −40 dB-floor case whose
corrected noise lies 28 dB below the plateau. Obtain real steep titles such as Master and
Commander, Kingdom of Heaven DC, Hunger Games: Songbirds & Snakes, Nobody, Wreck-It Ralph,
Battleship, Mad Max 2 and Midnight Run. Safe House is already on hand and accepts a steep
finite-stopband correction with the default, so steepness alone is not the missing ability.
The open scoring work can proceed on existing real texture: test codec-like/coloured floors,
finite stopbands and partial-channel filtering; declare each recipe's truth band instead of
the scorer's fixed 60 Hz top and compute corrected noise from its actual spectrum rather
than the white-floor formula. Review shape-clause failures that discard the closest-to-truth
candidate in both modes, along with E9's excess in the published response. Do not assume a
ceiling gate or a shape exemption is the answer; both can discard usable partial recovery.
A default change waits on E10 and the missing listening/independent-title evidence.

### Device behaviour and held-out verification

F2 requires a named device, known rate/coefficient format, a signal/capture path with enough
low-frequency dynamic range, and real measurements of internal word length, recursive
rounding noise and limit cycles. Those measurements are the blocker, not writing the
harness. The [F2 measurement plan](plans/F2-device-precision-validation.md) defines the
miniDSP loopback with sounddevice/pyfar, optional REW cross-checks, identity-normalised
exact/stored-coefficient comparisons, arithmetic checks, CamillaDSP/JRiver controls and a
standalone cross-platform executable with single-entry/full-catalogue modes; qualify the bench before executing its frozen matrix. Compare sections at Q 5.2–6.0 with unconstrained fits and the device's measured
output before deciding the limit; coefficient quantisation alone does not model its arithmetic.

**F2a — remeasure the catalogue sample after the clipping fix.** The one cascade in
`results/20261005T192911Z` that failed against prediction (*Mojin: The Worm Valley*) was
clipped by the device: the level screen used the sent float64 gain (+32.5 dB) rather than the
stored float32 gain (+48.8 dB), and the 2x4 HD saturates at −0.012 dBFS, under the old 0.999
clipping test. Both are fixed (plan section 13). Next: regenerate the catalogue manifest and run
verify again; expect all 50 to be judged on (nearly) every bin, and Mojin's result to say
something about the device rather than about clipping.

E1: derive evidence, reference, target and cascade from separated scene blocks, evaluate the
fixed correction on the other fold, then swap. Guard filter/window edges so an event does not
cross folds; do not concatenate excerpts and call them complete programmes. Scene-specific
bass is content, so do not demand flatness in every scene. Report first: demonstrate that a
deliberately overfit target is exposed out of sample and quantify variability on valid
injections and real titles. Reporting alone changes no acceptance counts. Only consider a
gate after demonstrating fewer false accepts without losing true positives on fresh E10
evaluation; the existing development corpus is a regression check too.

### Parked decision changes and watch cases

E4's proposed running-minimum ceiling must never license gain unsupported by the raw ceiling.
F3's fifth section moved no verdict when tried; fit cost grows with section budget. F4's two
fitter-selection spikes were rejected: acceptance judges something different from residual.
A follow-up would carry several publishable fits through `_judge`, then select by verdict.
T2's cap sweep did not explain weak winners. Revisit only with a binding example.

Watch near-texture-blocker cases: Black Bag (1.08×), Bugonia (1.09×), Incredible Hulk (1.01×).
Obsession has a narrow level-dependent band ending its level-independence run; decide whether
its omission from the response matters if a reviewer needs it. T8's point floor agrees with
the modal resampled floor on tested titles; revisit only if they disagree. T7's floor and
1024/4096-sample resolution review found no verdict depending on it; revisit with injected
floor evidence. Reopen E7 only if the plateau rule changes.

### Performance and remaining product questions

Measure identical numerical fit requests before gathering parametric targets into `_fit_all`
and deduplicating. Identity includes target, grid, score/placement bands, bounds, seeds and
realisation; preserving each strategy's scoring matters. Only then consider a bounded atomic
cross-run fit cache keyed on that identity, implementation and library versions, honouring
`--fresh`/`--no-cache`; never cache verdicts or headroom. Check repeated `mean_spectrum`,
`plateau_reference`, `_flat_deficit`, `supported_mix_change` and counterfactual-cap blocks
without merging different estimators. More seeds, warm starts or reparameterisation need a
measured missed usable fit. Precision/budget trades measured around 1.4× carry a quality cost
and were not adopted. Headroom acceleration and stage timing already ship (C4/C5).
The fit kernel (row 23, [plans/fit-kernel.md](plans/fit-kernel.md)) is a different kind of trade:
the same budget, scored faster, quality-neutral on the tasks measured.

Identification still needs a generalisable `N(f)` model/fit band and a specified uncertainty
method. Scene segmentation must be evaluated against false positives, not one title. There
is no computed response-level channel scope or mixed-channel policy; the adapter leaves the
optional field unset despite the available per-channel diagnosis. Automatic authored-feature
exclusions remain manual via `--exclude`. `parametric` stays on by default and does win titles:
model work must show an improvement in the final priced and judged correction, not just a
better fit to `N + A`. A sampling interval would not resolve the observational equivalence
between natural colour and a mastering filter.

Catalogue disagreement is an untested hypothesis: steep authored corrections may be
under-realised by single shelves. Look at disagreements rather than treating them as scores.
Dynamic processing needs a real suspected case before designing its tripwire.

Upstream wording is already confirmed in the local contract, including non-parametric
residuals. Passing device realisation per request would be a new contract decision, not
confirmation of an adopted field; server flags already supply it. Bass-management propagation
and semantic fidelity are the playback item above. By-reference support on both sides is
already complete. Chart maxima deliberately retain duration-dependent bias for catalogue
comparison; extraction's evidence envelope uses a percentile instead, so changing charts
would not improve the generated filter.

## Validation material and completion rules

Every decision change follows [AGENTS.md](AGENTS.md)'s regression workflow. Write its outcome
in the appropriate completed/research record in `plans/`, and remove or update its status row
here in the same commit. Preserve baseline records; scratch check runs must not overwrite them.


Real audio tests generalisation to programme the tool has not seen; constructed cases test
known failure mechanisms and differential injection supplies known changes on real texture.
All three are needed. Describe tracks by the structure they test, not by title. Each real
track must be a complete programme (the tool abstains on an excerpt), with an explicit
channel layout so `extract` accepts it. Black Bag already supplies sparse material with an
in-band tracking floor; Dossier supplies a dialogue-led abstention. The missing coverage is
additional independent sparse examples and characterised truth, not the absence of any
sparse title. The [baseline coverage](plans/done-baseline-evidence.md#baseline-2026-09-26-track-set)
still lacks paired releases, old/upmixed material, continuous-bass concert films, heavily
compressed and noise-dominated material, 2.0 and long/short pairs.

### Per-track metadata to record

Layout and LFE presence; source codec and bit depth; whether it is a complete programme;
runtime; whether it is believed filtered, unfiltered or unknown, and how that was established.
The last matters most: a belief with no independent source is not ground truth.

### The shapes

| Shape | What it provokes | Items exercised |
| --- | --- | --- |
| **Paired releases of one mix** (an original and a remaster, or a lossless and a lossy release of the same soundtrack) | Independent reference for a mastering change after alignment and gain matching. Establish that the difference is a filter: remixing, dynamics, edits and codecs can also differ. Codec-only variants test noise-floor and ceiling robustness. | E1, E2, E6, A1 |
| **Bass-rich, high-dynamic-range modern mix with full LFE** | The positive control: large events, quiet passages, a clean floor. Every change must keep it working. | all (regression) |
| **Bass-light, dialogue-driven drama** | The sparse case the guard exists for; few independent loud events, so wide standard errors. Best if its tracking floor sits *inside* the content band. | E2, E4, T7, Validation coverage |
| **Old or upmixed mix** (mono or stereo origin, no real LFE) | Natural droop that looks like a mastered rolloff. `counterfactual` can restore mains without LFE; assess the correction against its declared goal without treating absent LFE as proof that nothing can be restored. | E2, E6, T3 |
| **Concert or music film** | Continuous bass with few genuine quiet frames: the quiet estimate may contain programme and suppress the contrast licence. | E4, E5, T5 |
| **Heavily compressed or limited mix** (loudness-war, trailer-style) | Dynamic processing may undermine contrast or level-independence evidence. Establish which corrections become wrong before designing an abstention tripwire; compression by itself need not invalidate a spectral correction. | E2, E6, Dynamic processing |
| **Noise-dominated location recording** (documentary, stationary rumble) | Stationary noise at low frequency; the ceiling must license nothing there. | E2, E4, E5 |
| **Strongly rippled or humped bass** (a 40-80 Hz hump, or a mid-bass shelf above the sub) | Plateau choice and the anchor: a wide hump can win "widest first" and a wobbly plateau can drag the anchor. | T4, T5 |
| **Authored LFE feature** (a narrow hump in the LFE) and **LFE lowpass variation** (different lowpass corners across releases) | The `--exclude` path, and whether a channel is judged filtered. | T3, T2 |
| **Layout variety** (2.0, 5.1, 7.1, and a bed from an object mix) | Downmix weights, the LFE gain assumption, and the `"mixed"` channel-scope case with no policy. | T1, Identification |
| **Infrasound-rich mix** (content below 10 Hz) | The 5 Hz placement floor and the flat hold below the noise floor. | E5, T7 |
| **Long and short programmes of similar character** | How the standard errors and the ceiling scale with the number of independent events. | E4, E2 |

Aim for at least two real examples of each shape; a single example cannot separate a track's
quirk from the shape's.

### Variants generated from each real track

The real tracks supply content; known transforms supply **differential** truth. An injection
does not require a known-unfiltered original: score the additional change against the
original, whose unknown mastering then cancels. Neither that nor comparison with the
original's own correction proves absolute restoration accuracy. Absolute positive/negative
labels need independently established truth; an unknown as-is track is not a negative.
Commit recipes for:

1. **As-is** — the baseline record.
2. **Injected known rolloff:** vary corner (roughly 15-40 Hz), order (2-4 and steep 8/12/16),
   family (Butterworth and Linkwitz-Riley), finite stopband and channel subset. Declare the
   recoverable band and score recovery, noise lift and which candidate was selected.
3. **Natural-droop controls:** intrinsically coloured known sources, with acceptance/shaping
   rates reported separately (E6), not gated as distinguishable mastering negatives. Applying
   the same high-pass to every channel is also the positive injection above: it cannot
   become an independently distinguishable negative merely by renaming its provenance.
4. **Added noise at a stated spectrum/SNR:** steady rumble, white, coloured, nonstationary
   and cross-channel-correlated floors, including noise added after the filter. Measure the
   corrected floor as well as cascade gain; keep the true programme/noise arrays or spectra.
5. **Excerpted:** 20% and 50% of the programme, explicitly marked `coverage="excerpt"`,
   which must abstain. This tests coverage policy; undisclosed excerpts cannot be assumed
   detectable from their audio alone.
6. **Re-encoded:** through the codecs a release would use, for noise-floor stability.
7. **Non-default playback model:** different `--main-gain-db`, `--lfe-gain-db` and
   `--crossover` on the same track (T1).

Each variant is a separate `.npz` under `data/`, which stays gitignored, and each gets its own
run record. The variant recipe (seed, transform, parameters) is what should be committed, so
they are reproducible without committing audio.

### What to measure on every track

* Accepted or abstained, which strategy won, and the section count and filter.
* `recovered_fraction`, `shaping_fraction`, `correction_support_score`, and the note that the
  ceiling bound; published `evidence_excess`, including unsupported bins and exclusions.
* Plateau region and level, deficit anchor, noise floor and judged band, so T4-T7 can be read
  straight from the records.
* The held-out verdict (once E1 exists) and the false-accept and true-positive tallies by shape.
* For known transforms, recovery/overshoot in the declared truth band, noise after correction
  and whether selection discarded a better valid candidate. Compare the published device
  response rather than raw optimiser parameters.

### Definition of enough

Every decision change must complete AGENTS.md's regression workflow on available material
and record its limits. A claim of broad real-programme correctness additionally needs at
least a positive control, sparse material, a natural-droop control and a characterised
paired release, with outcomes recorded under `plans/`; that claim is currently blocked by
the missing paired releases and independent truth. Do not imply that development-corpus
success closes it. A change that only speeds a run up needs `compare_records.py` to show
the records are identical apart from the fingerprint and timings.
