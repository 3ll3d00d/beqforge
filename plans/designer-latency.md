# Designer latency: repeated work removed, no answer changed (TODO 23)

A profiling review on 13 November 2026 (design version 10, `bc0cd3c`) found about half of a
run was work done more than once or not needed: the same sub feed built seven times, the
same spectra measured per candidate, the same waveform filtered twice, and so on. Seven
changes removed it, one commit each, each held to the bar for an exact-preserving change:
`probe.py compare --tol 0` shows nothing and a real run's record is identical apart from the
fingerprint and timings (`compare_records.py`). No design version bump; nothing here can
move an answer, and nothing did. The fitter was out of scope (its alternatives are measured
in [fit-kernel.md](fit-kernel.md)).

## Result

Interleaved real runs of `bc0cd3c` (a worktree) and the last commit, two repeats each,
sleep inhibited, each version with its own cache file. Pipeline time is the record's
`timings.elapsed_s`; wall time adds process start, imports, loading and the record. Repeats
agreed within 1 s, and every one of the 20 records was identical between the two versions.

| | before, pipeline | after, pipeline | | before, wall | after, wall |
| --- | --- | --- | --- | --- | --- |
| Caught Stealing, cold (`--no-cache`) | 54.7 s | 27.5 s | 2.0x | 64.2 s | 37.0 s |
| Caught Stealing, warm | 28.9 s | 15.2 s | 1.9x | 38.5 s | 24.8 s |
| Black Bag, cold | 22.1 s | 13.9 s | 1.6x | 29.7 s | 21.5 s |
| Black Bag, warm | 12.3 s | 8.1 s | 1.5x | 19.9 s | 15.8 s |

The review had estimated 25 s cold and 11-12 s warm on Caught Stealing from summed
components. Cold came close; warm is 15 s because the warm baseline measured 29 s here
rather than the 25 s quoted. What is left of a warm Caught Stealing run: the fit 5.5 s,
`counterfactual`'s target 3.7 s, judging 3.6 s, the sub feed and its spectra 0.6 s. About
9.5 s of each run's wall time is outside the pipeline and was not touched.

## The changes

Each saving is the stage time in warm real runs of Caught Stealing (CS) and Black Bag (BB)
against the previous commit; the runs went one at a time, sleep inhibited.

1. **Headroom peak in 1,024-sample blocks** (`verify.waveform_peak`, was 65,536). The
   C4 bound is the interpolation kernel's polyphase gain, 3.02, so a block holding any
   sample within 9.6 dB of the peak found must be interpolated. Over 65 seconds nearly
   every loud passage's block qualifies: CS interpolated 1.84M samples in 28 blocks, against
   0.15M in 134 at 1,024 (Incredible Hulk 2.69M against 0.51M). Below 1,024 the per-call cost
   and the 96-sample kernel overlap each block carries win back what pruning saves (256 is
   no faster). The block cannot change the answer: each retained sample's sum takes exactly
   the inputs within the kernel's reach, whatever block it falls in, which the existing C4
   test pins against a 65,536-block reference (now with a case of many near-equal transients
   across 1,024 edges). Checked on all 29 recorded candidates of the 11 baseline titles: the
   peak at 1,024 equals the peak at 65,536 and the baseline record's. Headroom 7.2 to 1.7 s
   (CS).
2. **The sub feed built once a run** (`run`, passed to `overlift_allowance` and `_judge` as
   `sub_samples`). `analyse` keeps its own build for the silent-feed blocker rather than
   returning it on `Analysed`, which the refit probe pickles whole into its state: a 50 MB
   array a title in that file. Sub feed 2.5 to 0.36 s (CS).
3. **The unfiltered spectra measured once** (`verify.measure_unfiltered`, an `Unfiltered`
   record `verify` takes and refuses when measured for other signals). The sub feed's and
   the mix's Welch spectra and the plateau reference were remeasured for every candidate
   and for the over-lift bar. `verify` 4.9 to 2.9 s (CS).
4. **One filtered waveform per measured candidate.** `verify` filtered the feed through the
   device transfer and `measure_headroom` did it again with ring-out; the two share FFT size,
   padding and transfer, so the head of the second is the first. `_judge` builds it once and
   hands it to both (`corrected`, `waveform`); an unstable cascade has none and each falls
   back to its own path and reasons. Checked on the same 29 candidates: the corrected curve
   and headroom equal `verify` and `measure_headroom` called apart. Judging 4.8 to 3.6 s
   (CS).
