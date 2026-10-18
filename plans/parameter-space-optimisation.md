# Optimising a filter's parameters for several device profiles at once

**Status: implemented (`beqoptimiser.optimise_parameters`, 18 October 2026); released with the next tag. See [Outcome](#outcome-18-october-2026).** Originally: A request from beqdesigner (October 2026), for a feature in its main window: a filter
designer picks one or more device profiles, sees what each does to the filter, and asks for the filter to be optimised
before it is published. The person who owns both projects decided that the search belongs here, in `beqoptimiser`, and
beqdesigner only provides the interface. Parameter search is already listed as a follow-up in
[F2-catalogue-filter-optimisation.md](F2-catalogue-filter-optimisation.md).

## What is different from `optimise()`

`optimise()` searches the coefficients of one cascade for one rate and precision, and returns custom SOS. This request
needs:

1. **Parameters out, not coefficients.** The result is each section's `freq`, `q` and `gain` (and its type unchanged).
   A BEQ is published and loaded as parameters: beqdesigner's projects and exports, the catalogue, and ezbeq (which
   rebuilds RBJ coefficients from the parameters at each device's rate when it has none published for it) all carry
   parameters. Optimised parameters therefore need no new catalogue schema and reach every consumer as they are.
2. **Several profiles jointly.** The same parameters are realised on every device. The search minimises the worst
   matching-band error across all the profiles the caller passes (a minimax), so a change that helps one device cannot
   quietly make another worse. The result reports each profile's error before and after.
3. **Representable parameters.** Only values beqdesigner can show and the exports keep: `freq` to 0.01 Hz, `q` (and a
   shelf's `S`) to 0.0001, `gain` to 0.01 dB. Search on that grid, or round and re-validate, so the result is exactly
   what is published.

## Proposed interface

```python
optimise_parameters(
    sections,                 # the cascade as authored: beqoptimiser.core.Section (type, freq, q, gain), in order
    *,
    profiles,                 # [(rate, precision), ...]: 48000 or 96000, with Float32() or FixedPoint(i, f)
    settings=None,            # Settings: margin, band, plus the parameter bounds below
) -> ParameterResult
```

`ParameterResult` carries the outcome (with the same `replacement`/`improvement`/`no_replacement` rules as
`optimise()`), the new sections when there is one, and per profile: the original error, the candidate's error and its
guard (out-of-band) error, with the numerical version and settings for provenance.

* **Reference:** each section's ideal float64 RBJ response, from the authored parameters, as now.
* **Realised:** for each profile, the coefficients computed from the candidate parameters at that rate in float64,
  then stored with that profile's precision (`quantise`), as a device that receives parameters (or coefficients
  computed from them) would hold them.
* **Bounds:** the parameters may only move as far as keeps the filter the author's: proposed defaults of ±1% in
  frequency, ±2% in Q and ±0.1 dB in gain per section, configurable. A result outside them is not a correction of
  the same filter.
* **Sections it cannot change:** the request may contain other biquads (pass filters, a gain stage). They stay
  fixed but count in the cascade's response; a cascade with nothing searchable returns `no_replacement`.

## Open points for this repository to decide

* **Whose RBJ:** the coefficients must be computed as the consumers compute them. beqdesigner (`model/iir.py`),
  `beq_common.biquad` and ezbeq each implement the cookbook; check that they agree, including the shelf Q/S conversion,
  to the precision a profile can resolve. If they do not, name the one a profile models.
* **Search method:** a coordinate or pattern search on the parameter grid, a scalar minimiser per parameter as now, or
  something else; deterministic, bounded and cacheable as `optimise()` is.
* **Whether it ever helps:** benchmark against direct-coefficient search on the catalogue's float32/96 kHz worst cases
  (e.g. the 5 Hz Q 6 peak the 2x4 HD pilot measured). Parameter search may recover little where the coefficient grid is
  coarse; the outcome rules already report that honestly as `no_replacement`.

## What beqdesigner will build around it

* Device profiles: one per device it exports to (miniDSP HD-class: float32 at 96 kHz; earlier miniDSPs: Q5.23 fixed
  point at 48 kHz; HTP-1 and JRiver compute in double precision, so nothing to show), plus profiles a user defines
  (rate and storage). It uses `beqoptimiser`'s `Float32`/`FixedPoint` and `magnitude` for part (a).
* Part (a), now: the main chart shows the filter as each chosen profile realises it, and its error against the ideal.
* Part (b), after this ships: an *Optimise for devices* action on the filter, which calls `optimise_parameters` with the
  ticked profiles, shows the before/after errors per profile and lets the designer accept the new parameters.

## Completion criteria

* `optimise_parameters` in `beqoptimiser` with tests covering: both rates, both precisions, the joint (minimax)
  objective protecting each profile, the parameter grid and bounds, fixed non-searchable sections, and cache identity.
* A short benchmark against `optimise()` on the catalogue report's worst float32 cases, recorded here.
* Released in a `beqforge` version beqdesigner can pin.

## Outcome (18 October 2026)

`optimise_parameters(sections, *, profiles, settings=None, cache=None)` in
`beqoptimiser/parameters.py`, cached through `beqoptimiser/cache.py`, exported from `beqoptimiser`,
documented in [docs/optimiser.md](../docs/optimiser.md#parameters-for-several-devices). The
interface is as proposed, with three additions: `ParameterSettings` (margin, band, the bounds,
`max_evaluations`) rather than `Settings`; `Fixed` for sections the search may not change, given
as SOS per rate; and identical adjacent sections (a repeated shelf) moving together, so a shelf ×3
stays one.

**Open points, decided.**

* **Whose RBJ.** beqdesigner (`model/iir.py`), `beq_common.biquad` and ezbeq (`ezbeq/iir.py`)
  agree bit for bit on the publication grid: 20,000 random peaks and shelves at 48 and 96 kHz,
  maximum coefficient difference 0. beqdesigner's `BiquadWithQ.__init__`, the three
  `_compute_coeffs` and `q_to_s`/`s_to_q` are AST-identical to `beq_common`'s. Off the grid,
  every case differed: ezbeq rounds Q to 4 and gain to 3 decimals before computing, the others
  do not (`w0` uses the unrounded frequency in all three). So the search never leaves the grid,
  and `Section.sos` models every consumer. A shelf's Q is searched, as stored.
* **Search method.** Deterministic compass search on the integer grid, steps halving from half
  each bound to one unit, then every ±1 combination of each section's three parameters until
  nothing improves; only changed sections are re-evaluated. Joint objective: the worst
  profile's matching-band error, with any step refused that makes a profile worse than both its
  original error and the margin. The original is the authored parameters on the grid.
* **Whether it ever helps.** Yes. `tools/experiments/parameter_benchmark.py` on the committed
  report's 25 worst distinct cascades at each rate (catalogue `5ea769f`, the report's snapshot,
  SHA-256 checked), float32 storage, both searches uncached from the authored parameters:

  | Rate | Original | Within margin (coefficient / parameter) | Median after | Time per entry |
  | --- | --- | --- | --- | --- |
  | 48 kHz | 2.5-5.7 dB | 20 / 21 | 0.11 / 0.21 dB | 1.5-11 s / 0.2-4 s |
  | 96 kHz | 9.8-16.6 dB | 16 / 10 | 0.45 / 0.69 dB | 1.2-14 s / 0.4-4 s |

  Both published (replacement or improvement) for all 50; all 50 were on the grid. Neither
  dominates: parameter search met the margin where coefficient search only improved (Predator
  96 kHz 0.29 vs 2.12 dB, Unbreakable 48 kHz 0.21 vs 0.69 dB) and the reverse (Listening 96 kHz
  1.52 vs 0.08 dB). At 96 kHz the coefficient grid is finer than a ±1%/2%/0.1 dB parameter
  neighbourhood can reach, which is where it falls behind. Its result needs no published
  coefficients and reaches every consumer as it is.

**Checks.** `tests/test_optimiser_parameters.py` (19): both rates and precisions, the joint
objective's per-profile guarantee, grid and bounds (and zero bounds giving `no_replacement`),
fixed sections kept and counted, nothing searchable, off-grid authored parameters, repeated
shelves, invalid requests, a cache hit, the key covering sections/profiles/settings, an
off-grid tampered entry being a miss, and the coefficient seed's identity unchanged. The
parameter cache key adds `parameters.py`'s hash and `PARAMETER_VERSION` to
`implementation_identity()` without changing it, so the bundled seed still loads.

**Not done.** Phase is not considered, as for `optimise`. Bounds are not derived from what a
listener would notice; ±1%/2%/0.1 dB is the proposal's default, configurable.
