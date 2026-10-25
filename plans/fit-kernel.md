# A faster fit for 0.3: the population-vectorised cost (TODO 23)

Measured 25 October 2026 on `a20ed8c` (0.2.12, design version 7); built the same day as design
version 8, released in 0.3.0. See [Outcome](#outcome).

## Where a title's time goes now

Real `design_beq.py` runs, one title at a time, warm stage cache, sleep inhibited, on the
8-core Ryzen 7 PRO 8840HS this repo is developed on. CPU includes every child process (the fit
pool). Dossier 137 declines in 3 s and is left out; the other 10 titles take 42-107 s, 70 s on
average:

| Stage | Wall s/title | CPU s/title |
| --- | --- | --- |
| `fit` (`_fit_all`) | 28.9 (41%) | 133 (70%) |
| `parametric`'s own fit, inside its target stage | ~7.2 | ~22 |
| Other target construction (`counterfactual` alone is 7-8 s, single-threaded) | ~8.6 | ~8.6 |
| Judge: verify 5.1, headroom 4.4, sub feed 2.2 | 11.7 (17%) | 12 |
| Outside the pipeline (material load, record write, start-up) | ~13 | ~13 |

The fitter is half of a title's wall time and about 82% of its CPU. The 29 September split
(fit 49%, judge 41%, target 10%) is out of date: the judge is now 17%. A full redesign runs
several titles at once and is CPU-bound, so CPU is the figure that sets its throughput. The
13 s outside the pipeline is not yet split into load and record write, and the server loads
audio differently, so it is not counted as a lever until measured on that path.

## What one fit spends

60 real `_fit_structure` tasks captured from Black Bag, 28 Years Later and Incredible Hulk (two
targets each, every shelf/peak split at 1-4 sections):

* Differential evolution is ~99% of cost evaluations; the Nelder-Mead polish ~1%. A 4-section
  fit is ~73,000 evaluations and 8.7 s.
* **The generation budget binds.** On multi-section fits DE's best is still improving close to
  generation 300: median 284 generations to reach its final value, 227 to come within 0.01 dB.
  So fewer generations is a quality trade (the ~1.4x already declined), not free.
* One evaluation is 100-120 µs: two 400-bin `magnitude_db` (~25 µs each), the ceiling grid
  (~17.5 µs), per-section Python for rounding and coefficients (~12 µs), and scipy's own
  per-member work in `updating="immediate"` (~18 µs; ~4.5 µs deferred).

## Options measured

* **Exact-preserving:** only reusing the quantised cascade for the ceiling, about 5%. Any
  rewrite of the arithmetic changes last bits, which the fit turns into a different near-equal
  optimum (TODO 28, 32), so everything substantial is a trade.
* **Score the whole population in one call, comparing in the linear domain.** The worst
  absolute dB error, the device drift and the over-lift ceiling are each monotone in the power
  ratio, so a member needs ~3 logarithms instead of one per bin per section. Agrees with the
  current formulation to 7e-10 dB. numba, fused: 9.8 µs a member on one core. numpy only, in
  chunks of 32 members: ~30 µs. Plain numpy over the whole population with complex arithmetic
  and per-bin logs: ~65 µs (memory-bound; the scalar path was already vectorised over
  frequency).
* **Quality of deferred, vectorised DE**, same NM polish and final score as production, over
  the 60 tasks (~360 s of fitting today):

  | Generations | Fitting | Better / worse / same | Best per target and section count |
  | --- | --- | --- | --- |
  | 300 | 47 s (~7.6x) | 22 / 21 / 17 | 8 / 7 / 9; none crosses the 0.5 dB bar |
  | 600 | 98 s (~3.7x) | 34 / 11 / 15 | worst regression +0.13 dB |
  | 1000 | 164 s (~2.2x) | 39 / 7 / 14 | one target newly clears 0.5 dB |

  At 300 generations it is a wash on quality. More generations need a measured missed usable
  fit first (TODO 23), so 300 stays.
* **GPU: rejected.** The cost needs float64: 28-bit coefficient rounding and poles within
  ~2e-4 of z=1 (3 Hz at 96 kHz) are below float32's resolution, so the drift term cannot be
  computed. Consumer GPUs run float64 at 1/32-1/64 rate (the 780M here has no ROCm userland
  either); batching every fit into one kernel per generation tops out around 1.5-2x over 8 cores
  on the numba kernel, for a large cost in packaging and cross-machine reproducibility.
* **Hand-written C++:** the numba kernel's inner loop is still mostly scalar (branches on band
  and ceiling bins, two divisions per section per bin). Restructured, LLVM vectorises it as
  clang would; C++ would add a compiled extension for three platforms and the executables.