5. **A cap's restoration reused when its boosts repeat** (`counterfactual_targets`, with
   `counterfactual_target` split into `_restoration_boosts` and `_restored_target`). A
   restoration cap reaches the target only through each channel's boost curve; comparing
   those few hundred bins exactly is the cheap test, and a cap whose curves equal an
   earlier cap's reuses its restoration. 45 and 50 dB repeat 35 on CS, every cap past 25
   on BB. The review also named the mix's `_spectral_blocks`, the same for every cap: it is
   0.02 s, and sharing it would change `diagnose.py`, which is in `cache.ANALYSIS_MODULES`
   and so would invalidate every analysis cache, so it was left. `counterfactual` 6.6 to
   5.1 s (CS), 3.0 to 2.1 s (BB).
6. **One `_flat_deficit` a channel** (`channels_missing_low_end`; `low_end_deficit_db` and
   `passband_ripple_db` take `measured`). Both rules took the channel's Welch spectrum for
   themselves. `counterfactual` 5.1 to 3.8 s (CS), 2.1 to 1.4 s (BB).
7. **The bootstrap percentile from draw counts** (`extraction._bootstrap_percentiles`). A
   replicate is a multiset of the masked frames, so its 95th percentile is found by walking
   the frames in descending order of value, counting how often each was drawn, and
   interpolating the two order statistics as `np.percentile`'s linear method does; the
   replicate draws are unchanged. The review's prototype agreed to 2e-15 dB, not exactly.
   The order statistics and per-replicate percentiles were already bit-identical; the
   difference was layout: its replicate-by-bin array was transposed, so `np.std` summed
   the replicates in another order. Kept in C order, the result is bit-identical. A bin whose
   rank lies past the frames searched (four times its rank, plus 16), or with non-finite
   power, takes the original gather (`_gathered_percentiles`). Checked against `bc0cd3c`'s
   function on every channel and the mix of CS and BB, loud and quiet sharing one generator
   as `extract` does, and again with the fall-back forced on every chunk; the probe
   recomputed every title's analysis and showed nothing at `--tol 0`; cold runs of CS and BB
   matched `bc0cd3c`'s records. CS's LFE 11.7 to 1.9 s; cold `diagnose` (which extracts each
   channel) 21.6 to 10.4 s and `extract` 3.5 to 0.8 s.

## Validation, per commit

The probe snapshot was taken on committed code before the first change, and after each
commit that commit's snapshot became the reference. Twice on `bc0cd3c` first: the probe
reproduces itself exactly at `--tol 0`. Every commit then gave:

* `probe.py compare --tol 0` against the previous commit: all 11 titles unchanged;
* real warm runs of Caught Stealing, Black Bag and 28 Years Later (scratch records),
  `compare_records.py` against the previous commit's: identical, headroom peaks included;
* `uv run pytest`: passing;
* `impact.py check` against the previous commit: the expected warning that answer-reaching
  code changed with no bump, which the probe at `--tol 0` answers.

Steps 1 and 4 change how headroom is computed, which the probe skips, so each also had the
29-candidate direct check above. Step 7 changes an analysis module, so its probe recomputed
every analysis (165 s a title) and it also had cold runs.

New tests pin each seam: a run hands every judge one sub feed and one `Unfiltered`
(`test_design_timings`); a judge or over-lift bar handed them judges as one that built them,
and one filtered waveform serves verify and headroom on stable and unstable cascades
(`test_design_playback_headroom`); `Unfiltered` verifies as remeasured and is refused for
other signals (`test_design_playback`); a cap whose boosts repeat is not restored again and
every cap's target is still its own (`test_design_pipeline`); one `_flat_deficit` a channel
(`test_design_corpus`); the draw-count percentiles equal the gathered ones bit for bit at
six percentiles, with ties, non-finite power and a forced short tail, and `extract`'s errors
equal by either path (`test_design_extraction`).

## Not done, noticed

* The mix's `_flat_deficit` (a Welch pass over the whole mix) is computed afresh three
  times in `analyse` (its texture check, its low-end deficit, its judged band), again by
  every strategy's `low_end_deficit_db`, and by `content_edge_hz`. Not measured; the next
  candidate of this kind.
* `analyse` builds the sub feed once more to check it is not silent (step 2).
* Outside the pipeline, about 9.5 s a run: the record's chart curves filter the mix and
  the charted channels through every candidate (`record.py`'s `device_waveform` calls), on
  top of loading and imports.
