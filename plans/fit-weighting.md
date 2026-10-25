# Weighting the fit's error by frequency (TODO 37)

Tried 25 October 2026 on design version 8 (`4e9e539`); neither variant adopted. The code is on
branch `experiment-fit-weighting` (`5753a14`, variant B).

## Why

The fit scores the worst absolute dB error the same at every frequency, so it treats near-equal
fits as interchangeable wherever their error sits. A dB deep in the boost doesn't matter; the
same dB near the top of the band is a change of balance. Version 8's re-roll (TODO 23) moved 28
Years Later by 1.13 dB at 33 Hz and Obsession by 1.09 dB at 29 Hz with their errors unchanged.
`impact.MOVED` now uses 20/f dB, capped at 2 dB at 10 Hz and below, so the question was whether
the fit should use the same line.

## What was built

A per-bin weight on the fit's error, used by the search (`PopulationCost`), the polish, the
residual the fitter returns and pruning. So the residual bar (0.5 dB), the near-equal window
(0.5 dB, TODO 32) and settling all apply to the weighted error. The drift term is weighted
too; the over-lift ceiling, the reported `residual_db` and the judge are untouched. The
weighted population cost matches the scalar cost and numba matches numpy bit for bit. It takes
a logarithm per bin, so it costs 8.0 µs a member against 3.4 µs.

* **Variant A:** weight f/20 Hz, held at 0.5 below 10 Hz and 2.5 above 50 Hz (dB at 20 Hz).
* **Variant B:** weight f/40 Hz, held at 0.25 below 10 Hz and 1 from 40 Hz up. The 0.5 dB bar
  is then exactly 20/f dB, and the bar above 40 Hz stays what it was.

## Results, against version 8

Refit probe (54 titles and variants, default mode), both protocol seeds, corpus seeds 1-9, same
machine. Errors are each published cascade against its own target, measured flat for both.

| | Version 8 | A | B |
| --- | --- | --- | --- |
| median worst error, 5-10 Hz | 1.09 | 1.74 | 1.88 |
| 10-20 Hz | 1.16 | 1.55 | 1.64 |
| 20-30 Hz | 1.05 | 0.83 | 0.89 |
| 30-50 Hz | 1.01 | 0.54 | 0.61 |
| above 50 Hz | 0.64 | 0.33 | 0.43 |
| mean sections | 2.56 | 2.62 | 2.33 |
| verdicts pass to fail / fail to pass | | 11 / 9 | 12 / 14 |
| real titles' winners changed | | Caught Stealing, Send Help | Safe House, Send Help |
| protocol | | unchanged | unchanged |
| corpus gate; filtered | 0/45; 7/9, 1.37 dB | 0/45; 8/9, 1.85 dB | 0/45; 8/9, 1.85 dB |

**A fails.** Weighted at 2.5 above 50 Hz, the bar there is 0.2 dB, and the fitter spends
sections on fractions of a dB at 38-140 Hz that the judge refuses as not having earned their
slot. 28 Years Later's parametric went to four sections, with peaks at 38.5 Hz (0.96 dB) and
102 Hz (0.11 dB), and failed. Black Bag's counterfactual added shelves at 62 and 138 Hz and
failed, and its flatten went from one section to three.

**B passes the gates and fails on the designs that win.** Across all candidates, error at 30-50
Hz falls. But the winners mostly don't improve where it matters, and they lose a lot below 20 Hz:

| Winner's error against its target (dB) | 5-10 Hz | 20-30 Hz | 30-40 Hz | 40-60 Hz |
| --- | --- | --- | --- | --- |
| 28 Years Later: v8, 2 sections | 0.86 | 0.86 | 0.85 | 0.83 |
| 28 Years Later: B, 1 section | 3.59 | 1.64 | 1.08 | 0.32 |
| Obsession: v8 to B | 0.72 to 2.12 | 0.72 to 0.74 | 0.46 to 0.63 | 0.44 to 0.52 |
| Safe House (new winner) | 0.65 to 2.56 | 0.82 to 1.07 | 0.84 to 0.81 | 0.85 to 0.66 |
| Send Help (new winner) | 0.69 to 1.06 | 0.70 to 0.36 | 0.59 to 0.35 | 0.38 to 0.25 |

The near-equal window is the reason. It is 0.5 dB of weighted error, which at a weight of 0.25 is
2 dB at 10 Hz. The pipeline keeps the first passing fit within that window, fewest sections
first (TODO 32). So a single shelf 3.6 dB off at 5-10 Hz, and worse at 30-40 Hz, ties with the
two-section fit and wins on section count. The weight works on the search; the bars built on the
error turn it into fewer sections rather than a better top of the band.

## What could still work

Not measured:

* weight only the search's objective, and keep the residual bar, the near-equal window and
  pruning on the flat error;
* keep the weight, but hold the near-equal window in flat dB, or narrow it by the weight;
* a gentler slope: a floor of 0.5 rather than 0.25 below 10 Hz.