* **Own DE loop**, compiled: removes scipy's ~4 µs a member and makes immediate updating cheap
  again. Worth ~4% of a title once the kernel lands; for redesign throughput only.

## Projection per title

Applying the measured factors to the fit and `parametric`'s fit:

| | Wall s/title | CPU s/title | Redesign throughput |
| --- | --- | --- | --- |
| 0.2.12 | 70 | 190 | 1x |
| numpy kernel (~3.5x on the fit) | ~44 | ~79 | ~2.4x |
| numba kernel (~7.6x) | ~39 | ~55 | ~3.4x |
| plus own DE loop (~20x) | ~36 | ~42 | ~4.5x |

Assumes the fit stage keeps its parallel efficiency as it shrinks; at ~4 s pool start-up and
any per-worker compile start to count.

## The build

The numba kernel, a numpy fallback when numba is unavailable, deferred updating, `maxiter`
300; the Nelder-Mead polish and the returned residual stay on the exact scalar cost. A trade,
so it goes through the refit probe on every title and variant, both protocol seeds and the
corpus, and bumps `DESIGN_VERSION` with its `impact.toml` declaration.

## Outcome

Built as `beqforge/fit_kernel.py`, wired into `_fit_structure`: differential evolution with
`vectorized=True`, `updating="deferred"`, `polish=False`, still 300 generations at popsize 20;
Nelder-Mead and the returned residual on the scalar cost as before. numba 0.68 joins the
`designer` and `all` extras (it caps numpy below 2.6). Design version 8.

**Same answer whichever kernel runs.** numpy computes every coefficient, every grid
trigonometric and every logarithm for both paths, and the kernels only multiply, add, divide and
take maxima, in the same order. `tests/test_fit_kernel.py` holds them to bitwise equality over
every case (device at the fit's rate and another, with and without a ceiling, with no device)
and holds the population cost to the scalar cost within 1e-6 dB. The record's `timings.fit.kernel`
says which ran, and `tools/smoke_test_exe.py` now fails a frozen build that fell back to numpy.

**Speed, real runs** (`design_beq.py`, the 11 baseline titles one at a time, warm cache, sleep
inhibited, Python 3.13, same machine as the measurement above):

| | 0.2.12 | design version 8 | |
| --- | --- | --- | --- |
| all 11 titles, wall | 703 s | 283 s | 2.5x |
| all 11 titles, CPU | 1905 s | 373 s | 5.1x |
| `fit` stage, wall | 289 s | 29 s | 10x |
| `fit` stage, CPU | 1331 s | 113 s | 11.8x |
| per designing title | 70 s, 190 CPU-s | 28 s, 37 CPU-s | |

`parametric`'s own fit was cached in every version 8 run and refitted in five 0.2.12 runs (~72 s
between them); without it the per-title gain is ~2.2x rather than 2.5x. A title is now judging
(32%), target construction (21%) and ~9 s outside the pipeline before it is fitting (10%). A cold
numba compile costs ~0.6 s of import and ~0.7 s of compile per process (0.08 s from its cache), so
a onefile executable, which unpacks afresh, pays ~1.3 s per fit worker, in parallel.

