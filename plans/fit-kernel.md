# A faster fit for 0.3: the population-vectorised cost (TODO 23)

Measured 25 October 2026 on `a20ed8c` (0.2.12, design version 7); build in progress for 0.3.

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