**Decisions, refit probe** (all 54 titles and variants, both modes, `a20ed8c` against the change):
a re-roll among near-equal optima, as any change to the fit's arithmetic is (TODO 28, 32), and no
worse on balance. Of 225 candidates' fit errors 82 improved, 90 got worse and 53 stayed (median
change 0.000 dB; 17 worse and 18 better by more than 0.5 dB). Default mode: 5 verdicts pass to
fail, 8 fail to pass, 7 winners changed, one swap from designed to declined
(Incredible_Hulk__BW16_30__n80, whose parametric fit improved from 1.055 to 0.971 dB and now
trips the cliff check at 110.9 dB/oct against the input's 103.6). `--content-edge`: 15 to fail,
17 to pass, 10 winners, no swap. That is the size of row 32's measured instability (a 0.004 dB
perturbation of the input flips 14 winners and 33 verdicts). No baseline title's winner changed
in either mode.

**Decisions, real runs** (the 11 titles, `compare_verdicts.py` against 0.2.12's records from the
same timing runs): no verdict and no accepted candidate changed; section counts and types moved
on seven titles. Three accepted cascades moved by `impact.MOVED`, all still `flatten`. Their
corrected low ends stay within 1.1 dB of 0.2.12's inside the judged band (rms 0.37-0.70 dB), but
that is not reassurance: two of the moves land where they matter most, near the top of the band
(see below):

* Black Bag: three sections (1.30 dB) became one low shelf (1.89 dB). Row 32's fewest-sections
  rule: the best multi-section fit now sits within 0.5 dB of the single shelf, which it did not.
  It drifts 0.13 dB on publication rounding where the three sections drifted 1.73.
* 28 Years Later: two shelves (0.74 dB) became a shelf and a peak (0.86 dB).
* Obsession: three shelves (0.76 dB) became three shelves placed differently (0.72 dB).

**Where the moves land.** By a flat 1 dB line these were the three moves; by `impact.MOVED`'s
line as it now stands (20/f dB, capped at 2 dB at 10 Hz and below) they still are, but for other
reasons. 28 Years Later differs by 1.13 dB at 33 Hz and Obsession by 1.09 dB at 29 Hz, against a
line of about 0.6-0.7 dB there. Black Bag's 1.80 dB is at 15 Hz, within its line; it moves on 0.60
dB at 50 Hz. Send Help's 0.98 dB is at 5 Hz, which doesn't count, but its 0.5-0.6 dB at 20-50 Hz is
close. The fit is the reason: it scores the worst absolute dB error the same at every frequency,
so it treats near-equal fits as interchangeable wherever their error sits, and a re-roll among
them (TODO 28, 32) can move the top of the band. Whether the fit should use the same
frequency-dependent tolerance is TODO 37: [weighting the search works, and waits on TODO 36](fit-weighting.md).

**Protocol** (seeds 101 and 947): false acceptances 1 and 1, unchanged; abstentions unchanged.
One selection moved, `varying_filtered` on seed 101, parametric to flatten, its recovery error
16.76 to 18.18 dB RMS: worse, on a case neither version recovers.

**Corpus** (seeds 1-9, against the same run on `a20ed8c`): gate 0/45, upper bound 0.079, PASS,
unchanged; every shape's false acceptances unchanged (natural_droop 5/9 as before); filtered
true positives 7/9, median recovery 1.375 to 1.369 dB RMS. Three filtered cases moved: 8 better
(1.01 to 0.71), 9 worse (1.15 to 1.34), 3 changed strategy for the same recovery.

**Executable.** Built locally with PyInstaller 6.22 (numba and llvmlite hooks from
`pyinstaller-hooks-contrib`), 147 MB on Linux; the smoke test, including the new kernel check,
passes. Windows and macOS are CI's.

**Impact basis** (`impact.toml`, `fit.search`): from the refit probe's default mode, by
`impact.MOVED`: no_fit 0/1, declined_after_fit 0/21, designed_with_failures 14/18,
designed_all_passed 2/14 (13/18 and 2/14 by the flat 1 dB line it replaced). Not a library sample: 43 of the 54 are injected variants, and every
declined_after_fit case is one. 0.3.0 shipped with it; measure a library sample and replace it in 0.3.1,
as version 7's basis was.

**Left for later** (TODO 23): reuse of repeated numerical identities, the ~9 s a title outside the
pipeline (measure on the server path first), and an own compiled DE loop, which is now worth a
few per cent of a title and only matters for redesign throughput.
